"""Ground-destruction effects for heat-vision impacts on Earth's terrain.

ScorchCrater:
  - A persistent dark scorch mark (flat circle) oriented to the planet surface.
  - Spawns DebrisPiece ejecta outward from the impact point.
  - Slowly fades over ~30 s so the world doesn't accumulate unlimited decals;
    the oldest decals are culled when MAX_CRATERS is exceeded.

ground_ray_intersect:
  - Finds the ground hit point for the camera ray without needing a collider on
    the terrain mesh.  Uses a coarse march then bisects to ~0.05 m accuracy.
"""
from __future__ import annotations

from math import sqrt
from random import Random
from typing import TYPE_CHECKING

from ursina import Entity, Mesh, Vec3, color
from ursina.shaders import lit_with_shadows_shader

from movement.flight_physics import Vec3 as SimVec3
from world.interactive_objects import DebrisPiece

if TYPE_CHECKING:
    from world.city_generator import CityWorld

# Hard cap on live scorch marks; oldest removed when exceeded.
MAX_CRATERS = 24
# Budget of ejecta chunks per crater strike.
EJECTA_PER_CRATER = 5


def ground_ray_intersect(planet: object,
                         origin: Vec3,
                         direction: Vec3,
                         max_range: float = 500.0,
                         steps: int = 48) -> SimVec3 | None:
    """March camera ray and return the first ground-level (altitude ≤ 0) hit.

    Returns None if the ray never reaches the surface within *max_range*.
    """
    ox, oy, oz = float(origin.x), float(origin.y), float(origin.z)
    dx, dy, dz = float(direction.x), float(direction.y), float(direction.z)
    length = sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-8:
        return None
    dx, dy, dz = dx / length, dy / length, dz / length

    step_size = max_range / steps
    prev_alt = None
    prev_t = 0.0

    for i in range(steps + 1):
        t = i * step_size
        px, py, pz = ox + dx * t, oy + dy * t, oz + dz * t
        pos = SimVec3(px, py, pz)
        alt = planet.altitude(pos)
        if prev_alt is not None and prev_alt > 0.0 and alt <= 0.0:
            # Sign change — bisect between (prev_t, t) for accuracy.
            lo, hi = prev_t, t
            for _ in range(12):
                mid = (lo + hi) * 0.5
                mp = SimVec3(ox + dx * mid, oy + dy * mid, oz + dz * mid)
                if planet.altitude(mp) > 0.0:
                    lo = mid
                else:
                    hi = mid
            mid = (lo + hi) * 0.5
            hit = SimVec3(ox + dx * mid, oy + dy * mid, oz + dz * mid)
            # Snap precisely to ground level.
            snapped = planet.project(hit, 0.0)
            return SimVec3(snapped.x, snapped.y, snapped.z)
        prev_alt = alt
        prev_t = t
    return None


