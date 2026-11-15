"""Streamed, deterministic 10 km island world for the sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
import atexit
from concurrent.futures import ThreadPoolExecutor
import json
from math import cos, exp, pi, sin, sqrt
import os
from pathlib import Path
from threading import Thread
from random import Random
from collections import OrderedDict

from ursina import Entity, Mesh, Vec3, color, destroy

from ai.civilian_ai import CivilianState
from characters.civilian import Civilian
from combat.damage_system import impact_damage
from game.art_style import SUN_DIRECTION, VEGETATION_SHADER, WATER_SHADER, shade
from game.island_frame import IslandFrame
from game.effects import DestructionBurst, TimedEffect
from movement.flight_physics import Vec3 as SimVec3
from world import native_bridge as native
from world.buildings import Building
from world.destructible_props import DebrisBudget
from world.destruction_math import (DestructionScales, crater_height_delta,
                                    superhuman_impact_damage, sweep_point_aabb)
from world.interactive_objects import DebrisPiece, DestructibleEntity, TrafficVehicle
from world.population import (civilian_capacity, civilians_per_chunk,
                              traffic_capacity, traffic_per_chunk)
from world.tree_destruction import FallingTree

_SUN_LENGTH = sqrt(sum(value * value for value in SUN_DIRECTION))
TERRAIN_SUN = tuple(value / _SUN_LENGTH for value in SUN_DIRECTION)


@dataclass
class IslandChunk:
    key: tuple[int, int]
    entities: list[Entity] = field(default_factory=list)
    objects: list[Entity] = field(default_factory=list)
    civilians: list[Civilian] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)
    tree_colliders: list[Entity] = field(default_factory=list)
    tree_visuals: Entity | None = None
    visual_lod: bool = False
    lod_vertices: list = field(default_factory=list)
    lod_triangles: list = field(default_factory=list)
    lod_colors: list = field(default_factory=list)
    tree_specs: list[tuple] = field(default_factory=list)
    quality: str = "low"


class IslandWorld:
    """Procedural island terrain with deterministic, distance-streamed districts."""

    NATURAL_ONLY = True
    EXTENT = 5_000.0
    CHUNK_SIZE = 500.0
    LOAD_RADIUS = 1
    async_chunks = False  # the windowed game turns this on; tests stay on one thread, frame for frame
    TERRAIN_STEPS_BY_QUALITY = {"low": 200, "medium": 280, "high": 360, "ultra": 440}
    # Keep the same terrain samples and triangle count with fewer, larger
    # meshes; this cuts per-frame scene traversal and draw submission overhead.
    TERRAIN_SECTORS = 8
    TERRAIN_SAVE_KEY = "__terrain_impacts__"
    CIVILIAN_SAVE_KEY = "__civilian_states__"
    TREE_SAVE_KEY = "__tree_states__"
    TREE_MAX_HEALTH = 120.0
    TERRAIN_PATCH_SUBDIVISIONS = 16
    MAX_TERRAIN_IMPACTS = 300
    TERRAIN_REBUILD_INTERVAL = .3  # collision changes at once; the visible mesh catches up

    def __init__(self, game, settings):
        self.game = game
        self.settings = settings
        self.quality = str(settings.quality).lower()
        self.terrain_steps = self.TERRAIN_STEPS_BY_QUALITY.get(self.quality, 200)
        self.random = Random(2026)
        game.random = self.random
        self.planet = IslandFrame(self)
        self.game.planet = self.planet
        self.ground_size = self.EXTENT * 2.0
        self.static_art: list[Entity] = []
        self.objects: list[DestructibleEntity] = []
        self._objects_by_chunk: dict[tuple[int, int], list[DestructibleEntity]] = {}
        self.debris: list[Entity] = []
        self.civilians: list[Civilian] = []
        self._civilians_by_chunk: dict[tuple[int, int], list[Civilian]] = {}
        self._civilian_pool: list[Civilian] = []
        self._traffic_pool: list[TrafficVehicle] = []
        self.civilian_states: dict[str, dict[str, object]] = {}
        self.tree_states: dict[str, dict[str, float | bool]] = {}
        self.animals = []
        self.traffic: list[TrafficVehicle] = []
        self.buildings: list[Building] = []
        self._buildings_by_chunk: dict[tuple[int, int], list[Building]] = {}
        self.effects: list = []
        self.scales = DestructionScales()
        self.debris_budget = DebrisBudget({"low": 64, "medium": 144,
                                           "high": 320, "ultra": 480}.get(self.quality, 64))
        self.debris_step_interval = {"low": 1/30, "medium": 1/45,
                                     "high": 1/60, "ultra": 1/60}.get(self.quality, 1/30)
        self.chunks: dict[tuple[int, int], IslandChunk] = {}
        self._chunk_data_cache: OrderedDict[tuple[int, int], IslandChunk] = OrderedDict()
        self._chunk_worker = None
        self._pending_chunk_data: dict = {}
        self._pending_sector = None
        self._save_thread = None
        # Repeated high-speed routes can cross several dozen 500 m chunks
        # before returning. Keep their deterministic natural geometry bounded
        # in memory so the return leg only recreates scene nodes.
        self._chunk_cache_limit = 48
        self.object_states: dict[str, dict[str, float | bool]] = {}
        self.terrain_impacts: dict[str, dict[str, float | str]] = {}
        self._terrain_impacts_by_chunk: dict[tuple[int, int], list[dict]] = {}
        if native.available:  # the same maths, compiled; the methods below remain the fallback
            native.terrain_setup(IslandFrame.WATER_LEVEL, *TERRAIN_SUN, self.EXTENT)
            native.set_craters([])
            self._base_height_at = native.base_height
            self.height_at = native.height
        self._terrain_sector_entities: dict[tuple[int, int], Entity] = {}
        self._pending_terrain_sectors: set[tuple[int, int]] = set()
        self._terrain_cell_cache: dict[tuple[int, int, int], tuple] = {}
        self._terrain_rebuild_wait = 0.0
        self._debris_pool: list[Entity] = []
        self._explosion_pool: list = []
        self._active_explosions: list = []
        self._explosion_audio = []
        self._explosion_audio_cursor = 0
        self._chain_queue: list[tuple] = []
        self._processing_chain = False
        self._current_chain_depth = 0
        self.MAX_CHAIN_DEPTH = 3
        self.MAX_CHAIN_EVENTS_PER_TICK = 12
        self.MAX_ACTIVE_EXPLOSIONS = 8
        self.MAX_POOLED_DEBRIS = 24
        save_override = os.environ.get("SENTRY_DESTRUCTION_SAVE")
        if save_override:
            self.damage_save_path = Path(save_override)
        else:
            local_data = Path(os.environ.get(
                "LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
            self.damage_save_path = local_data / "Sentry" / "island_destruction.json"
        self._damage_state_dirty = False
        self._damage_save_timer = 0.0
        self._load_damage_state()
        atexit.register(self.save_damage_state)
        self._initialized = False
        self._terrain_colors: dict = {}
        self.water = None
        self.ground = None
        self._terrain_art = None
        self.distant_lod = None
        self._distant_lod_dirty = False
        self._distant_lod_dirty_sectors: set[tuple[int, int]] = set()
        self._distant_lod_sectors: dict[tuple[int, int], Entity] = {}
        self._distant_lod_refresh_timer = 0.0

    def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self.water = Entity(name="island-ocean", model="plane", position=(0, -2.0, 0),
                            scale=(self.EXTENT * 8.0, 1.0, self.EXTENT * 8.0),
                            shader=WATER_SHADER, double_sided=True, collider=None)
        self.ground = Entity(name="island-terrain", model=None, collider=None)
        self._terrain_art = self._build_terrain()
        self.ground.color = color.white
        self.ground.double_sided = True
        self.ground.collider = None
        self.static_art.extend((self.water, self.ground))
        self._stream_chunks(0.0, 0.0, immediate=True)
        self._refresh_distant_lod()

    @staticmethod
    def _footprint_value(x: float, z: float) -> float:
        return IslandFrame.boundary_value(x, z)

    def contains_position(self, x: float, z: float) -> bool:
        return self._footprint_value(x, z) <= 1.0

    @staticmethod
    def district_at(x: float, z: float) -> str:
        ax, az = abs(x), abs(z)
        if ax < 1_400 and az < 1_400:
            return "downtown"
        if 1_500 < x < 3_900 and -1_900 < z < 1_300:
            return "luxury"
        if abs(z) > 3_900 or abs(x) > 4_350:
            return "coastal"
        if z > 2_000:
            return "mountain"
        if x < -1_400 and abs(z) < 3_500:
            return "forest"
        return "rural"

    def _base_height_at(self, x: float, z: float) -> float:
        x, z = float(x), float(z)
        footprint = self._footprint_value(x, z)
        if footprint >= 1.0:
            return IslandFrame.WATER_LEVEL
        coast = max(0.0, 1.0 - footprint ** .5)
        beach = max(0.0, min(1.0, coast / .055))
        rolling = (9.0 * sin(x * .0021 + z * .0013)
                   + 7.0 * cos(z * .0018 - x * .0011)
                   + 3.5 * sin((x + z) * .0052))
        mountain = 245.0 * exp(-(((x - 1_450.0) / 1_800.0) ** 2
                                 + ((z - 2_900.0) / 2_000.0) ** 2) * 1.55)
        interior = max(4.0, 24.0 + rolling + mountain) * min(1.0, coast / .18)
        return max(0.0, min(330.0, beach * 3.0 + interior * (1.0 - beach) + beach * rolling * .12))

    def height_at(self, x: float, z: float) -> float:
        """Collision height including persistent, localized impact craters."""
        x, z = float(x), float(z)
        height = self._base_height_at(x, z)
        cx, cz = int(x // self.CHUNK_SIZE), int(z // self.CHUNK_SIZE)
        for ix in range(cx - 1, cx + 2):
            for iz in range(cz - 1, cz + 2):
                for crater in self._terrain_impacts_by_chunk.get((ix, iz), ()):
                    dx, dz = x - crater["x"], z - crater["z"]
                    distance = sqrt(dx * dx + dz * dz)
                    height += crater_height_delta(distance, crater["radius"], crater["depth"])
        return max(-2.0, height)

    def _terrain_color(self, x: float, z: float, height: float):
        """Painted ground with the sun baked in, cached per point because rebuilds repeat."""
        key = (x, z)
        cached = self._terrain_colors.get(key)
        if cached is None:
            cached = self._terrain_colors[key] = self._paint_terrain(x, z, height)
        return cached

    def _sync_native_craters(self) -> None:
        """The compiled height keeps its own copy of the craters; call after any change to them."""
        if native.available:
            native.set_craters([(cx, cz, float(crater["x"]), float(crater["z"]), float(crater["radius"]),
                                 float(crater["depth"]))
                                for (cx, cz), bucket in self._terrain_impacts_by_chunk.items()
                                for crater in bucket])

    def _prepaint_terrain(self, points: list) -> None:
        """Paint a large batch on every core, ready for the cell builds that are about to ask."""
        fresh = [point for point in points if point not in self._terrain_colors]
        for point, packed in zip(fresh, native.paint_many(fresh)):
            self._terrain_colors[point] = color.rgb32(packed >> 16, (packed >> 8) & 255, packed & 255)

    def _paint_terrain(self, x: float, z: float, height: float):
        if native.available:
            packed = native.paint(x, z, height)
            return color.rgb32(packed >> 16, (packed >> 8) & 255, packed & 255)
        probe = 9.0
        slope_x = (self._base_height_at(x + probe, z) - height) / probe
        slope_z = (self._base_height_at(x, z + probe) - height) / probe
        scale = 1.0 / sqrt(slope_x * slope_x + slope_z * slope_z + 1.0)
        sun_x, sun_y, sun_z = TERRAIN_SUN
        lit = max(0.0, (-slope_x * sun_x + sun_y - slope_z * sun_z) * scale)
        steep = 1.0 - scale

        # Large soft patches of meadow and deep grass, not a uniform green.
        patch = (sin(x * .0037 + z * .0021) * cos(z * .0043 - x * .0017)
                 + .45 * sin(x * .017 - z * .013)) * .5 + .5
        patch = max(0.0, min(1.0, patch))
        patch = patch * patch * (3.0 - 2.0 * patch)
        red = 62.0 + (134.0 - 62.0) * patch
        green = 108.0 + (152.0 - 108.0) * patch
        blue = 54.0 + (66.0 - 54.0) * patch
        if height > 120.0:  # high meadow cools towards the mountain
            high = min(1.0, (height - 120.0) / 110.0)
            red, green, blue = red + (96.0 - red) * high, green + (120.0 - green) * high, \
                blue + (92.0 - blue) * high
        rock = min(1.0, max(0.0, (steep - .10) / .16))  # warm stone on cliffs
        red, green, blue = red + (136.0 - red) * rock, green + (122.0 - green) * rock, \
            blue + (108.0 - blue) * rock
        footprint = self._footprint_value(x, z)
        sand = min(1.0, max(0.0, (footprint - .90) / .055))  # grass melts into the beach
        red, green, blue = red + (226.0 - red) * sand, green + (202.0 - green) * sand, \
            blue + (158.0 - blue) * sand

        light = .66 + .52 * lit  # the cool side stays readable, the sun side glows
        warmth = lit * .10
        return color.rgb32(int(min(255.0, red * light * (1.0 + warmth))),
                           int(min(255.0, green * light)),
                           int(min(255.0, blue * light * (1.0 - warmth * .9 + (1.0 - lit) * .12))))

    def _build_terrain(self):
        """Create independently rebuildable terrain sectors for local craters."""
        meshes = []
        if self.ground is None:
            return meshes
        for sx in range(self.TERRAIN_SECTORS):
            for sz in range(self.TERRAIN_SECTORS):
                key = (sx, sz)
                entity = self._terrain_sector_entities.get(key)
                if entity is None:
                    entity = Entity(parent=self.ground, name=f"terrain-sector-{sx}-{sz}",
                                    model=None, collider=None, double_sided=True)
                    self._terrain_sector_entities[key] = entity
                entity.model = self._build_terrain_sector(sx, sz)
                meshes.append(entity.model)
        return meshes

    def _build_terrain_sector(self, sx: int, sz: int) -> Mesh:
        step = self.EXTENT * 2 / self.terrain_steps
        start_cell_x = sx * self.terrain_steps // self.TERRAIN_SECTORS
        end_cell_x = (sx + 1) * self.terrain_steps // self.TERRAIN_SECTORS
        start_cell_z = sz * self.terrain_steps // self.TERRAIN_SECTORS
        end_cell_z = (sz + 1) * self.terrain_steps // self.TERRAIN_SECTORS
        start_x, start_z = -self.EXTENT + start_cell_x * step, -self.EXTENT + start_cell_z * step
        vertices, colors, triangles = [], [], []
        cache = self._terrain_cell_cache
        if native.available:
            corners = []
            for ix in range(end_cell_x - start_cell_x):
                x0 = start_x + ix * step
                x1 = x0 + step
                for iz in range(end_cell_z - start_cell_z):
                    if (start_cell_x + ix, start_cell_z + iz, self.terrain_steps) not in cache:
                        z0 = start_z + iz * step
                        z1 = z0 + step
                        corners.extend(((x0, z0), (x0, z1), (x1, z1), (x1, z0)))
            if corners:
                self._prepaint_terrain(corners)
        for ix in range(end_cell_x - start_cell_x):
            x0 = start_x + ix * step
            for iz in range(end_cell_z - start_cell_z):
                z0 = start_z + iz * step
                key = (start_cell_x + ix, start_cell_z + iz, self.terrain_steps)
                cell = cache.get(key)
                if cell is None:
                    cell = cache[key] = self._build_terrain_cell(x0, z0, step)
                base = len(vertices)
                vertices.extend(cell[0])
                colors.extend(cell[1])
                triangles.extend([base + index for index in cell[2]])
        return Mesh(vertices=vertices, triangles=triangles, colors=colors, static=True)

    def _build_terrain_cell(self, x0: float, z0: float, step: float) -> tuple:
        """One terrain cell's geometry, kept so a crater only recomputes the cells it touches."""
        x1, z1 = x0 + step, z0 + step
        if not self.contains_position((x0 + x1) * .5, (z0 + z1) * .5):
            return ((), (), ())
        vertices, colors, triangles = [], [], []
        impacts = self._terrain_cell_impacts(x0, x1, z0, z1)
        if not impacts:
            for x, z in ((x0, z0), (x0, z1), (x1, z1), (x1, z0)):
                vertices.append((x, self.height_at(x, z), z))
                colors.append(self._terrain_color(x, z, self._base_height_at(x, z)))
            return vertices, colors, (0, 1, 2, 0, 2, 3)
        subdivisions = self.TERRAIN_PATCH_SUBDIVISIONS
        for dx in range(subdivisions + 1):
            x = x0 + step * dx / subdivisions
            for dz in range(subdivisions + 1):
                z = z0 + step * dz / subdivisions
                vertices.append((x, self.height_at(x, z), z))
                tint = self._terrain_color(x, z, self._base_height_at(x, z))
                if any((x - crater["x"]) ** 2 + (z - crater["z"]) ** 2
                       <= crater["radius"] ** 2 for crater in impacts):
                    # Scorched earth: warm and darkened, not a black hole.
                    tint = color.rgb32(int(tint.r * 150) + 22, int(tint.g * 112) + 16,
                                       int(tint.b * 96) + 10)
                colors.append(tint)
        row = subdivisions + 1
        for dx in range(subdivisions):
            for dz in range(subdivisions):
                a = dx * row + dz
                b, c, d = a + row, a + row + 1, a + 1
                triangles.extend((a, d, c, a, c, b))
        return vertices, colors, triangles

    def _forget_terrain_cells(self, x: float, z: float, radius: float) -> None:
        """A crater's area, widened to its rim; the same steps can be reused across qualities."""
        step = self.EXTENT * 2 / self.terrain_steps
        reach = radius * 1.25
        for ix in range(int((x - reach + self.EXTENT) // step) - 1,
                        int((x + reach + self.EXTENT) // step) + 2):
            for iz in range(int((z - reach + self.EXTENT) // step) - 1,
                            int((z + reach + self.EXTENT) // step) + 2):
                self._terrain_cell_cache.pop((ix, iz, self.terrain_steps), None)

    def _terrain_cell_impacts(self, x0, x1, z0, z1):
        cx, cz = int(((x0 + x1) * .5) // self.CHUNK_SIZE), int(((z0 + z1) * .5) // self.CHUNK_SIZE)
        candidates = []
        for ix in range(cx - 1, cx + 2):
            for iz in range(cz - 1, cz + 2):
                for crater in self._terrain_impacts_by_chunk.get((ix, iz), ()):
                    radius = crater["radius"] * 1.25
                    if (crater["x"] + radius >= x0 and crater["x"] - radius <= x1
                            and crater["z"] + radius >= z0 and crater["z"] - radius <= z1):
                        candidates.append(crater)
        return candidates

    def _terrain_surface_height(self, x: float, z: float,
                                vertex_cache: dict | None = None) -> float:
        """Interpolate the rendered terrain cell so grass blades sit on its mesh."""
        if native.available:
            return native.surface_height(x, z, self.terrain_steps)
        step = self.EXTENT * 2 / self.terrain_steps
        ix = min(self.terrain_steps-1, max(0, int((x+self.EXTENT)/step)))
        iz = min(self.terrain_steps-1, max(0, int((z+self.EXTENT)/step)))
        x0, z0 = -self.EXTENT+ix*step, -self.EXTENT+iz*step
        u, v = (x-x0)/step, (z-z0)/step
        def sample(ix, iz, sample_x, sample_z):
            if vertex_cache is None:
                return self.height_at(sample_x, sample_z)
            key = (ix, iz)
            if key not in vertex_cache:
                vertex_cache[key] = self.height_at(sample_x, sample_z)
            return vertex_cache[key]

        h00 = sample(ix, iz, x0, z0)
        h01 = sample(ix, iz + 1, x0, z0 + step)
        h11 = sample(ix + 1, iz + 1, x0 + step, z0 + step)
        h10 = sample(ix + 1, iz, x0 + step, z0)
        # Terrain cells are split across the lower-left to upper-right diagonal.
        if u <= v:
            return (1-v)*h00 + (v-u)*h01 + u*h11
        return (1-u)*h00 + v*h11 + (u-v)*h10

    def deform_terrain(self, position, *, radius: float, depth: float,
                       surface: str = "ground") -> dict | None:
        """Persist a crater and rebuild only the terrain sector it affects."""
        x, z = float(position.x), float(position.z)
        if not self.contains_position(x, z):
            return None
        radius = max(1.5, min(80.0, float(radius)))
        depth = max(.05, min(7.0, float(depth)))
        span = int(radius * 1.25 // self.CHUNK_SIZE) + 1
        chunk_x, chunk_z = int(x // self.CHUNK_SIZE), int(z // self.CHUNK_SIZE)
        for ix in range(chunk_x - span, chunk_x + span + 1):
            for iz in range(chunk_z - span, chunk_z + span + 1):
                self._chunk_data_cache.pop((ix, iz), None)
        key = f"{round(x / 8.0)}:{round(z / 8.0)}"
        crater = self.terrain_impacts.get(key)
        if crater is None:
            crater = {"x": x, "z": z, "radius": radius, "depth": depth,
                      "surface": str(surface)[:20]}
            self.terrain_impacts[key] = crater
            self._terrain_impacts_by_chunk.setdefault(
                (int(x // self.CHUNK_SIZE), int(z // self.CHUNK_SIZE)), []).append(crater)
            self._forget_oldest_craters()
        else:
            crater["radius"] = max(float(crater["radius"]), radius)
            crater["depth"] = min(7.0, float(crater["depth"]) + depth * .38)
        self._sync_native_craters()
        self._damage_state_dirty = True
        self._forget_terrain_cells(x, z, max(radius, float(crater["radius"])))
        sector_width = self.EXTENT * 2 / self.TERRAIN_SECTORS
        sectors_x = range(max(0, min(self.TERRAIN_SECTORS - 1,
                                     int((x - radius + self.EXTENT) / sector_width))),
                          max(0, min(self.TERRAIN_SECTORS - 1,
                                     int((x + radius + self.EXTENT) / sector_width))) + 1)
        sectors_z = range(max(0, min(self.TERRAIN_SECTORS - 1,
                                     int((z - radius + self.EXTENT) / sector_width))),
                          max(0, min(self.TERRAIN_SECTORS - 1,
                                     int((z + radius + self.EXTENT) / sector_width))) + 1)
        if self._initialized:
            for sx in sectors_x:
                for sz in sectors_z:
                    sector = (sx, sz)
                    if sector in self._terrain_sector_entities:
                        self._pending_terrain_sectors.add(sector)
        return crater

    def _forget_oldest_craters(self) -> None:
        """Keep height queries quick and the save small however much is blown up."""
        while len(self.terrain_impacts) > self.MAX_TERRAIN_IMPACTS:
            key = next(iter(self.terrain_impacts))
            old = self.terrain_impacts.pop(key)
            chunk = (int(old["x"] // self.CHUNK_SIZE), int(old["z"] // self.CHUNK_SIZE))
            bucket = self._terrain_impacts_by_chunk.get(chunk)
            if bucket and old in bucket:
                bucket.remove(old)
            self._forget_terrain_cells(old["x"], old["z"], old["radius"])
            self._mark_terrain_sectors(old["x"], old["z"], old["radius"])

    def _mark_terrain_sectors(self, x: float, z: float, radius: float) -> None:
        sector_width = self.EXTENT * 2 / self.TERRAIN_SECTORS
        for sx in range(max(0, int((x - radius + self.EXTENT) / sector_width)),
                        min(self.TERRAIN_SECTORS - 1, int((x + radius + self.EXTENT) / sector_width)) + 1):
            for sz in range(max(0, int((z - radius + self.EXTENT) / sector_width)),
                            min(self.TERRAIN_SECTORS - 1, int((z + radius + self.EXTENT) / sector_width)) + 1):
                if (sx, sz) in self._terrain_sector_entities:
                    self._pending_terrain_sectors.add((sx, sz))

    def _stream_chunks(self, x: float, z: float, *, immediate: bool = False) -> None:
        cx = int(x // self.CHUNK_SIZE)
        cz = int(z // self.CHUNK_SIZE)
        needed = {(ix, iz) for ix in range(cx - self.LOAD_RADIUS, cx + self.LOAD_RADIUS + 1)
                  for iz in range(cz - self.LOAD_RADIUS, cz + self.LOAD_RADIUS + 1)
                  if self.contains_position((ix + .5) * self.CHUNK_SIZE,
                                            (iz + .5) * self.CHUNK_SIZE)}
        changed = set()
        for key in tuple(self.chunks):
            if key not in needed:
                self._unload_chunk(key)
                changed.add(key)
        missing = [key for key in needed if key not in self.chunks]
        sentry = getattr(self.game, "sentry", None)
        if immediate:
            missing.sort()
        elif sentry is not None and missing:
            velocity = (sentry.flight.velocity if sentry.flight.is_flying
                        else sentry.ground.velocity)
            speed = velocity.length()
            prediction = min(1_000.0, speed * .35)
            if speed > 1e-4:
                predicted_x = x + velocity.x / speed * prediction
                predicted_z = z + velocity.z / speed * prediction
            else:
                predicted_x, predicted_z = x, z
            missing.sort(key=lambda key: (
                ((key[0] + .5) * self.CHUNK_SIZE - predicted_x) ** 2
                + ((key[1] + .5) * self.CHUNK_SIZE - predicted_z) ** 2,
                ((key[0] + .5) * self.CHUNK_SIZE - x) ** 2
                + ((key[1] + .5) * self.CHUNK_SIZE - z) ** 2))
            limit = {"low": 1, "medium": 2, "high": 3, "ultra": 3}.get(self.quality, 1)
            missing = missing[:limit]
        if self.async_chunks and not immediate:
            missing = self._collect_prepared_chunks(missing, needed)
        for key in missing:
            cached = self._chunk_data_cache.pop(key, None)
            if cached is not None and cached.quality == self.quality:
                self.chunks[key] = self._materialize_chunk(cached)
            else:
                self.chunks[key] = self._build_chunk(*key)
            changed.add(key)
        if changed and not self.NATURAL_ONLY:
            for key in changed:
                sx = min(3, max(0, (int(key[0]) + 10) // 5))
                sz = min(3, max(0, (int(key[1]) + 10) // 5))
                self._distant_lod_dirty_sectors.add((sx, sz))
            self._distant_lod_dirty = True

    @staticmethod
    def _append_lod_box(chunk: IslandChunk, position, size, tint) -> None:
        x, y, z = position
        sx, sy, sz = (max(.04, abs(float(value)) * .5) for value in size)
        first = len(chunk.lod_vertices)
        chunk.lod_vertices.extend(((x-sx,y-sy,z-sz),(x+sx,y-sy,z-sz),
                                   (x+sx,y+sy,z-sz),(x-sx,y+sy,z-sz),
                                   (x-sx,y-sy,z+sz),(x+sx,y-sy,z+sz),
                                   (x+sx,y+sy,z+sz),(x-sx,y+sy,z+sz)))
        chunk.lod_triangles.extend((first+0,first+2,first+1, first+0,first+3,first+2,
                                    first+4,first+5,first+6, first+4,first+6,first+7,
                                    first+0,first+1,first+5, first+0,first+5,first+4,
                                    first+1,first+2,first+6, first+1,first+6,first+5,
                                    first+2,first+3,first+7, first+2,first+7,first+6,
                                    first+3,first+0,first+4, first+3,first+4,first+7))
        chunk.lod_colors.extend((tint,) * 8)

    @staticmethod
    def _append_lod_tree(chunk: IslandChunk, x: float, z: float,
                         ground: float, scale: float, tint,
                         health_ratio: float = 1.0) -> None:
        if health_ratio <= 0.0:
            IslandWorld._append_lod_box(chunk, (x, ground + .22*scale, z),
                                        (.48*scale, .44*scale, .48*scale),
                                        color.rgb32(79, 57, 39))
            return
        IslandWorld._append_lod_box(chunk, (x, ground + 2.3*scale, z),
                                    (.30*scale, 4.6*scale, .30*scale),
                                    color.rgb32(96, 70, 52))
        if health_ratio < .75:
            # Visible charcoal tint at a few coarse health stages, without
            # rebuilding detailed per-tree entities on each laser tick.
            tint = color.rgb32(round(36 + 12 * health_ratio),
                               round(68 + 45 * health_ratio),
                               round(34 + 16 * health_ratio))
        # Two stacked cones, dark underneath and sunlit at the tip, make one clean
        # silhouette that stays legible from altitude at 14 triangles per tier.
        spin = (x * .37 + z * .19) % (pi / 3.0)
        for radius_scale, base, height, tip_light in ((1.55, 3.5, 3.9, 1.10), (1.05, 5.9, 3.5, 1.42)):
            first = len(chunk.lod_vertices)
            radius = radius_scale * scale
            base_y = ground + base * scale
            for index in range(6):
                angle = spin + index * pi / 3.0
                chunk.lod_vertices.append((x + cos(angle)*radius, base_y, z + sin(angle)*radius))
                # The sun is low in the -x, -z sky, so those sides of the ring are lit.
                facing = .5 - .5 * (cos(angle) * .54 + sin(angle) * .84)
                chunk.lod_colors.append(shade(tint, .58 + .44 * facing, .22))
            chunk.lod_vertices.append((x, base_y + height * scale, z))
            chunk.lod_colors.append(shade(tint, tip_light, .55))
            chunk.lod_vertices.append((x, base_y - .3 * scale, z))
            chunk.lod_colors.append(shade(tint, .46, .1))
            for index in range(6):
                nxt = (index + 1) % 6
                chunk.lod_triangles.extend((first+index, first+nxt, first+6,
                                            first+nxt, first+index, first+7))

    def _refresh_distant_lod(self, sectors=None) -> None:
        """Build batched sector meshes; destruction only rebuilds its own sector."""
        from ursina import Mesh, scene
        if self.distant_lod is None:
            self.distant_lod = Entity(parent=scene, name="island-distant-lod",
                                      model=None, collider=None)
        sector_keys = (set((sx, sz) for sx in range(4) for sz in range(4))
                       if sectors is None else set(sectors))
        for sx, sz in sector_keys:
            self._apply_sector_lod((sx, sz), self._sector_lod_data(sx, sz))
        self._distant_lod_dirty_sectors.difference_update(sector_keys)
        self._distant_lod_dirty = False

    def _sector_lod_data(self, sx: int, sz: int) -> tuple:
        """A sector's distant trees and grass as plain data, for any thread."""
        vertices, triangles, colors = [], [], []
        x_start, z_start = -10 + sx * 5, -10 + sz * 5
        for cx in range(x_start, x_start + 5):
            for cz in range(z_start, z_start + 5):
                center_x = (cx + .5) * self.CHUNK_SIZE
                center_z = (cz + .5) * self.CHUNK_SIZE
                if not self.contains_position(center_x, center_z):
                    continue
                # Detailed chunks already render every object and tree.
                # Excluding them from the proxy mesh prevents duplicate
                # coplanar surfaces and z-fighting near the player.
                if not self.NATURAL_ONLY and (cx, cz) in self.chunks:
                    continue
                lod_chunk = self._chunk_data(cx, cz, visual_lod=True)
                base = len(vertices)
                vertices.extend(lod_chunk.lod_vertices)
                triangles.extend(base + index for index in lod_chunk.lod_triangles)
                colors.extend(lod_chunk.lod_colors)
        return vertices, triangles, colors

    def _apply_sector_lod(self, sector: tuple, data: tuple) -> None:
        vertices, triangles, colors = data
        entity = self._distant_lod_sectors.get(sector)
        if entity is None:
            entity = Entity(parent=self.distant_lod, name=f"island-distant-lod-{sector[0]}-{sector[1]}",
                            collider=None, double_sided=True)
            self._distant_lod_sectors[sector] = entity
        entity.model = (Mesh(vertices=vertices, triangles=triangles, colors=colors, static=True) if vertices else None)
        entity.collider = None

    def _refresh_distant_lod_in_background(self) -> None:
        """One sector at a time, its data made by the worker, so distant trees falling cost the player no frame."""
        pending = self._pending_sector
        if pending is not None:
            if pending[1].done():
                self._pending_sector = None
                try:
                    self._apply_sector_lod(pending[0], pending[1].result())
                except Exception:  # noqa: BLE001  (distant scenery is never worth stopping the game for)
                    self._distant_lod_dirty_sectors.add(pending[0])
            return
        if self._distant_lod_dirty_sectors and self.distant_lod is not None:
            sector = min(self._distant_lod_dirty_sectors)
            self._distant_lod_dirty_sectors.discard(sector)
            if self._chunk_worker is None:
                self._chunk_worker = ThreadPoolExecutor(1, thread_name_prefix="chunk-data")
            self._pending_sector = (sector, self._chunk_worker.submit(self._sector_lod_data, *sector))

    def _collect_prepared_chunks(self, missing: list, needed: set) -> list:
        """Generating a chunk's data takes tens of milliseconds, and it needs no scene: a worker does that part.

        Returns the chunks ready to go into the scene this frame; their data is waiting in the cache.
        """
        pending = self._pending_chunk_data
        for key, future in tuple(pending.items()):
            if not future.done():
                continue
            del pending[key]
            if key not in needed:
                continue
            try:
                data = future.result()
            except Exception:  # noqa: BLE001  (one bad chunk must not stop the game: it will simply be built where it is)
                continue
            if data.quality == self.quality:
                self._chunk_data_cache[key] = data
        ready = []
        for key in missing:
            cached = self._chunk_data_cache.get(key)
            if cached is not None and cached.quality == self.quality:
                ready.append(key)
            elif key not in pending and len(pending) < 2:
                if self._chunk_worker is None:
                    self._chunk_worker = ThreadPoolExecutor(1, thread_name_prefix="chunk-data")
                pending[key] = self._chunk_worker.submit(self._chunk_data, *key)
        return ready

    def _build_chunk(self, cx: int, cz: int, *, visual_lod: bool = False) -> IslandChunk:
        """Build only natural ground cover and trees for the active island."""
        chunk = self._chunk_data(cx, cz, visual_lod=visual_lod)
        return chunk if visual_lod else self._materialize_chunk(chunk)

    def _chunk_data(self, cx: int, cz: int, *, visual_lod: bool = False) -> IslandChunk:
        """A chunk's trees and grass as plain data. It touches nothing in the scene, so any thread can do it."""
        chunk = IslandChunk((cx, cz), visual_lod=visual_lod, quality=self.quality)
        rng = Random((cx * 73_856_093 ^ cz * 19_349_663 ^ 2026) & 0xffffffff)
        center_x = (cx + .5) * self.CHUNK_SIZE
        center_z = (cz + .5) * self.CHUNK_SIZE
        district = self.district_at(center_x, center_z)
        tree_count = {"downtown": 14, "luxury": 28, "coastal": 15,
                      "forest": 72, "mountain": 42, "rural": 34}.get(district, 24)
        quality_scale = {"low": .75, "medium": 1.0, "high": 1.25, "ultra": 1.4}.get(self.quality, .75)
        tree_count = max(4, int(tree_count * quality_scale))

        # Clustered, deterministic distributions create forest patches and open
        # grassy clearings instead of a uniform grid of identical trees.
        cluster_centers = [(center_x + rng.uniform(-180, 180),
                            center_z + rng.uniform(-180, 180))
                           for _ in range(max(3, tree_count // 18))]
        tree_vertices, tree_triangles, tree_colors = [], [], []
        for index in range(tree_count):
            for _attempt in range(12):
                if rng.random() < .2:
                    tx = center_x + rng.uniform(-238, 238)
                    tz = center_z + rng.uniform(-238, 238)
                else:
                    cluster_x, cluster_z = rng.choice(cluster_centers)
                    tx = cluster_x + rng.gauss(0, 54)
                    tz = cluster_z + rng.gauss(0, 54)
                if not (-245 < tx-center_x < 245 and -245 < tz-center_z < 245):
                    continue
                if not self.contains_position(tx, tz):
                    continue
                ground = self.height_at(tx, tz)
                if ground < 3.0:
                    continue
                if abs(self.height_at(tx+4, tz)-self.height_at(tx-4, tz)) > 10:
                    continue
                break
            else:
                continue
            scale = rng.uniform(.72, 1.55)
            tint = rng.choice((color.rgb32(36, 91, 45), color.rgb32(46, 112, 53),
                               color.rgb32(63, 128, 61), color.rgb32(43, 98, 60),
                               color.rgb32(79, 136, 67)))
            tree_id = f"tree:{cx}:{cz}:{index}"
            state = self.tree_states.get(tree_id, {})
            health_ratio = max(0.0, min(1.0, float(state.get("health", self.TREE_MAX_HEALTH))
                                        / self.TREE_MAX_HEALTH))
            if visual_lod:
                self._append_lod_tree(chunk, tx, tz, self.height_at(tx, tz), scale,
                                      tint, health_ratio)
                tree_vertices, tree_triangles, tree_colors = (
                    chunk.lod_vertices, chunk.lod_triangles, chunk.lod_colors)
            if not visual_lod:
                chunk.tree_specs.append((tree_id, tx, tz, ground, scale, tint))

        grass_vertices, grass_triangles, grass_colors = [], [], []
        # Grass is scattered densely across a chunk, so many blades share the
        # same four terrain-grid vertices. Cache those exact height samples for
        # this build rather than recalculating the terrain trig for each blade.
        terrain_vertex_cache = {}
        grass_count = (90 if visual_lod else
                       {"low": 1000, "medium": 1600, "high": 2200, "ultra": 2800}.get(self.quality, 1000))
        grass_count = int(grass_count * (1.12 if district in ("forest", "rural") else .85))
        for _ in range(grass_count):
            for _attempt in range(6):
                gx = center_x + rng.uniform(-245, 245)
                gz = center_z + rng.uniform(-245, 245)
                if not self.contains_position(gx, gz):
                    continue
                ground = self._terrain_surface_height(gx, gz, terrain_vertex_cache)
                if (ground < 4.0 or abs(
                        self._terrain_surface_height(gx + 3.0, gz, terrain_vertex_cache)
                        - self._terrain_surface_height(gx - 3.0, gz,
                                                       terrain_vertex_cache)) > 8):
                    continue
                if self._footprint_value(gx, gz) > .93:
                    continue
                break
            else:
                continue
            tuft_scale = rng.uniform(.72, 1.35)
            blade_height = rng.uniform(.38, .72) * tuft_scale
            # ``ground`` is the exact interpolation of the visible terrain
            # mesh, already computed for the height and slope checks above.
            render_ground = ground + .06
            lean_x, lean_z = rng.uniform(-.10,.10), rng.uniform(-.10,.10)
            tint = color.rgb32(rng.randint(88,128), rng.randint(140,170), rng.randint(58,78))
            root, tip = shade(tint, .62), shade(tint, 1.18, .7)
            for angle in (rng.random()*pi, rng.random()*pi+pi/2):
                half_width = rng.uniform(.10,.19)*tuft_scale
                dx, dz = cos(angle)*half_width, sin(angle)*half_width
                first = len(grass_vertices)
                grass_vertices.extend(((gx-dx,render_ground,gz-dz),(gx+dx,render_ground,gz+dz),
                    (gx+lean_x+dx*.18,render_ground+blade_height,gz+lean_z+dz*.18),
                    (gx+lean_x-dx*.18,render_ground+blade_height,gz+lean_z-dz*.18)))
                grass_triangles.extend((first,first+1,first+2,first,first+2,first+3))
                grass_colors.extend((root, root, tip, tip))

        chunk.lod_vertices = tree_vertices + grass_vertices
        offset = len(tree_vertices)
        chunk.lod_triangles = tree_triangles + [offset + index for index in grass_triangles]
        chunk.lod_colors = tree_colors + grass_colors
        return chunk

    def _materialize_chunk(self, chunk: IslandChunk) -> IslandChunk:
        """Recreate a cached chunk's scene objects on the main thread."""
        cx, cz = chunk.key
        for tree_id, tx, tz, ground, scale, _tint in chunk.tree_specs:
            state = self.tree_states.get(tree_id, {})
            health = max(0.0, min(self.TREE_MAX_HEALTH,
                                  float(state.get("health", self.TREE_MAX_HEALTH))))
            if health <= 0.0:
                continue
            collider = Entity(parent=self.ground, name="natural-tree-collider",
                model=None, collider="box", position=(tx, ground + 2.35*scale, tz),
                scale=(.7*scale, 4.7*scale, .7*scale))
            collider.chart_x, collider.chart_z = tx, tz
            collider.tree_radius = .35*scale
            collider.chunk_key = chunk.key
            collider.tree_id = tree_id
            collider.tree_health = health
            collider.tree_max_health = self.TREE_MAX_HEALTH
            collider.tree_scale = scale
            collider.tree_tint = _tint
            chunk.tree_colliders.append(collider)
            chunk.entities.append(collider)
        self._rebuild_tree_visuals(chunk)
        if chunk.lod_vertices:
            vegetation = Entity(parent=self.ground,
                name=f"natural-vegetation-{cx}-{cz}",
                model=Mesh(vertices=chunk.lod_vertices, triangles=chunk.lod_triangles,
                           colors=chunk.lod_colors, static=True),
                collider=None, double_sided=True, shader=VEGETATION_SHADER)
            chunk.entities.append(vegetation)
        return chunk

    def _rebuild_tree_visuals(self, chunk: IslandChunk) -> None:
        """Rebuild the chunk's batched tree mesh after damage-stage changes."""
        from ursina import Mesh
        mesh_chunk = IslandChunk(chunk.key, visual_lod=True)
        for tree_id, tx, tz, ground, scale, tint in chunk.tree_specs:
            state = self.tree_states.get(tree_id, {})
            health = max(0.0, min(self.TREE_MAX_HEALTH,
                                  float(state.get("health", self.TREE_MAX_HEALTH))))
            self._append_lod_tree(mesh_chunk, tx, tz, ground, scale, tint,
                                  health / self.TREE_MAX_HEALTH)
        if chunk.tree_visuals is None:
            chunk.tree_visuals = Entity(parent=self.ground,
                name=f"natural-tree-batch-{chunk.key[0]}-{chunk.key[1]}",
                collider=None, double_sided=True, shader=VEGETATION_SHADER)
            chunk.entities.append(chunk.tree_visuals)
        chunk.tree_visuals.model = (Mesh(vertices=mesh_chunk.lod_vertices,
            triangles=mesh_chunk.lod_triangles, colors=mesh_chunk.lod_colors,
            static=True) if mesh_chunk.lod_vertices else None)

    def _npc_capacity(self) -> int:
        return civilian_capacity(self.quality,
            getattr(self.settings, "npc_density", "medium"),
            getattr(self.settings, "civilian_count", 8))

    def _traffic_capacity(self) -> int:
        return traffic_capacity(self.quality,
                                getattr(self.settings, "traffic_density", "medium"))

    def _population_spawn_point(self, chunk: IslandChunk, index: int, rng: Random):
        cx, cz = chunk.key
        center_x, center_z = (cx + .5) * self.CHUNK_SIZE, (cz + .5) * self.CHUNK_SIZE
        side = rng.choice((-1.0, 1.0))
        if index % 3:
            return (center_x + rng.uniform(-185, 185),
                    center_z + side * rng.uniform(246, 251))
        return (center_x + side * rng.uniform(246, 251),
                center_z + rng.uniform(-185, 185))

    def _populate_chunk(self, chunk: IslandChunk) -> None:
        if self.NATURAL_ONLY:
            return
        district = self.district_at((chunk.key[0] + .5) * self.CHUNK_SIZE,
                                    (chunk.key[1] + .5) * self.CHUNK_SIZE)
        target = civilians_per_chunk(district,
            getattr(self.settings, "npc_density", "medium"))
        active_here = sum(c.alive for c in chunk.civilians)
        active_elsewhere = sum(c.alive for c in self.civilians) - active_here
        target = min(target, max(0, self._npc_capacity() - active_elsewhere))
        rng = Random((chunk.key[0] * 8191 + chunk.key[1] * 131 + 0x51A7) & 0xffffffff)
        index = 0
        while sum(c.alive for c in chunk.civilians) < target:
            persistent_id = f"civilian:{chunk.key[0]}:{chunk.key[1]}:{index}"
            index += 1
            if self.civilian_states.get(persistent_id, {}).get("dead", False):
                continue
            position = self._population_spawn_point(chunk, index, rng)
            seed = (chunk.key[0] * 8191 + chunk.key[1] * 131 + index) & 0xffffffff
            if self._civilian_pool:
                civilian = self._civilian_pool.pop()
                civilian.reset(position, persistent_id)
            else:
                civilian = Civilian(self.game, (position[0], 0.0, position[1]),
                                    seed, persistent_id)
            chunk.civilians.append(civilian)
            self.civilians.append(civilian)
            chunk.entities.append(civilian.entity)
            civilian.chunk_key = chunk.key
            self.reindex_civilian(civilian)
        # Pair a minority of people in short, asynchronous conversation stops.
        for first, second in zip(chunk.civilians[::7], chunk.civilians[1::7]):
            if first.alive and second.alive and rng.random() < .45:
                for civilian in (first, second):
                    civilian.brain.state = CivilianState.TALKING
                    civilian.brain.target = None
                    civilian.brain.reaction_time = rng.uniform(2.0, 6.0)

    def _populate_traffic(self, chunk: IslandChunk, rng: Random) -> None:
        if self.NATURAL_ONLY:
            return
        district = self.district_at((chunk.key[0] + .5) * self.CHUNK_SIZE,
                                    (chunk.key[1] + .5) * self.CHUNK_SIZE)
        desired = traffic_per_chunk(district,
            getattr(self.settings, "traffic_density", "medium"))
        existing = sum(1 for vehicle in chunk.objects
                       if getattr(vehicle, "is_traffic", False)
                       and vehicle in self.traffic and not vehicle.health.broken)
        target = min(max(0, desired - existing),
                     max(0, self._traffic_capacity() - len(self.traffic)))
        cx, cz = chunk.key
        center_x, center_z = (cx + .5) * self.CHUNK_SIZE, (cz + .5) * self.CHUNK_SIZE
        for index in range(existing, existing + target):
            persistent_id = f"vehicle:{cx}:{cz}:{index}"
            state = self.object_states.get(persistent_id)
            if state and state.get("destroyed", False):
                self._spawn_remains(chunk, persistent_id, center_x, center_z)
                continue
            lane = -1.0 if index % 2 == 0 else 1.0
            # The south lane travels east; the north lane travels west.
            # Lane offset and route direction are separate properties.
            direction = 1.0 if lane < 0.0 else -1.0
            x = center_x + rng.uniform(-205.0, 205.0)
            z = center_z + lane * 237.0
            point = self.planet.point_from_local(x, z, self.height_at(x, z) + .66)
            if self._traffic_pool:
                vehicle = self._traffic_pool.pop()
                vehicle.reset(self.game, point, direction, (center_x, center_z), persistent_id)
            else:
                vehicle = TrafficVehicle(self.game, point, direction,
                    route_center=(center_x, center_z), persistent_id=persistent_id,
                    style_seed=rng.randrange(1, 2**31))
            vehicle.chart_x, vehicle.chart_z = x, z
            self._configure_object(vehicle, chunk, persistent_id, vehicle.vehicle_type.title())
            self.traffic.append(vehicle)

    def refresh_population(self) -> None:
        """Apply density controls to loaded chunks without rebuilding the island."""
        if self.NATURAL_ONLY:
            return
        for chunk in tuple(self.chunks.values()):
            target = civilians_per_chunk(
                self.district_at((chunk.key[0] + .5) * self.CHUNK_SIZE,
                                 (chunk.key[1] + .5) * self.CHUNK_SIZE),
                getattr(self.settings, "npc_density", "medium"))
            while len(chunk.civilians) > target:
                civilian = chunk.civilians.pop()
                if civilian in self.civilians:
                    self.civilians.remove(civilian)
                if civilian.entity in chunk.entities:
                    chunk.entities.remove(civilian.entity)
                self._retire_civilian(civilian)
            self._populate_chunk(chunk)
            district=self.district_at((chunk.key[0]+.5)*self.CHUNK_SIZE,
                                      (chunk.key[1]+.5)*self.CHUNK_SIZE)
            vehicle_target=traffic_per_chunk(district,
                getattr(self.settings,"traffic_density","medium"))
            loaded=[v for v in chunk.objects if getattr(v,"is_traffic",False)
                    and v in self.traffic and not v.health.broken]
            while len(loaded)>vehicle_target:
                vehicle=loaded.pop()
                if vehicle in chunk.objects: chunk.objects.remove(vehicle)
                if vehicle in chunk.entities: chunk.entities.remove(vehicle)
                self.remove_object(vehicle)
                self._retire_vehicle(vehicle)
            self._populate_traffic(chunk, self.random)

    def _retire_civilian(self, civilian: Civilian) -> None:
        self._remove_civilian_index(civilian)
        civilian.entity.disable()
        if len(self._civilian_pool) < self._npc_capacity():
            self._civilian_pool.append(civilian)
        else:
            self._destroy_entity_tree(civilian.entity)

    def _remove_civilian_index(self, civilian: Civilian) -> None:
        key = getattr(civilian, "_spatial_chunk", None)
        if key is not None:
            bucket = self._civilians_by_chunk.get(key)
            if bucket and civilian in bucket:
                bucket.remove(civilian)
                if not bucket:
                    self._civilians_by_chunk.pop(key, None)
        civilian._spatial_chunk = None

    def reindex_civilian(self, civilian: Civilian) -> None:
        key = (int(civilian.chart_x // self.CHUNK_SIZE),
               int(civilian.chart_z // self.CHUNK_SIZE))
        if getattr(civilian, "_spatial_chunk", None) == key:
            return
        self._remove_civilian_index(civilian)
        civilian._spatial_chunk = key
        self._civilians_by_chunk.setdefault(key, []).append(civilian)

    def nearby_civilians(self, east: float, north: float, chunk_radius: int = 1):
        cx, cz = int(east // self.CHUNK_SIZE), int(north // self.CHUNK_SIZE)
        return tuple(civilian for ix in range(cx - chunk_radius, cx + chunk_radius + 1)
                     for iz in range(cz - chunk_radius, cz + chunk_radius + 1)
                     for civilian in self._civilians_by_chunk.get((ix, iz), ())
                     if civilian.alive)

    def nearby_traffic(self, east: float, north: float, radius: float = 25.0):
        chunk_radius = max(1, int(radius // self.CHUNK_SIZE) + 1)
        cx, cz = int(east // self.CHUNK_SIZE), int(north // self.CHUNK_SIZE)
        return tuple(vehicle for ix in range(cx - chunk_radius, cx + chunk_radius + 1)
                     for iz in range(cz - chunk_radius, cz + chunk_radius + 1)
                     for vehicle in self._objects_by_chunk.get((ix, iz), ())
                     if getattr(vehicle, "is_traffic", False) and vehicle.enabled
                     and not vehicle.health.broken)

    def record_civilian_death(self, civilian: Civilian) -> None:
        self.civilian_states[civilian.persistent_id] = {"dead": True}
        self._damage_state_dirty = True
        self.save_damage_state()

    def _cleanup_dead_civilians(self) -> None:
        for civilian in tuple(self.civilians):
            if civilian.alive or civilian.death_age < civilian.CLEANUP_AFTER:
                continue
            if civilian in self.civilians:
                self.civilians.remove(civilian)
            chunk = self.chunks.get(getattr(civilian, "chunk_key", None))
            if chunk is not None:
                if civilian in chunk.civilians:
                    chunk.civilians.remove(civilian)
                if civilian.entity in chunk.entities:
                    chunk.entities.remove(civilian.entity)
            self._retire_civilian(civilian)


    def _add_tree(self, chunk: IslandChunk, x: float, z: float, rng: Random, index: int) -> None:
        identifier = f"tree:{chunk.key[0]}:{chunk.key[1]}:{index}"
        if self._spawn_remains(chunk, identifier, x, z):
            return
        tint = rng.choice((color.rgb32(37, 96, 48), color.rgb32(48, 115, 58),
                           color.rgb32(70, 128, 62), color.rgb32(34, 83, 55)))
        scale = rng.uniform(.8, 1.45)
        size = (.65 * scale, 7.0 * scale, .65 * scale)
        position = (x, self.height_at(x, z) + size[1] * .5, z)
        if chunk.visual_lod:
            self._append_lod_tree(chunk, x, z, self.height_at(x, z), scale*.90, tint)
            return
        tree = DestructibleEntity(self.game, position, size, tint, 145.0 * scale, "tropical-tree")
        tree.model = None
        tree.color = color.white
        tree.anchored = True
        Entity(parent=tree, model="cube", position=(0, -.08, 0),
               scale=(.42, 1.0, .42), color=color.rgb32(103, 72, 46), collider=None)
        foliage = Entity(parent=tree, model="sphere", position=(0, .30, 0),
                         scale=(2.5, .62, 2.35), color=tint, collider=None)
        Entity(parent=tree, model="sphere", position=(.30, .42, .18),
               scale=(1.6, .48, 1.5), color=tint, collider=None)
        self._configure_object(tree, chunk, identifier, "Tropical Tree")
        state = self.object_states.get(identifier)
        if state and not state.get("destroyed", False):
            tree.health.health = float(state.get("health", tree.health.maximum_health))
            tree._update_damage_appearance()

    def _configure_object(self, obj, chunk: IslandChunk, identifier: str, display_name: str) -> None:
        obj.persistent_id = identifier
        obj.chunk_key = chunk.key
        obj.display_name = display_name
        self._index_object(obj, chunk.key)
        chunk.objects.append(obj)
        chunk.entities.append(obj)
        if isinstance(obj, Building):
            chunk.buildings.append(obj)
            self.buildings.append(obj)
            self._buildings_by_chunk.setdefault(chunk.key, []).append(obj)

    def _spawn_remains(self, chunk: IslandChunk, identifier: str, x: float, z: float) -> bool:
        state = self.object_states.get(identifier)
        if not state or not state.get("destroyed", False):
            return False
        count = 3 + int(identifier[-1], 36) % 3
        if chunk.visual_lod:
            for index in range(count):
                self._append_lod_box(
                    chunk, (x + (index - count / 2) * .8,
                            self.height_at(x, z) + .18 + index * .08,
                            z + ((index % 2) * .7)),
                    (1.2, .28 + (index % 2) * .24, .96), color.rgb32(104, 101, 94))
            return True
        for index in range(count):
            rubble = Entity(name="persistent-collapsed-rubble", model="cube",
                position=(x + (index - count / 2) * .8, self.height_at(x, z) + .18 + index * .08,
                          z + ((index % 2) * .7)), scale=(1.5, .35 + (index % 2) * .3, 1.2),
                color=color.rgb32(104, 101, 94), collider=None)
            chunk.entities.append(rubble)
        return True

    def _unload_chunk(self, key: tuple[int, int]) -> None:
        chunk = self.chunks.pop(key)
        if self.NATURAL_ONLY and chunk.quality == self.quality:
            cached = IslandChunk(
                key=chunk.key, visual_lod=chunk.visual_lod,
                lod_vertices=chunk.lod_vertices,
                lod_triangles=chunk.lod_triangles,
                lod_colors=chunk.lod_colors,
                tree_specs=chunk.tree_specs, quality=chunk.quality)
            self._chunk_data_cache[key] = cached
            self._chunk_data_cache.move_to_end(key)
            while len(self._chunk_data_cache) > self._chunk_cache_limit:
                self._chunk_data_cache.popitem(last=False)
        for obj in tuple(chunk.objects):
            self.record_damage(obj, destroyed=obj.health.broken)
            self.remove_object(obj)
            if getattr(obj, "is_traffic", False) and not obj.health.broken:
                if obj in chunk.entities:
                    chunk.entities.remove(obj)
                self._retire_vehicle(obj)
            if obj in self.buildings:
                self.buildings.remove(obj)
        for civilian in tuple(chunk.civilians):
            if civilian in self.civilians:
                self.civilians.remove(civilian)
            if civilian.entity in chunk.entities:
                chunk.entities.remove(civilian.entity)
            self._retire_civilian(civilian)
        for entity in chunk.entities:
            self._destroy_entity_tree(entity)

    @staticmethod
    def _destroy_entity_tree(entity) -> None:
        """Remove Panda nodes and their wrappers from Ursina's live entity list."""
        if entity is None or not hasattr(entity, "removeNode"):
            return
        try:
            if entity.is_empty():
                return
            for child in tuple(getattr(entity, "children", ())):
                IslandWorld._destroy_entity_tree(child)
            for child in tuple(getattr(entity, "loose_children", ())):
                IslandWorld._destroy_entity_tree(child)
            destroy(entity, force_destroy=True)
        except (AttributeError, TypeError, RuntimeError):
            # A destruction effect may already have removed the Panda node.
            try:
                entity.removeNode()
            except Exception:
                pass

    def record_damage(self, obj, *, destroyed: bool = False) -> None:
        identifier = getattr(obj, "persistent_id", None)
        if not identifier:
            return
        self.object_states[identifier] = {
            "health": float(obj.health.health or 0.0),
            "destroyed": bool(destroyed or obj.health.broken),
        }
        self._damage_state_dirty = True
        if destroyed or obj.health.broken:
            self._distant_lod_dirty = True
            chunk_key = getattr(obj, "chunk_key", None)
            if chunk_key is not None:
                sx = min(3, max(0, (int(chunk_key[0]) + 10) // 5))
                sz = min(3, max(0, (int(chunk_key[1]) + 10) // 5))
                self._distant_lod_dirty_sectors.add((sx, sz))
        if destroyed or obj.health.broken:
            self.save_damage_state()

    def _retire_vehicle(self, vehicle: TrafficVehicle) -> None:
        if vehicle in self.traffic:
            self.traffic.remove(vehicle)
        if vehicle.health.broken:
            return
        vehicle.disable()
        if len(self._traffic_pool) < self._traffic_capacity():
            self._traffic_pool.append(vehicle)
        else:
            self._destroy_entity_tree(vehicle)

    def _load_damage_state(self) -> None:
        try:
            raw = json.loads(self.damage_save_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        for identifier, state in raw.items():
            if not isinstance(identifier, str) or not isinstance(state, dict):
                continue
            if identifier == self.TERRAIN_SAVE_KEY:
                for terrain_id, terrain_state in state.items():
                    if not isinstance(terrain_id, str) or not isinstance(terrain_state, dict):
                        continue
                    try:
                        x, z = float(terrain_state["x"]), float(terrain_state["z"])
                        radius = max(1.5, min(80.0, float(terrain_state["radius"])))
                        depth = max(.05, min(7.0, float(terrain_state["depth"])))
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
                    if (not self.contains_position(x, z) or not all(
                            value == value and abs(value) != float("inf")
                            for value in (x, z, radius, depth))):
                        continue
                    crater = {"x": x, "z": z, "radius": radius, "depth": depth,
                              "surface": str(terrain_state.get("surface", "ground"))[:20]}
                    self.terrain_impacts[terrain_id] = crater
                    self._terrain_impacts_by_chunk.setdefault(
                        (int(x // self.CHUNK_SIZE), int(z // self.CHUNK_SIZE)), []).append(crater)
                self._sync_native_craters()
                continue
            if identifier == self.CIVILIAN_SAVE_KEY:
                for civilian_id, civilian_state in state.items():
                    if (isinstance(civilian_id, str) and isinstance(civilian_state, dict)
                            and civilian_state.get("dead") is True):
                        self.civilian_states[civilian_id] = {"dead": True}
                continue
            if identifier == self.TREE_SAVE_KEY:
                for tree_id, tree_state in state.items():
                    if not isinstance(tree_id, str) or not tree_id.startswith("tree:") \
                            or not isinstance(tree_state, dict):
                        continue
                    try:
                        health = float(tree_state.get("health", self.TREE_MAX_HEALTH))
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if health != health or abs(health) == float("inf"):
                        continue
                    self.tree_states[tree_id] = {
                        "health": max(0.0, min(self.TREE_MAX_HEALTH, health)),
                        "destroyed": bool(tree_state.get("destroyed", False)) or health <= 0.0,
                    }
                    if self.tree_states[tree_id]["destroyed"]:
                        self.tree_states[tree_id]["health"] = 0.0
                continue
            try:
                health = float(state.get("health", 0.0))
            except (TypeError, ValueError, OverflowError):
                continue
            if health != health or abs(health) == float("inf"):
                continue
            self.object_states[identifier] = {
                "health": max(0.0, health),
                "destroyed": bool(state.get("destroyed", False)) or health <= 0.0,
            }

    def save_damage_state(self) -> None:
        if not self._damage_state_dirty:
            return
        temporary = self.damage_save_path.with_suffix(".tmp")
        try:
            self.damage_save_path.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(self.object_states)
            if self.terrain_impacts:
                payload[self.TERRAIN_SAVE_KEY] = self.terrain_impacts
            civilian_states = getattr(self, "civilian_states", {})
            if civilian_states:
                payload[self.CIVILIAN_SAVE_KEY] = civilian_states
            tree_states = getattr(self, "tree_states", {})
            if tree_states:
                payload[self.TREE_SAVE_KEY] = tree_states
            if self.async_chunks:
                self._save_in_background(payload, temporary)
                return
            temporary.write_text(json.dumps(payload, separators=(",", ":")),
                                 encoding="utf-8")
            temporary.replace(self.damage_save_path)
            self._damage_state_dirty = False
            self._damage_save_timer = 0.0
        except OSError:
            # An unavailable save directory must not interrupt gameplay.
            return

    def _save_in_background(self, payload: dict, temporary) -> None:
        """Saving a badly damaged island took 45 ms. The player should never feel that, so a thread does it."""
        if self._save_thread is not None and self._save_thread.is_alive():
            return  # still dirty, so it runs again shortly
        self._damage_state_dirty = False
        self._damage_save_timer = 0.0

        def write() -> None:
            try:
                temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
                temporary.replace(self.damage_save_path)
            except (OSError, RuntimeError):  # the save directory is gone, or a table changed mid-write: try again
                self._damage_state_dirty = True

        self._save_thread = Thread(target=write, name="damage-save", daemon=False)
        self._save_thread.start()

    def register_object(self, obj) -> None:
        self.objects.append(obj)
        self._index_object(obj, (int(obj.x // self.CHUNK_SIZE),
                                 int(obj.z // self.CHUNK_SIZE)))

    def remove_object(self, obj) -> None:
        if obj in self.objects:
            self.objects.remove(obj)
        if obj in self.traffic:
            self.traffic.remove(obj)
        key = getattr(obj, "_spatial_chunk", None)
        if key is not None:
            bucket = self._objects_by_chunk.get(key)
            if bucket and obj in bucket:
                bucket.remove(obj)
                if not bucket:
                    self._objects_by_chunk.pop(key, None)
        if isinstance(obj, Building):
            if obj in self.buildings:
                self.buildings.remove(obj)
            building_key = getattr(obj, "chunk_key", None)
            bucket = self._buildings_by_chunk.get(building_key)
            if bucket and obj in bucket:
                bucket.remove(obj)
                if not bucket:
                    self._buildings_by_chunk.pop(building_key, None)

    def _index_object(self, obj, key: tuple[int, int]) -> None:
        previous = getattr(obj, "_spatial_chunk", None)
        if previous == key:
            return
        if previous is not None:
            old_bucket = self._objects_by_chunk.get(previous)
            if old_bucket and obj in old_bucket:
                old_bucket.remove(obj)
                if not old_bucket:
                    self._objects_by_chunk.pop(previous, None)
        obj._spatial_chunk = key
        self._objects_by_chunk.setdefault(key, []).append(obj)

    def _reindex_object(self, obj) -> None:
        self._index_object(obj, (int(obj.x // self.CHUNK_SIZE),
                                 int(obj.z // self.CHUNK_SIZE)))

    def _nearby_objects(self, x: float, z: float, chunk_radius: int = 1):
        cx, cz = int(float(x) // self.CHUNK_SIZE), int(float(z) // self.CHUNK_SIZE)
        candidates = []
        for ix in range(cx - chunk_radius, cx + chunk_radius + 1):
            for iz in range(cz - chunk_radius, cz + chunk_radius + 1):
                candidates.extend(self._objects_by_chunk.get((ix, iz), ()))
        return tuple(candidates)

    def spawn_debris(self, position, velocity, tint, size: float,
                     lifetime: float) -> DebrisPiece:
        velocity = velocity * self.scales.debris_speed
        lifetime = lifetime * self.scales.effect_duration
        if self._debris_pool:
            item = self._debris_pool.pop()
            item.reset(self.game, position, velocity, tint, size, lifetime)
        else:
            item = DebrisPiece(self.game, position, velocity, tint, size, lifetime)
        self.debris.append(item)
        return item

    def damage_tree(self, tree, amount: float, impulse=None, *,
                    impact_position=None, impact_speed: float = 0.0,
                    chain_depth: int = 0) -> bool:
        """Damage a streamed tree; its health and final stump persist by ID."""
        tree_id = getattr(tree, "tree_id", None)
        if not tree_id or not getattr(tree, "enabled", True):
            return False
        previous = max(0.0, min(self.TREE_MAX_HEALTH,
            float(getattr(tree, "tree_health", self.TREE_MAX_HEALTH))))
        damage = max(0.0, float(amount)) * self.scales.tree
        if damage <= 0.0 or previous <= 0.0:
            return False
        health = max(0.0, previous - damage)
        tree.tree_health = health
        state = {"health": health, "destroyed": health <= 0.0}
        self.tree_states[tree_id] = state
        self._damage_state_dirty = True
        chunk = self.chunks.get(getattr(tree, "chunk_key", None))

        point = impact_position or SimVec3(tree.x, tree.y, tree.z)
        effect_clock = getattr(tree, "_next_tree_burn_effect", 0.0)
        if self.game.elapsed >= effect_clock and health > 0.0:
            tree._next_tree_burn_effect = self.game.elapsed + .28
            TimedEffect(self, point, color.rgb32(255, 105, 30), "fire", .42)
        previous_stage = min(3, int(previous / self.TREE_MAX_HEALTH * 4))
        current_stage = min(3, int(health / self.TREE_MAX_HEALTH * 4))
        if chunk is not None and current_stage != previous_stage:
            self._rebuild_tree_visuals(chunk)
            self._chunk_data_cache.pop(chunk.key, None)

        if health > 0.0:
            return True

        scale = float(getattr(tree, "tree_scale", 1.0))
        tint = getattr(tree, "tree_tint", color.rgb32(47, 104, 52))
        ground = float(tree.y) - 2.35 * scale
        fall_position = (float(tree.x), ground, float(tree.z))
        chunk_key = getattr(tree, "chunk_key", None)
        if chunk is not None:
            if tree in chunk.tree_colliders:
                chunk.tree_colliders.remove(tree)
            self._rebuild_tree_visuals(chunk)
        self._chunk_data_cache.pop(chunk_key, None)
        try:
            destroy(tree, force_destroy=True)
        except (AttributeError, TypeError, RuntimeError):
            tree.disable()

        direction = impulse if impulse is not None else SimVec3(1.0, 0.0, 0.0)
        if direction.length() < .05:
            direction = SimVec3(1.0, 0.0, 0.0)
        falling = FallingTree(self, tree_id, fall_position, scale, tint,
                              direction, chain_depth=chain_depth)
        self.effects.append(falling)
        self._acquire_explosion(point, 2.0 * scale,
                                min(2.0, .65 + max(0.0, damage) / self.TREE_MAX_HEALTH * .25))
        self._distant_lod_dirty_sectors.add((
            min(3, max(0, (int(chunk_key[0]) + 10) // 5)),
            min(3, max(0, (int(chunk_key[1]) + 10) // 5))))
        self._damage_state_dirty = True
        self.save_damage_state()
        return True

    def restore_tree(self, tree) -> None:
        """Molecular reconstruction: a damaged tree back to full health."""
        tree.tree_health = self.TREE_MAX_HEALTH
        self.tree_states.pop(getattr(tree, "tree_id", None), None)
        self._damage_state_dirty = True
        chunk = self.chunks.get(getattr(tree, "chunk_key", None))
        if chunk is not None:
            self._rebuild_tree_visuals(chunk)
            self._chunk_data_cache.pop(chunk.key, None)

    def add_debris(self, item) -> None:
        if item not in self.debris:
            self.debris.append(item)

    def remove_debris(self, item) -> None:
        if item in self.debris:
            self.debris.remove(item)
            self.debris_budget.release(1)

    def recycle_debris(self, item) -> None:
        self.remove_debris(item)
        item.visible = False
        item.disable()
        item.collider = None
        if len(self._debris_pool) < self.MAX_POOLED_DEBRIS:
            self._debris_pool.append(item)
        else:
            destroy(item, force_destroy=True)

    def _acquire_explosion(self, position, radius: float, intensity: float) -> None:
        if self._explosion_pool:
            burst = self._explosion_pool.pop()
        elif len(self._active_explosions) < self.MAX_ACTIVE_EXPLOSIONS:
            burst = DestructionBurst(self)
        else:
            # Recycle the oldest visual bundle for the latest high-salience hit.
            # The destruction, debris, and damage event are still processed.
            burst = self._active_explosions.pop(0)
            if burst in self.effects:
                self.effects.remove(burst)
        burst.start(position, radius, intensity * self.scales.visual)
        self.effects.append(burst)
        self._active_explosions.append(burst)

    def recycle_explosion(self, burst) -> None:
        if burst in self.effects:
            self.effects.remove(burst)
        if burst in self._active_explosions:
            self._active_explosions.remove(burst)
        for entity in burst.entities:
            entity.visible = False
        if burst not in self._explosion_pool:
            self._explosion_pool.append(burst)

    def on_object_destroyed(self, obj, *, impact_position=None,
                            impact_speed: float = 0.0,
                            damage_power: float = 0.0) -> None:
        if getattr(obj, "_chain_event_queued", False):
            return
        obj._chain_event_queued = True
        point = impact_position or SimVec3(obj.x, obj.y, obj.z)
        depth = self._current_chain_depth + 1 if self._processing_chain else 0
        speed_factor = max(0.0, float(impact_speed)) / 80.0
        power_factor = sqrt(max(0.0, float(damage_power)) / 300.0)
        intensity = max(.7, min(4.0, 1.0 + speed_factor + power_factor * .55))
        radius = max(7.0, min(36.0, 7.0 + intensity * 6.0))
        if self.scales.chain <= 0.0:
            return
        radius = radius * self.scales.chain
        self._chain_queue.append((point, radius, intensity, obj, depth))
        if not self._processing_chain:
            self._drain_chain_queue()

    def _drain_chain_queue(self) -> None:
        self._processing_chain = True
        processed = 0
        try:
            while self._chain_queue and processed < self.MAX_CHAIN_EVENTS_PER_TICK:
                point, radius, intensity, source, depth = self._chain_queue.pop(0)
                self._current_chain_depth = depth
                processed += 1
                self._acquire_explosion(point, radius, intensity)
                self._play_explosion_sound(intensity)
                self.game.camera_impulse = max(
                    self.game.camera_impulse, min(3.0, .45 + intensity * .48))
                if depth < self.MAX_CHAIN_DEPTH:
                    self.damage_nearby(point, 120.0 * intensity,
                        radius=radius, impulse=18.0 * intensity, ignore=source,
                        chain_depth=depth + 1)
        finally:
            self._current_chain_depth = 0
            self._processing_chain = False

    def _play_explosion_sound(self, intensity: float) -> None:
        audio_path = Path(__file__).resolve().parents[1] / "assets" / "audio" / "impact.wav"
        if not audio_path.exists():
            return
        try:
            from ursina import Audio
            if not self._explosion_audio:
                self._explosion_audio = [Audio("assets/audio/impact.wav",
                                               autoplay=False, loop=False,
                                               volume=.7, auto_destroy=False)
                                         for _ in range(3)]
            sound = self._explosion_audio[self._explosion_audio_cursor % len(self._explosion_audio)]
            self._explosion_audio_cursor += 1
            sound.stop()
            sound.volume = min(1.0, .45 + float(intensity) * .12) * self.scales.explosion_sound
            sound.time = 0
            sound.play()
        except (ImportError, AttributeError, RuntimeError, TypeError):
            return

    def play_power_sound(self, volume: float) -> None:
        """Play the shared impact sample for a power or strike; zero stays silent."""
        if volume <= 0.0:
            return
        scale = self.scales.explosion_sound
        self.scales.explosion_sound = 1.0
        try:
            self._play_explosion_sound(0.0)
            if self._explosion_audio:
                index = (self._explosion_audio_cursor - 1) % len(self._explosion_audio)
                self._explosion_audio[index].volume = min(1.0, float(volume))
        finally:
            self.scales.explosion_sound = scale

    def damage_debris_impact(self, debris) -> bool:
        speed = debris.velocity.length()
        if speed <= 14.0:
            return False
        candidates = self._nearby_objects(debris.x, debris.z, 1)
        nearest = None
        nearest_distance_sq = float("inf")
        for obj in candidates:
            if obj is debris or not obj.enabled or obj.held or obj.health.broken:
                continue
            dx, dy, dz = obj.x - debris.x, obj.y - debris.y, obj.z - debris.z
            distance_sq = dx * dx + dy * dy + dz * dz
            reach = max(1.0, max(abs(obj.scale_x), abs(obj.scale_y), abs(obj.scale_z)) * .55)
            if distance_sq <= reach * reach and distance_sq < nearest_distance_sq:
                nearest, nearest_distance_sq = obj, distance_sq
        if nearest is None:
            return False
        direction = debris.velocity.normalized()
        damage = min(180.0, max(8.0, (speed - 14.0) * 1.2))
        nearest.take_damage(damage, direction * min(40.0, speed * .6),
                            impact_position=SimVec3(debris.x, debris.y, debris.z),
                            impact_speed=speed)
        return True

    def add_effect(self, effect) -> None:
        self.effects.append(effect)

    def _blast_chunk_radius(self, radius: float) -> int:
        """Chunks a blast must search. Past the island's width there is nothing more to
        find, so a huge setting can't make the search walk millions of empty chunks."""
        island_span = int(20000.0 // self.CHUNK_SIZE) + 1
        return max(1, min(island_span, int(min(radius, 1e9) // self.CHUNK_SIZE) + 1))

    def damage_nearby(self, origin, amount: float, *, radius: float = 5.0,
                      impulse: float = 8.0, ignore=None, chain_depth: int = 0) -> None:
        radius = max(0.0, float(radius))
        chunk_radius = self._blast_chunk_radius(radius)
        # Copies: whatever this destroys leaves these lists, and must not make the search skip its neighbour.
        for obj in tuple(self._nearby_objects(origin.x, origin.z, chunk_radius)):
            if obj is ignore or not obj.enabled:
                continue
            dx, dy, dz = obj.x - origin.x, obj.y - origin.y, obj.z - origin.z
            distance = sqrt(dx * dx + dy * dy + dz * dz)
            if distance >= radius or radius <= 1e-6:
                continue
            falloff = 1.0 - distance / radius
            direction = SimVec3(dx, max(.2, dy), dz).normalized()
            structure_scale = self.scales.building if isinstance(obj, Building) else 1.0
            obj.take_damage(amount * falloff * structure_scale, direction * impulse * falloff,
                            impact_position=origin,
                            impact_speed=impulse * falloff)
        if chain_depth <= 1:
            for tree in tuple(self._nearby_tree_colliders(origin.x, origin.z, chunk_radius)):
                if tree is ignore or not getattr(tree, "enabled", True):
                    continue
                dx, dy, dz = tree.x - origin.x, tree.y - origin.y, tree.z - origin.z
                distance = sqrt(dx * dx + dy * dy + dz * dz)
                if distance >= radius or radius <= 1e-6:
                    continue
                falloff = 1.0 - distance / radius
                direction = SimVec3(dx, max(.2, dy), dz).normalized()
                self.damage_tree(tree, amount * falloff,
                    direction * impulse * falloff, impact_position=origin,
                    impact_speed=impulse * falloff, chain_depth=chain_depth)
        self.damage_civilians_nearby(origin, amount, radius=radius, impulse=impulse)
        combat_hook = getattr(self.game, "on_area_damage", None)
        if callable(combat_hook):
            combat_hook(origin, amount, radius, impulse)

    def damage_civilians_nearby(self, origin, amount: float, *, radius: float,
                                impulse: float = 0.0) -> int:
        radius = max(0.0, float(radius))
        if radius <= 1e-6 or amount <= 0.0:
            return 0
        affected = 0
        for civilian in self.nearby_civilians(origin.x, origin.z,
                                              self._blast_chunk_radius(radius)):
            dx, dy, dz = civilian.entity.x - origin.x, civilian.entity.y - origin.y, civilian.entity.z - origin.z
            distance = sqrt(dx*dx + dy*dy + dz*dz)
            if distance >= radius:
                continue
            falloff = 1.0 - distance / radius
            direction = SimVec3(dx, max(.15, dy), dz).normalized()
            velocity_damage = max(0.0, float(impulse))
            fatal_scale = 1.0 + min(8.0, velocity_damage / 35.0)
            civilian.take_damage(float(amount) * falloff * fatal_scale,
                                 direction * velocity_damage * falloff,
                                 impact_speed=velocity_damage * falloff,
                                 impact_position=origin)
            affected += 1
        return affected

    def notify_danger(self, origin: SimVec3) -> None:
        for civilian in self.nearby_civilians(origin.x, origin.z, 1):
            civilian.react_to_danger(origin)

    def nearby_buildings(self, east: float, north: float):
        cx, cz = int(east // self.CHUNK_SIZE), int(north // self.CHUNK_SIZE)
        candidates = (building for ix in range(cx - 1, cx + 2)
                      for iz in range(cz - 1, cz + 2)
                      for building in self._buildings_by_chunk.get((ix, iz), ()))
        return tuple(building for building in candidates
                     if abs(building.chart_x - east) < abs(building.scale_x) * .5 + 30
                     and abs(building.chart_z - north) < abs(building.scale_z) * .5 + 30)

    def _nearby_tree_colliders(self, east: float, north: float, radius: int):
        cx, cz = int(east // self.CHUNK_SIZE), int(north // self.CHUNK_SIZE)
        return (tree for ix in range(cx-radius, cx+radius+1)
                for iz in range(cz-radius, cz+radius+1)
                if (ix,iz) in self.chunks
                for tree in self.chunks[(ix,iz)].tree_colliders)

    def resolve_sentry(self, sentry, *, previous_position=None) -> None:
        """Sweep the character through nearby destructibles using actual impact velocity."""
        end = SimVec3(sentry.x, sentry.y, sentry.z)
        start = (SimVec3(previous_position.x, previous_position.y, previous_position.z)
                 if previous_position is not None else end)
        travel = end - start
        chunk_radius = min(3, max(1, int(travel.length() / self.CHUNK_SIZE) + 1))
        velocity = sentry.flight.velocity if sentry.flight.is_flying else sentry.ground.velocity
        if velocity.length() > 8.0:
            hits = 0
            for civilian in self.nearby_civilians((start.x + end.x) * .5,
                    (start.z + end.z) * .5, chunk_radius):
                if self.game.elapsed < getattr(civilian, "_next_sentry_impact", 0.0):
                    continue
                center = civilian.entity.world_position
                hit = sweep_point_aabb((start.x,start.y,start.z),(end.x,end.y,end.z),
                    (center.x-.42,center.y-.88,center.z-.42),
                    (center.x+.42,center.y+.88,center.z+.42))
                if hit is None:
                    continue
                _t, normal_tuple = hit
                normal = SimVec3(*normal_tuple)
                impact_speed = abs(velocity.x*normal.x + velocity.y*normal.y + velocity.z*normal.z)
                if impact_speed <= 8.0:
                    continue
                civilian._next_sentry_impact = self.game.elapsed + .35
                damage = superhuman_impact_damage(impact_speed) * 1.6
                civilian.take_damage(damage,
                    velocity.normalized() * min(95.0, impact_speed * .9),
                    impact_speed=impact_speed,
                    impact_position=SimVec3(center.x,center.y,center.z))
                hits += 1
                if hits >= 4:
                    break
        contact = None
        for obj in self._nearby_objects((start.x + end.x) * .5,
                                        (start.z + end.z) * .5, chunk_radius):
            if not obj.enabled or obj.held or obj.health.broken:
                continue
            half_x = abs(obj.scale_x) * .5 + .48
            half_y = abs(obj.scale_y) * .5 + 1.05
            half_z = abs(obj.scale_z) * .5 + .48
            bounds_min = (obj.x - half_x, obj.y - half_y, obj.z - half_z)
            bounds_max = (obj.x + half_x, obj.y + half_y, obj.z + half_z)
            hit = sweep_point_aabb((start.x, start.y, start.z),
                                   (end.x, end.y, end.z), bounds_min, bounds_max)
            if hit is None:
                continue
            t, normal_tuple = hit
            if contact is None or t < contact[0]:
                contact = (t, normal_tuple, obj)

        if contact is not None:
            t, normal_tuple, obj = contact
            normal = SimVec3(*normal_tuple)
            hit_center = start + travel * t
            impact_point = SimVec3(hit_center.x - normal.x * .46,
                                   hit_center.y + .65 - normal.y * .46,
                                   hit_center.z - normal.z * .46)
            normal_speed = abs(velocity.x * normal.x + velocity.y * normal.y
                               + velocity.z * normal.z)
            if normal_speed > 10.0 and self.game.elapsed >= float(
                    getattr(obj, "_next_sentry_impact", 0.0)):
                obj._next_sentry_impact = self.game.elapsed + .28
                damage = superhuman_impact_damage(normal_speed)
                impulse = velocity.normalized() * min(180.0, max(8.0, normal_speed * .8))
                obj.take_damage(damage, impulse, impact_position=impact_point,
                                impact_speed=normal_speed)
                if normal_speed >= 22.0 and not obj.health.broken:
                    self._acquire_explosion(impact_point,
                        min(12.0, 2.0 + normal_speed * .035),
                        min(1.4, .4 + normal_speed / 100.0))
                    self.game.camera_impulse = max(self.game.camera_impulse,
                                                   min(1.2, normal_speed / 90.0))
                if normal_speed >= 105.0 and isinstance(obj, Building):
                    self.deform_terrain(impact_point,
                        radius=min(30.0, 7.0 + normal_speed * .07),
                        depth=min(4.5, 1.0 + normal_speed * .018),
                        surface="high_speed_impact")
            if not obj.health.broken:
                # Correct only the swept collision and remove inward velocity;
                # tangential momentum remains available for follow-through.
                sentry.position = (hit_center.x + normal.x * .025,
                                   hit_center.y + normal.y * .025,
                                   hit_center.z + normal.z * .025)
                into_wall = velocity.x * normal.x + velocity.y * normal.y + velocity.z * normal.z
                if into_wall < 0.0:
                    velocity = velocity - normal * into_wall
                    if sentry.flight.is_flying:
                        sentry.flight.velocity = velocity
                    else:
                        sentry.ground.velocity = velocity

        tree_contact = None
        for tree in self._nearby_tree_colliders((start.x+end.x)*.5,
                                                 (start.z+end.z)*.5, chunk_radius):
            radius = tree.tree_radius + .48
            half_height = tree.scale_y * .5 + 1.05
            hit = sweep_point_aabb((start.x,start.y,start.z),(end.x,end.y,end.z),
                (tree.x-radius,tree.y-half_height,tree.z-radius),
                (tree.x+radius,tree.y+half_height,tree.z+radius))
            if hit is not None and (tree_contact is None or hit[0] < tree_contact[0]):
                tree_contact = (hit[0],hit[1])
        if tree_contact is not None:
            t, normal_tuple = tree_contact
            normal = SimVec3(*normal_tuple)
            hit_center = start + travel*t
            sentry.position=(hit_center.x+normal.x*.025,hit_center.y+normal.y*.025,
                             hit_center.z+normal.z*.025)
            into_tree=velocity.x*normal.x+velocity.y*normal.y+velocity.z*normal.z
            if into_tree<0:
                velocity=velocity-normal*into_tree
                if sentry.flight.is_flying:
                    sentry.flight.velocity=velocity
                else:
                    sentry.ground.velocity=velocity

        x, z = self.planet.clamp_to_land(sentry.x, sentry.z)
        sentry.x, sentry.z = x, z
        terrain = self.height_at(x, z)
        keeps_height = getattr(sentry, "keeps_own_height", False)
        if keeps_height:
            sentry.y = max(float(sentry.y), terrain + .25)
        elif not sentry.flight.is_flying:
            sentry.y = terrain + .25 + sentry.jump_height
            if sentry.flight.velocity.y < 0:
                sentry.flight.velocity.y = 0.0
        elif sentry.y < terrain + .25:
            sentry.y = terrain + .25
            if sentry.flight.velocity.y < 0:
                sentry.flight.velocity.y = 0.0
        if sentry.y > IslandFrame.MAX_FLIGHT_ALTITUDE and not keeps_height:
            sentry.y = IslandFrame.MAX_FLIGHT_ALTITUDE
            if sentry.flight.velocity.y > 0:
                sentry.flight.velocity.y = 0.0

    def resolve_object_collision(self, moving, *, old_position=None, impact_speed=None) -> None:
        if not moving.enabled:
            return
        speed = impact_speed if impact_speed is not None else moving.velocity.length()
        damage = impact_damage(speed)
        if damage <= 0.0:
            return
        self._reindex_object(moving)
        if getattr(moving, "dynamic", False) and speed > 16.0:
            start = (SimVec3(old_position.x, old_position.y, old_position.z)
                     if old_position is not None else SimVec3(moving.x,moving.y,moving.z))
            end = SimVec3(moving.x,moving.y,moving.z)
            for civilian in self.nearby_civilians((start.x+end.x)*.5,
                    (start.z+end.z)*.5,1):
                hit = sweep_point_aabb((start.x,start.y,start.z),(end.x,end.y,end.z),
                    (civilian.entity.x-.42,civilian.entity.y-.88,civilian.entity.z-.42),
                    (civilian.entity.x+.42,civilian.entity.y+.88,civilian.entity.z+.42))
                if hit is None or self.game.elapsed < getattr(civilian,"_next_object_impact",0.0):
                    continue
                civilian._next_object_impact=self.game.elapsed+.35
                delta=end-start
                civilian.take_damage(damage*1.6,delta.normalized()*min(80.0,speed*.75),
                                     impact_speed=speed,impact_position=end)
        for other in self._nearby_objects(moving.x, moving.z, 1):
            if other is moving or not other.enabled or other.held or other.health.broken:
                continue
            overlaps = ((abs(moving.scale_x) + abs(other.scale_x)) * .5 - abs(moving.x - other.x),
                        (abs(moving.scale_y) + abs(other.scale_y)) * .5 - abs(moving.y - other.y),
                        (abs(moving.scale_z) + abs(other.scale_z)) * .5 - abs(moving.z - other.z))
            if min(overlaps) <= 0.0:
                continue
            direction = SimVec3(moving.x - other.x, moving.y - other.y,
                                moving.z - other.z).normalized()
            other.take_damage(damage, direction * min(45.0, speed * .65))
            if moving.dynamic and moving.health.health > 0:
                moving.take_damage(damage * .12)
                moving.velocity = moving.velocity + direction * speed * .25
            elif old_position is not None and hasattr(moving, "lane_direction"):
                moving.position = old_position
                moving.lane_direction *= -1.0
            break

    def sonic_boom(self, origin: SimVec3, direction: SimVec3) -> None:
        TimedEffect(self, (origin.x, origin.y, origin.z), color.azure, "shockwave", .65)
        self.damage_nearby(origin, 32.0, radius=28.0, impulse=72.0)
        self.notify_danger(origin)

    def ground_impact(self, origin, damage: float, radius: float, impulse: float) -> None:
        scales = self.scales
        damage = float(damage) * scales.damage
        radius = float(radius) * scales.radius
        impulse = float(impulse) * scales.force
        crater_depth = min(6.0, .6 + damage / 190.0) * scales.terrain
        if scales.crater > 0.0 and scales.terrain > 0.0:
            self.deform_terrain(origin, radius=min(60.0, max(5.0, radius * .55)) * scales.crater,
                                depth=crater_depth, surface="impact")
        self.damage_nearby(origin, damage, radius=radius, impulse=impulse)
        intensity = min(4.0, max(.8, float(damage) / 250.0))
        self._acquire_explosion(origin, max(8.0, radius), intensity)
        self._play_explosion_sound(intensity)
        self.game.camera_impulse = max(self.game.camera_impulse,
                                       min(3.0, .55 + intensity * .48) * scales.camera_shake)

    def terrain_impact(self, origin, *, radius: float, depth: float,
                       intensity: float = 1.0, surface: str = "ground") -> None:
        radius = radius * self.scales.crater
        depth = depth * self.scales.terrain
        if radius <= 0.0 or depth <= 0.0:
            return
        crater = self.deform_terrain(origin, radius=radius, depth=depth, surface=surface)
        if crater is None:
            return
        point = SimVec3(origin.x, self.height_at(origin.x, origin.z) + .04, origin.z)
        east, up, north = self.planet.tangent_frame(point)
        count = self.debris_budget.reserve(min(8, max(2, int(2 + intensity * 2))))
        rng = Random(int(abs(point.x * 19 + point.z * 37 + self.game.elapsed * 100)))
        for _ in range(count):
            angle, speed = rng.random() * 2 * pi, rng.uniform(4.0, 12.0) * intensity
            velocity = (east * (cos(angle) * speed) + north * (sin(angle) * speed)
                        + up * rng.uniform(4.0, 9.0) * intensity)
            self.spawn_debris(point, velocity, color.rgb32(94, 75, 52),
                              rng.uniform(.12, .32) * intensity,
                              min(4.0, self.settings.debris_lifetime))
        self._acquire_explosion(point, radius * 1.8, min(2.2, max(.5, intensity)))
        if surface != "heat":
            self._play_explosion_sound(intensity)


    def update(self, dt: float) -> None:
        if not self._initialized:
            return
        # Height queries use crater data immediately for exact collision. Rebuild
        # at most one visible terrain sector per frame to avoid impact-sized stalls.
        self._terrain_rebuild_wait -= max(0.0, dt)
        if self._pending_terrain_sectors and self._terrain_rebuild_wait <= 0.0:
            self._terrain_rebuild_wait = self.TERRAIN_REBUILD_INTERVAL
            sector = min(self._pending_terrain_sectors)
            entity = self._terrain_sector_entities.get(sector)
            if entity is not None:
                entity.model = self._build_terrain_sector(*sector)
            self._pending_terrain_sectors.discard(sector)
        sentry = getattr(self.game, "sentry", None)
        if sentry is not None:
            self._stream_chunks(sentry.x, sentry.z)
        if self._chain_queue and not self._processing_chain:
            self._drain_chain_queue()
        if self.async_chunks:
            self._distant_lod_refresh_timer += max(0.0, dt)
            if self._pending_sector is not None or (self._distant_lod_dirty_sectors and self._distant_lod_refresh_timer >= .15):
                self._refresh_distant_lod_in_background()
                self._distant_lod_refresh_timer = 0.0
        elif self._distant_lod_dirty_sectors:
            self._distant_lod_refresh_timer += max(0.0, dt)
            if self._distant_lod_refresh_timer >= .15:
                sector = min(self._distant_lod_dirty_sectors)
                self._refresh_distant_lod({sector})
                self._distant_lod_refresh_timer = 0.0
        if self._damage_state_dirty:
            self._damage_save_timer += max(0.0, dt)
            if self._damage_save_timer >= 1.5:
                self.save_damage_state()
        for obj in tuple(self.objects):
            if getattr(obj, "is_traffic", False):
                timer = getattr(obj, "_simulation_timer", 0.0) + max(0.0, dt)
                distance_sq = ((obj.x - sentry.x) ** 2 + (obj.z - sentry.z) ** 2
                               if sentry is not None else 0.0)
                interval = .05 if distance_sq < 250.0 ** 2 else .20
                if timer >= interval:
                    obj.step(timer, None)
                    obj._simulation_timer = 0.0
                else:
                    obj._simulation_timer = timer
                continue
            held_target = None
            active_state = (obj.dynamic or obj.held
                            or obj.frozen_until > self.game.elapsed
                            or obj.heat_until > self.game.elapsed
                            or (obj.damage_stage == 0 and obj.color != obj.original_tint))
            if active_state:
                obj.step(dt, held_target)
        if self.civilians and sentry is not None:
            player_chart = self.planet.local_coordinates(
                SimVec3(sentry.x, sentry.y, sentry.z))
            px, pz = player_chart
            for civilian in tuple(self.civilians):
                dx, dz = civilian.chart_x - px, civilian.chart_z - pz
                distance_sq = dx * dx + dz * dz
                civilian.set_visual_lod(distance_sq < 150.0 ** 2)
                animation_quality = getattr(self.settings, "npc_animation_quality", "medium")
                interval = (1 / 60 if distance_sq < 65.0 ** 2
                            else .10 if distance_sq < 240.0 ** 2
                            else .6 if animation_quality == "low" else .35)
                civilian._simulation_timer += max(0.0, dt)
                if civilian._simulation_timer >= interval:
                    step_dt = civilian._simulation_timer
                    civilian._simulation_timer = 0.0
                    civilian.step(step_dt, player_chart=player_chart)
        self._cleanup_dead_civilians()
        for debris in tuple(self.debris):
            debris._simulation_timer = getattr(debris, "_simulation_timer", 0.0) + max(0.0, dt)
            if debris._simulation_timer >= self.debris_step_interval:
                step_dt = debris._simulation_timer
                debris._simulation_timer = 0.0
                debris.step(step_dt)
        for effect in tuple(self.effects):
            effect.step(dt)

    def set_quality(self, settings) -> None:
        self.settings = settings
        quality = str(settings.quality).lower()
        if quality != self.quality:
            self._chunk_data_cache.clear()
        self.quality = quality
        self.debris_budget.maximum_live_pieces = {
            "low": 64, "medium": 144, "high": 320, "ultra": 480}.get(quality, 64)
        self.debris_step_interval = {"low": 1/30, "medium": 1/45,
                                     "high": 1/60, "ultra": 1/60}.get(quality, 1/30)
        steps = self.TERRAIN_STEPS_BY_QUALITY.get(quality, 200)
        if steps != self.terrain_steps:
            self.terrain_steps = steps
            self._terrain_art = self._build_terrain()
        self._refresh_distant_lod()
        self.refresh_population()

