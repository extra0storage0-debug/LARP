"""Bounded lightweight visual effects for heat impacts and shockwaves."""

from __future__ import annotations

from math import sin

from ursina import Entity, Vec3, color, destroy
from game.art_style import shockwave_ring_mesh, soft_glow
from movement.flight_physics import Vec3 as SimVec3


FIRE_RGB = (255, 132, 42)


class TimedEffect:
    def __init__(self, world, position, tint, kind: str, lifetime: float = .6):
        self.world = world
        self.kind = kind
        self.age = 0.0
        self.lifetime = max(0.001, float(lifetime))
        if hasattr(position, "x"):
            self.origin = SimVec3(float(position.x), float(position.y), float(position.z))
        else:
            self.origin = SimVec3(float(position[0]), float(position[1]), float(position[2]))
        self.normal = world.planet.normal(self.origin)
        self.entity = Entity(model="circle" if kind in ("shockwave", "splash") else "sphere",
                             position=(self.origin.x, self.origin.y, self.origin.z),
                             color=tint, unlit=True,
                             transparency=True, double_sided=True)
        if kind in ("shockwave", "splash"):
            self.entity.scale = .8 if kind == "shockwave" else .25
            self.entity.wireframe = True
            self.entity.setQuat(world.planet.surface_plane_quaternion(self.origin))
        else:
            self.entity.scale = .15
        world.effects.append(self)

    def step(self, dt: float) -> None:
        self.age += dt
        alpha = min(1.0, self.age / self.lifetime)
        if self.kind == "shockwave":
            self.entity.scale = .8 + alpha * 18.0
            point = self.origin + self.normal * (self.age * .3)
            self.entity.position = Vec3(point.x, point.y, point.z)
        elif self.kind == "splash":
            self.entity.scale = .25 + alpha * 3.4
            point = self.origin + self.normal * .06
            self.entity.position = Vec3(point.x, point.y, point.z)
        else:
            self.entity.scale = .15 + alpha * .65
            point = self.origin + self.normal * (self.age * (1.2 + sin(self.age * 12.0) * .15))
            self.entity.position = Vec3(point.x, point.y, point.z)
        if self.kind == "splash":
            self.entity.color = color.rgba32(118, 208, 246,
                                             max(0, int(190 * (1.0 - alpha))))
        else:
            self.entity.color = color.rgba32(245, 128, 42,
                                             max(0, int(210 * (1.0 - alpha))))
        if self.age >= self.lifetime:
            if hasattr(self.entity, "eternal"):
                destroy(self.entity, force_destroy=True)
            else:  # Renderer-independent tests can use a minimal fake entity.
                self.entity.disable()
                self.entity.removeNode()
            if self in self.world.effects:
                self.world.effects.remove(self)


class DestructionBurst:
    """Reusable, bounded flash/ring/fire/smoke bundle for major impacts."""

    LIFETIME = 1.35

    def __init__(self, world):
        self.world = world
        self.age = self.lifetime = 0.0
        self.origin = SimVec3()
        self.normal = SimVec3(0, 1, 0)
        self.radius = self.intensity = 1.0
        self.smoke_scale = 1.0
        self.fire_rgb = FIRE_RGB
        self.flash = soft_glow(color=color.rgba32(255, 232, 170, 0), visible=False)
        self.ring = Entity(model=shockwave_ring_mesh(), color=color.rgba32(255, 214, 150, 0),
                           unlit=True, transparency=True, double_sided=True,
                           collider=None, visible=False)
        self.ring.setDepthWrite(False)
        self.smoke = soft_glow(color=color.rgba32(214, 196, 176, 0), visible=False)
        self.fire = soft_glow(color=color.rgba32(255, 132, 42, 0), visible=False)
        self.entities = (self.flash, self.ring, self.smoke, self.fire)

    def start(self, position, radius: float, intensity: float) -> None:
        self.age = 0.0
        self.fire_rgb = FIRE_RGB
        scales = getattr(self.world, "scales", None)
        self.lifetime = self.LIFETIME * (scales.effect_duration if scales else 1.0)
        self.smoke_scale = scales.smoke if scales else 1.0
        if hasattr(position, "x"):
            self.origin = SimVec3(float(position.x), float(position.y), float(position.z))
        else:
            self.origin = SimVec3(float(position[0]), float(position[1]), float(position[2]))
        self.normal = self.world.planet.normal(self.origin)
        self.radius = max(1.0, min(80.0, float(radius)))
        self.intensity = max(.25, min(4.0, float(intensity)))
        self.ring.setQuat(self.world.planet.surface_plane_quaternion(self.origin))
        point = Vec3(self.origin.x, self.origin.y + .1, self.origin.z)
        for entity in self.entities:
            entity.position = point
            entity.visible = True

    def step(self, dt: float) -> None:
        self.age += max(0.0, dt)
        t = min(1.0, self.age / self.lifetime)
        origin = Vec3(self.origin.x + self.normal.x * .1,
                      self.origin.y + self.normal.y * .1,
                      self.origin.z + self.normal.z * .1)
        self.flash.position = origin
        self.flash.scale = .8 + self.radius * self.intensity * .13 * (1.0 - t)
        self.flash.color = color.rgba32(255, 232, 170, int(235 * (1.0 - t) ** 3))
        self.ring.position = origin
        # Eases out, so the wave leaps away and then settles.
        ring_size = self.radius * (.25 + 2.1 * (1.0 - (1.0 - t) ** 3)) * self.intensity ** .35
        self.ring.scale = (ring_size, ring_size, ring_size)
        self.ring.color = color.rgba32(255, 214, 150, int(170 * (1.0 - t) ** 2))
        self.smoke.position = origin + Vec3(0, t * self.radius * .42, 0)
        smoke_size = self.radius * (.14 + t * .42) * self.intensity ** .35
        self.smoke.scale = (smoke_size, smoke_size * 1.5, smoke_size)
        self.smoke.color = color.rgba32(214, 196, 176, min(255, int(150 * (1.0 - t) * self.smoke_scale)))
        self.fire.position = origin + Vec3(0, t * self.radius * .14, 0)
        fire_size = self.radius * (.20 + .24 * (1.0 - t)) * self.intensity ** .25
        self.fire.scale = fire_size
        red, green, blue = self.fire_rgb
        self.fire.color = color.rgba32(red, min(255, int(green + 70 * t)), blue,
                                       int(225 * (1.0 - t) ** 2))
        if self.age >= self.lifetime:
            self.world.recycle_explosion(self)