class ScorchCrater:
    """A ground impact scar: dark scorch decal + ejected dirt chunks."""

    _all: list["ScorchCrater"] = []   # class-level registry for cull logic

    def __init__(self, world: "CityWorld", impact: SimVec3,
                 radius: float = 1.6, intensity: float = 1.0) -> None:
        self.world = world
        self.age = 0.0
        self.fade_start = 20.0           # start fading at 20 s
        self.lifetime = 30.0             # fully gone at 30 s
        self.origin = impact
        planet = world.planet

        # ---- scorch decal (flat circle on the ground) ----
        scorch_scale = radius * 2.0
        self.scorch = Entity(
            model="circle",
            position=(impact.x, impact.y, impact.z),
            scale=(scorch_scale, scorch_scale, scorch_scale),
            color=color.rgba32(18, 12, 8, 230),
            unlit=False,
            double_sided=True,
            transparency=True,
            shader=lit_with_shadows_shader,
        )
        self.scorch.setQuat(planet.surface_plane_quaternion(impact))
        # Lift slightly off the ground so it's not z-fighting the terrain.
        up = planet.normal(impact)
        lifted = SimVec3(impact.x + up.x * 0.06,
                         impact.y + up.y * 0.06,
                         impact.z + up.z * 0.06)
        self.scorch.position = Vec3(lifted.x, lifted.y, lifted.z)

        # ---- inner hot glow (fades out quickly) ----
        self.hot_glow = Entity(
            model="circle",
            position=Vec3(lifted.x, lifted.y, lifted.z),
            scale=(scorch_scale * 0.55, scorch_scale * 0.55, scorch_scale * 0.55),
            color=color.rgba32(255, 140, 30, 200),
            unlit=True,
            double_sided=True,
            transparency=True,
        )
        self.hot_glow.setQuat(planet.surface_plane_quaternion(impact))
        self._glow_lifetime = 1.8       # hot glow fades in 1.8 s

        # ---- crater rim bumps (dark reddish-brown cubes around edge) ----
        east, up_v, north = planet.tangent_frame(impact)
        rim_rng = Random(int(abs(impact.x * 1000)) ^ int(abs(impact.z * 1000)))
        self._rim: list[Entity] = []
        n_rim = min(8, max(4, int(intensity * 6)))
        for i in range(n_rim):
            angle_frac = i / n_rim
            import math
            angle = angle_frac * 2.0 * math.pi + rim_rng.uniform(-0.3, 0.3)
            r = radius * rim_rng.uniform(0.75, 1.05)
            ex = east.x * math.cos(angle) * r + north.x * math.sin(angle) * r
            ey = east.y * math.cos(angle) * r + north.y * math.sin(angle) * r
            ez = east.z * math.cos(angle) * r + north.z * math.sin(angle) * r
            rim_pos = SimVec3(impact.x + ex + up_v.x * 0.08,
                              impact.y + ey + up_v.y * 0.08,
                              impact.z + ez + up_v.z * 0.08)
            size = rim_rng.uniform(0.18, 0.38) * intensity
            ent = Entity(
                model="sphere",
                position=(rim_pos.x, rim_pos.y, rim_pos.z),
                scale=size,
                color=color.rgb32(rim_rng.randint(50, 80),
                                  rim_rng.randint(35, 55),
                                  rim_rng.randint(20, 35)),
                shader=lit_with_shadows_shader,
            )
            self._rim.append(ent)

        # ---- ejecta debris ----
        rng = Random(int(abs(impact.x + impact.z) * 997))
        budget = world.debris_budget.reserve(EJECTA_PER_CRATER)
        for _ in range(budget):
            import math
            angle = rng.uniform(0.0, 2.0 * math.pi)
            speed = rng.uniform(3.5, 9.0) * intensity
            vx = (east.x * math.cos(angle) + north.x * math.sin(angle)) * speed
            vy = (east.y * math.cos(angle) + north.y * math.sin(angle)) * speed
            vz = (east.z * math.cos(angle) + north.z * math.sin(angle)) * speed
            up_speed = rng.uniform(3.0, 7.0) * intensity
            vel = SimVec3(vx + up_v.x * up_speed,
                          vy + up_v.y * up_speed,
                          vz + up_v.z * up_speed)
            size = rng.uniform(0.08, 0.22) * intensity
            piece = world.spawn_debris(
                (impact.x, impact.y, impact.z),
                vel,
                color.rgb32(rng.randint(60, 90),
                            rng.randint(45, 65),
                            rng.randint(25, 40)),
                size,
                rng.uniform(2.0, 5.0),
            )

        # Register and cull oldest if over cap.
        world.effects.append(self)
        ScorchCrater._all.append(self)
        while len(ScorchCrater._all) > MAX_CRATERS:
            oldest = ScorchCrater._all[0]
            oldest._force_remove()

    # ------------------------------------------------------------------
    def step(self, dt: float) -> None:
        self.age += dt

        # Hot-glow fades in the first ~1.8 s.
        if self.hot_glow is not None:
            glow_alpha = max(0.0, 1.0 - self.age / self._glow_lifetime)
            self.hot_glow.color = color.rgba32(255, 140, 30, int(200 * glow_alpha))
            if glow_alpha <= 0.0:
                self.hot_glow.disable()
                self.hot_glow = None

        # Scorch decal fades after fade_start.
        if self.age > self.fade_start:
            fade = 1.0 - (self.age - self.fade_start) / (self.lifetime - self.fade_start)
            fade = max(0.0, fade)
            self.scorch.color = color.rgba32(18, 12, 8, int(230 * fade))

        if self.age >= self.lifetime:
            self._force_remove()

    def _force_remove(self) -> None:
        """Disable all owned entities and deregister from world lists."""
        self.scorch.disable()
        if self.hot_glow is not None:
            self.hot_glow.disable()
            self.hot_glow = None
        for ent in self._rim:
            ent.disable()
        self._rim.clear()
        if self in self.world.effects:
            self.world.effects.remove(self)
        if self in ScorchCrater._all:
            ScorchCrater._all.remove(self)
        # Advance age past lifetime so any lingering step() calls are no-ops.
        self.age = self.lifetime + 1.0
