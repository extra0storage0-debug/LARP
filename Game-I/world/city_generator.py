"""Seeded procedural district. All art uses generated geometry and Ursina primitives."""

from __future__ import annotations

import math
from random import Random

from ursina import Entity, Mesh, Vec3, color

from config import GraphicsSettings
from movement.flight_physics import Vec3 as SimVec3
from combat.damage_system import impact_damage
from world.buildings import Building
from world.destructible_props import DebrisBudget
from world.interactive_objects import DestructibleEntity, TrafficVehicle
from world.lighting import CITY_SURFACE_SHADER


def append_quad(vertices, triangles, colors, points, tint):
    first = len(vertices)
    vertices.extend(points)
    triangles.extend((first, first + 1, first + 2, first, first + 2, first + 3))
    colors.extend((tint, tint, tint, tint))


def append_box(vertices, triangles, colors, center, half_extents, tint):
    x, y, z = center
    hx, hy, hz = half_extents
    faces = (
        ((x-hx,y-hy,z+hz),(x+hx,y-hy,z+hz),(x+hx,y+hy,z+hz),(x-hx,y+hy,z+hz)),
        ((x+hx,y-hy,z-hz),(x-hx,y-hy,z-hz),(x-hx,y+hy,z-hz),(x+hx,y+hy,z-hz)),
        ((x+hx,y-hy,z+hz),(x+hx,y-hy,z-hz),(x+hx,y+hy,z-hz),(x+hx,y+hy,z+hz)),
        ((x-hx,y-hy,z-hz),(x-hx,y-hy,z+hz),(x-hx,y+hy,z+hz),(x-hx,y+hy,z-hz)),
        ((x-hx,y+hy,z+hz),(x+hx,y+hy,z+hz),(x+hx,y+hy,z-hz),(x-hx,y+hy,z-hz)),
        ((x-hx,y-hy,z-hz),(x+hx,y-hy,z-hz),(x+hx,y-hy,z+hz),(x-hx,y-hy,z+hz)),
    )
    for face in faces:
        append_quad(vertices, triangles, colors, face, tint)


class CityWorld:
    BUILDING_GRID_CELL_SIZE = 40.0

    def __init__(self, game, settings: GraphicsSettings):
        self.game = game
        self.settings = settings
        self.random = Random(2026)
        self.objects: list[DestructibleEntity] = []
        self.debris: list[Entity] = []
        self.civilians = []
        self.animals = []
        self.effects: list[Entity] = []
        self.debris_budget = DebrisBudget(240)
        self.buildings: list[Building] = []
        self._building_cells: dict[tuple[int, int], list[Building]] = {}
        self.traffic: list[TrafficVehicle] = []
        self.static_art: list[Entity] = []
        self._tree_instances: list[tuple[float, float, float]] = []
        self.planet = game.planet

    def _generate(self) -> None:
        # The city game stays at street level. Building the multi-shell global
        # Earth render (including several sphere meshes and large textures)
        # served the removed orbital exploration mode and is not used here.
        self._planet_art = ()
        self._terrain_art = self.planet.make_local_terrain_entity(self.settings.quality)
        if self._terrain_art is not None:
            self.static_art.append(self._terrain_art)
        self._ground_vertices, self._ground_triangles, self._ground_colors = [], [], []
        self._add_ground_and_roads()

        palette = [color.rgb32(49, 62, 82), color.rgb32(61, 72, 91), color.rgb32(70, 76, 88),
                   color.rgb32(55, 73, 87), color.rgb32(78, 83, 92)]
        for grid_x in range(-6, 6):
            for grid_z in range(-6, 6):
                if abs(grid_x) <= 1 and abs(grid_z) <= 1:
                    continue
                center_x = (grid_x + .5) * 40.0
                center_z = (grid_z + .5) * 40.0
                width = self.random.uniform(18.0, 27.0)
                depth = self.random.uniform(18.0, 27.0)
                height = self.random.uniform(14.0, 52.0)
                x = center_x + self.random.uniform(-3.0, 3.0)
                z = center_z + self.random.uniform(-3.0, 3.0)
                building = Building(self.game, (x, height * .5, z), (width, height, depth),
                                    self.random.choice(palette), self.random.randrange(1, 1_000_000))
                self.buildings.append(building)

        self._build_building_spatial_index()

        self._add_park()
        self._add_trees_and_lights()
        self._build_tree_mesh()
        self._add_street_props()
        self._add_traffic()

    def _build_building_spatial_index(self) -> None:
        """Index building footprints by 40 m cells for cheap NPC avoidance."""
        cell_size = self.BUILDING_GRID_CELL_SIZE
        cells: dict[tuple[int, int], list[Building]] = {}
        for building in self.buildings:
            # Include the NPC clearance in each indexed footprint so querying
            # the cell containing an NPC cannot miss a nearby building.
            half_x = abs(building.scale_x) * .5 + .6
            half_z = abs(building.scale_z) * .5 + .6
            min_x = int((building.chart_x - half_x) // cell_size)
            max_x = int((building.chart_x + half_x) // cell_size)
            min_z = int((building.chart_z - half_z) // cell_size)
            max_z = int((building.chart_z + half_z) // cell_size)
            for cell_x in range(min_x, max_x + 1):
                for cell_z in range(min_z, max_z + 1):
                    cells.setdefault((cell_x, cell_z), []).append(building)
        self._building_cells = cells

    def nearby_buildings(self, east: float, north: float):
        """Return buildings whose expanded footprints overlap this local cell."""
        cell_size = self.BUILDING_GRID_CELL_SIZE
        cell = (int(east // cell_size), int(north // cell_size))
        return self._building_cells.get(cell, ())

    def _add_ground_and_roads(self) -> None:
        vertices, triangles, colors = self._ground_vertices, self._ground_triangles, self._ground_colors

        def rectangle(x, z, width, depth, y, tint):
            count_x = max(1, int(abs(width) / 10.0 + .999))
            count_z = max(1, int(abs(depth) / 10.0 + .999))
            for ix in range(count_x):
                x0 = x - width*.5 + width * ix / count_x
                x1 = x - width*.5 + width * (ix + 1) / count_x
                for iz in range(count_z):
                    z0 = z - depth*.5 + depth * iz / count_z
                    z1 = z - depth*.5 + depth * (iz + 1) / count_z
                    points = ((x0,y,z0),(x1,y,z0),(x1,y,z1),(x0,y,z1))
                    first = len(vertices)
                    vertices.extend(self._surface_point(point) for point in points)
                    triangles.extend((first, first+1, first+2, first, first+2, first+3))
                    colors.extend((tint,) * 4)

        rectangle(0, 0, 560, 560, -.08, color.rgb32(45, 67, 48))
        rectangle(0, 0, 47, 47, -.01, color.rgb32(74, 82, 88))
        road_tint = color.rgb32(47, 50, 56)
        curb_tint = color.rgb32(139, 140, 132)
        for index in range(-6, 7):
            offset = index * 40.0
            rectangle(0, offset, 560, 8.5, 0, road_tint)
            rectangle(offset, 0, 8.5, 560, 0, road_tint)
            for side in (-1, 1):
                rectangle(0, offset + side * 5.5, 560, 2.0, .015, curb_tint)
                rectangle(offset + side * 5.5, 0, 2.0, 560, .015, curb_tint)
        rectangle(0, 0, 42, 42, .025, color.rgb32(47, 91, 57))
        path_tint = color.rgb32(157, 151, 123)
        for offset in (-12, -6, 0, 6, 12):
            rectangle(offset, 0, 1, 29, .18, path_tint)

        ground_mesh = Mesh(vertices=vertices, triangles=triangles,
                           colors=colors, static=True)
        ground_entity = Entity(model=ground_mesh, color=color.white,
                               double_sided=True, collider=None,
                               shader=CITY_SURFACE_SHADER)
        self.static_art.append(ground_entity)

    def _add_park(self) -> None:
        # Central park - lush dense grove of trees
        for _ in range(35):
            self._tree(self.random.uniform(-17.5, 17.5), self.random.uniform(-17.5, 17.5), scale=self.random.uniform(.85, 1.45))

    def _tree(self, x: float, z: float, scale: float = 1.0) -> None:
        self._tree_instances.append((x, z, scale))

    def _add_trees_and_lights(self) -> None:
        # 1. District street avenues and boulevards lined with trees
        for lane_z in (-12.0, -6.0, 6.0, 12.0):
            for x_idx in range(-12, 13):
                x = x_idx * 18.0 + self.random.uniform(-1.5, 1.5)
                if abs(x) < 22.0 and abs(lane_z) < 22.0:
                    continue  # center park handled separately
                self._tree(x, lane_z + self.random.uniform(-1.0, 1.0), self.random.uniform(.8, 1.2))

        # 2. Side avenues and courtyard greenery
        for _ in range(120):
            x = self.random.choice((-1, 1)) * self.random.uniform(12, 240)
            z = self.random.uniform(-240, 240)
            if abs(x % 40.0) < 6.0 or abs(z % 40.0) < 6.0:
                continue
            self._tree(x, z, self.random.uniform(.75, 1.35))

        # 3. Outer perimeter forest belt surrounding the district
        for _ in range(160):
            # Ring outside the urban core (from r=210 to 320)
            angle = self.random.uniform(0, 6.28318)
            radius = self.random.uniform(210.0, 310.0)
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            self._tree(x, z, self.random.uniform(0.9, 1.6))
        vertices, triangles, colors = [], [], []
        for index in range(18):
            x = -220 + index * 26
            z = 8.0 if index % 2 else -8.0
            append_box(vertices, triangles, colors, (x, 3.0, z), (.055, 3.0, .055),
                       color.rgb32(70, 74, 80))
            append_box(vertices, triangles, colors, (x, 6.0, z + 1.0), (.375, .08, .08),
                       color.rgb32(210, 195, 146))
        vertices = [self._surface_point(point) for point in vertices]
        lamp_mesh = Mesh(vertices=vertices, triangles=triangles, colors=colors, static=True)
        self.static_art.append(Entity(model=lamp_mesh, color=color.white,
                                      double_sided=True, collider=None,
                                      shader=CITY_SURFACE_SHADER))

    def _build_tree_mesh(self) -> None:
        vertices, triangles, colors = [], [], []
        trunk_tint = color.rgb32(92, 63, 42)
        leaf_tints = [
            color.rgb32(42, 102, 54),   # rich emerald forest
            color.rgb32(56, 126, 68),   # vibrant green
            color.rgb32(36, 88, 48),    # deep pine
            color.rgb32(72, 142, 60),   # olive green
            color.rgb32(48, 111, 62),   # standard foliage
        ]
        golden = (1.0 + 5.0 ** .5) * .5
        ico_points = ((-1,golden,0),(1,golden,0),(-1,-golden,0),(1,-golden,0),
                      (0,-1,golden),(0,1,golden),(0,-1,-golden),(0,1,-golden),
                      (golden,0,-1),(golden,0,1),(-golden,0,-1),(-golden,0,1))
        faces = ((0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),(1,5,9),
                 (5,11,4),(11,10,2),(10,7,6),(7,1,8),(3,9,4),(3,4,2),
                 (3,2,6),(3,6,8),(3,8,9),(4,9,5),(2,4,11),(6,2,10),
                 (8,6,7),(9,8,1))
        trunk_half = (.19, 1.2, .19)
        for i, (x, z, scale) in enumerate(self._tree_instances):
            leaf_tint = leaf_tints[i % len(leaf_tints)]
            append_box(vertices, triangles, colors, (x, 1.2 * scale, z),
                       tuple(component * scale for component in trunk_half), trunk_tint)
            first = len(vertices)
            center_y = 3.0 * scale
            for px, py, pz in ico_points:
                magnitude = (px*px + py*py + pz*pz) ** .5
                vertices.append((x + px / magnitude * 1.05 * scale,
                                 center_y + py / magnitude * 1.3 * scale,
                                 z + pz / magnitude * 1.05 * scale))
                colors.append(leaf_tint)
            for a, b, c in faces:
                triangles.extend((first + a, first + b, first + c))
        vertices = [self._surface_point(point) for point in vertices]
        tree_mesh = Mesh(vertices=vertices, triangles=triangles, colors=colors, static=True)
        self.static_art.append(Entity(model=tree_mesh, color=color.white,
                                      double_sided=True, collider=None,
                                      shader=CITY_SURFACE_SHADER))

    def _add_street_props(self) -> None:
        for _ in range(20):
            x = self.random.uniform(-240, 240)
            z = self.random.choice((-1, 1)) * self.random.uniform(7.0, 10.0)
            if abs(x) < 28 and abs(z) < 28:
                continue
            width = self.random.uniform(.7, 1.4)
            point = self.planet.point_from_local(x, z, width * .5)
            prop = DestructibleEntity(self.game, point,
                                      (width, width, width), color.rgb32(122, 94, 68), 65.0, "street-prop")
            prop.dynamic = False
            prop.chart_x, prop.chart_z = x, z
            self.planet.orient_entity(prop, self._sim(point))

    def _add_traffic(self) -> None:
        for lane_z, direction, starts in ((-2.25, 1.0, (-215, -105, 45)),
                                           (2.25, -1.0, (215, 105, -45))):
            for x in starts:
                point = self.planet.point_from_local(x, lane_z, .66)
                vehicle = TrafficVehicle(self.game, point, direction)
                vehicle.chart_x, vehicle.chart_z = x, lane_z
                self.planet.orient_entity(vehicle, self._sim(point), 90.0 if direction > 0 else -90.0)
                self.traffic.append(vehicle)

    @staticmethod
    def _sim(point):
        if hasattr(point, "x"):
            return SimVec3(float(point.x), float(point.y), float(point.z))
        return SimVec3(float(point[0]), float(point[1]), float(point[2]))

    def _surface_point(self, point):
        x, height, z = point
        mapped = self.planet.point_from_local(x, z, height)
        return (mapped.x, mapped.y, mapped.z)

    def register_object(self, obj: DestructibleEntity) -> None:
        self.objects.append(obj)

    def remove_object(self, obj: DestructibleEntity) -> None:
        if obj in self.objects:
            self.objects.remove(obj)
        if obj in self.traffic:
            self.traffic.remove(obj)

    def set_quality(self, settings: GraphicsSettings) -> None:
        quality_changed = settings.quality != self.settings.quality
        self.settings = settings
        if quality_changed:
            previous = self._planet_art
            previous_terrain = self._terrain_art
            for entity in previous:
                if entity in self.static_art:
                    self.static_art.remove(entity)
                entity.disable()
                entity.removeNode()
            self._planet_art = ()
            self._terrain_art = self.planet.make_local_terrain_entity(settings.quality)
            if self._terrain_art is not None:
                self.static_art.append(self._terrain_art)
            if previous_terrain is not None:
                if previous_terrain in self.static_art:
                    self.static_art.remove(previous_terrain)
                previous_terrain.disable()
                previous_terrain.removeNode()
        from characters.civilian import Civilian
        while len(self.civilians) < settings.civilian_count:
            index = len(self.civilians)
            x = self.game.random.uniform(-25, 25)
            z = self.game.random.choice((-1, 1)) * self.game.random.uniform(8, 22)
            self.civilians.append(Civilian(self.game, (x, 0, z), index + 100))
        while len(self.civilians) > settings.civilian_count:
            civilian = self.civilians.pop()
            civilian.entity.disable()
            civilian.entity.removeNode()

        # Wildlife is not part of the current compact urban population.
        while self.animals:
            animal = self.animals.pop()
            animal.entity.disable()
            animal.entity.removeNode()

    def add_debris(self, item: Entity) -> None:
        self.debris.append(item)

    def remove_debris(self, item: Entity) -> None:
        if item in self.debris:
            self.debris.remove(item)
            self.debris_budget.release(1)

    def notify_danger(self, origin: SimVec3) -> None:
        for civilian in tuple(self.civilians):
            civilian.react_to_danger(origin)
        for animal in tuple(self.animals):
            animal.react_to_danger(origin)

    def damage_nearby(self, origin: SimVec3, amount: float, *, radius: float = 5.0,
                      impulse: float = 8.0, ignore=None) -> None:
        for obj in tuple(self.objects):
            if obj is ignore or not obj.enabled:
                continue
            dx, dy, dz = obj.x - origin.x, obj.y - origin.y, obj.z - origin.z
            distance = (dx * dx + dy * dy + dz * dz) ** .5
            if distance < radius:
                direction = SimVec3(dx, max(.2, dy), dz).normalized()
                falloff = 1.0 - distance / radius
                obj.take_damage(amount * falloff, direction * impulse * falloff)

    def sonic_boom(self, origin: SimVec3, direction: SimVec3) -> None:
        from game.effects import TimedEffect
        from ursina import color
        TimedEffect(self, (origin.x, origin.y, origin.z), color.azure, "shockwave", .65)
        self.damage_nearby(origin, 32.0, radius=18.0, impulse=72.0)
        self.notify_danger(origin)

    def resolve_sentry(self, sentry) -> None:
        radius = .52
        sentry_altitude = self.planet.altitude(SimVec3(sentry.x, sentry.y, sentry.z))
        for obj in tuple(self.objects):
            if obj is sentry or not obj.enabled or obj.held:
                continue
            half_x, half_z = abs(obj.scale_x) * .5, abs(obj.scale_z) * .5
            dx, dz = sentry.x - obj.x, sentry.z - obj.z
            overlap_x, overlap_z = radius + half_x - abs(dx), radius + half_z - abs(dz)
            if overlap_x <= 0 or overlap_z <= 0:
                continue
            object_altitude = self.planet.altitude(SimVec3(obj.x, obj.y, obj.z))
            sentry_top = sentry_altitude + 2.85
            object_bottom = object_altitude - abs(obj.scale_y) * .5
            object_top = object_altitude + abs(obj.scale_y) * .5
            if sentry_top < object_bottom or sentry_altitude > object_top:
                continue
            speed = sentry.flight.speed_mps if sentry.flight.is_flying else sentry.ground.velocity.length()
            if speed > 18.0 and self.game.elapsed >= sentry.next_impact_damage:
                cfg = getattr(self.game, "sentry_config", None)
                dmg_mult = cfg.get("collision_damage_multiplier", 1.0) if cfg else 1.0
                sentry.take_damage(min(25.0, (speed - 18.0) * .3) * dmg_mult)
                sentry.next_impact_damage = self.game.elapsed + .65
                self.game.camera_impulse = max(self.game.camera_impulse, .6)
            if overlap_x < overlap_z:
                sentry.x += overlap_x if dx >= 0 else -overlap_x
            else:
                sentry.z += overlap_z if dz >= 0 else -overlap_z
        position = SimVec3(sentry.x, sentry.y, sentry.z)
        altitude = self.planet.altitude(position)
        ocean = self.planet.is_ocean(position)
        if ocean and self.game.sentry.flight.is_flying:
            if altitude < -18.0:
                position = self.planet.project(position, -18.0)
                up = self.planet.normal(position)
                velocity = self.game.sentry.flight.velocity
                radial = velocity.x * up.x + velocity.y * up.y + velocity.z * up.z
                if radial < 0.0:
                    self.game.sentry.flight.velocity = velocity - up * radial
        elif not self.game.sentry.flight.is_flying:
            position = self.planet.project(position, .25)
        elif altitude < .25:
            position = self.planet.project(position, .25)
            up = self.planet.normal(position)
            velocity = self.game.sentry.flight.velocity
            radial = velocity.x * up.x + velocity.y * up.y + velocity.z * up.z
            if radial < 0:
                self.game.sentry.flight.velocity = velocity - up * radial
        sentry.position = Vec3(position.x, position.y, position.z)

    def resolve_object_collision(self, moving, *, old_position=None, impact_speed: float | None = None) -> None:
        if not moving.enabled:
            return
        speed = impact_speed if impact_speed is not None else moving.velocity.length()
        damage = impact_damage(speed)
        if damage <= 0.0:
            return
        for other in tuple(self.objects):
            if other is moving or not other.enabled or other.held:
                continue
            overlap_x = (abs(moving.scale_x) + abs(other.scale_x)) * .5 - abs(moving.x - other.x)
            overlap_y = (abs(moving.scale_y) + abs(other.scale_y)) * .5 - abs(moving.y - other.y)
            overlap_z = (abs(moving.scale_z) + abs(other.scale_z)) * .5 - abs(moving.z - other.z)
            if min(overlap_x, overlap_y, overlap_z) <= 0:
                continue
            delta = SimVec3(moving.x - other.x, moving.y - other.y, moving.z - other.z)
            normal = delta.normalized()
            if normal.length() == 0:
                normal = SimVec3(1.0, 0.0, 0.0)
            cfg = getattr(self.game, "sentry_config", None)
            obj_dmg_mult = cfg.get("object_damage_multiplier", 1.0) if cfg else 1.0
            other.take_damage(damage * obj_dmg_mult, normal * min(40.0, speed * .65))
            if moving.dynamic:
                moving.take_damage(damage * .18)
                if moving.enabled:
                    moving.velocity = moving.velocity - normal * (speed * 1.35)
                    penetration = min(overlap_x, overlap_y, overlap_z) + .01
                    moving.position += Vec3(normal.x * penetration, normal.y * penetration,
                                            normal.z * penetration)
            else:
                if old_position is not None and hasattr(moving, "lane_direction"):
                    moving.position = old_position
                    moving.lane_direction *= -1.0
                    moving.rotation_y = 90.0 if moving.lane_direction > 0 else -90.0
            break

    def update(self, dt: float) -> None:
        sentry = getattr(self.game, "sentry", None)
        player_chart = None
        if sentry is not None:
            player_chart = self.planet.local_coordinates(
                SimVec3(sentry.x, sentry.y, sentry.z))
        for obj in tuple(self.objects):
            target = self.game.strength.held_target if obj.held else None
            obj.step(dt, target)
        for debris in tuple(self.debris):
            debris.step(dt)
        for civilian in self.civilians:
            self._step_npc(civilian, dt, player_chart)
        for animal in self.animals:
            self._step_npc(animal, dt, player_chart)
        for effect in tuple(self.effects):
            effect.step(dt)

    @staticmethod
    def _step_npc(actor, dt: float, player_chart) -> None:
        """Tick nearby NPCs at frame rate and distant ones at 10–20 Hz."""
        if player_chart is None:
            actor.step(dt)
            return
        dx = actor.chart_x - player_chart[0]
        dz = actor.chart_z - player_chart[1]
        distance_sq = dx * dx + dz * dz
        interval = (1.0 / 60.0 if distance_sq < 60.0 ** 2
                    else 1.0 / 20.0 if distance_sq < 180.0 ** 2
                    else 1.0 / 10.0)
        accumulated = getattr(actor, "_update_accumulator", 0.0) + dt
        if accumulated + 1e-8 < interval:
            actor._update_accumulator = accumulated
            return
        actor._update_accumulator = 0.0
        actor.step(accumulated, player_chart=player_chart)


class CityGenerator:
    def __init__(self, game, settings: GraphicsSettings):
        self.world = CityWorld(game, settings)
        game.world = self.world
        self.world._generate()
