"""Bounded, lightweight falling-tree animation for the island destruction system."""

from __future__ import annotations

from math import cos, sin
from random import Random

from ursina import Entity, color, destroy

from movement.flight_physics import Vec3 as SimVec3


TREE_GRAVITY, TIP_START, LYING_ANGLE, TREE_BOUNCE = 22.0, .10, 1.52, .22


class FallingTree:
    """A single pivoting tree with one angular physics step and pooled debris."""

    LIFETIME = 11.0

    def __init__(self, world, tree_id: str, position, scale: float,
                 tint, fall_direction, chain_depth: int = 0):
        self.world = world
        self.tree_id = tree_id
        self.position = SimVec3(float(position[0]), float(position[1]), float(position[2]))
        self.scale = float(scale)
        self.chain_depth = int(chain_depth)
        self.age = 0.0
        self.angle = 0.0
        self.angular_velocity = 0.0
        self.impacted = False
        direction = SimVec3(float(fall_direction.x), 0.0, float(fall_direction.z))
        if direction.length() < .01:
            direction = SimVec3(1.0, 0.0, 0.0)
        direction = direction.normalized()
        self.axis = SimVec3(direction.z, 0.0, -direction.x)

        self.pivot = Entity(parent=world.ground, name="falling-tree",
                            position=(self.position.x, self.position.y, self.position.z),
                            rotation=(0, 0, 0),
                            model=None, collider=None)
        Entity(parent=self.pivot, name="falling-tree-trunk", model="cube",
               position=(0, 2.3 * self.scale, 0),
               scale=(.30 * self.scale, 4.6 * self.scale, .30 * self.scale),
               color=color.rgb32(103, 72, 46), collider="box")
        Entity(parent=self.pivot, name="falling-tree-canopy", model="sphere",
               position=(0, 5.5 * self.scale, 0),
               scale=(2.55 * self.scale, 3.0 * self.scale, 2.55 * self.scale),
               color=tint, collider=None)
        Entity(parent=self.pivot, name="falling-tree-canopy-upper", model="sphere",
               position=(.35 * self.scale, 6.3 * self.scale, .22 * self.scale),
               scale=(1.75 * self.scale, 2.15 * self.scale, 1.8 * self.scale),
               color=tint, collider=None)
        self.random = Random(hash(tree_id) & 0xffffffff)

    def _impact(self) -> None:
        if self.impacted:
            return
        self.impacted = True
        point = SimVec3(self.position.x, self.position.y + .15, self.position.z)
        intensity = min(1.8, .55 + self.scale * .45)
        self.world._acquire_explosion(point, 2.5 * self.scale, intensity)
        count = self.world.debris_budget.reserve(min(10, max(4, int(4 + self.scale * 3))))
        up = self.world.planet.normal(point)
        for _ in range(count):
            direction = SimVec3(self.random.uniform(-1, 1), self.random.uniform(.2, 1.5),
                                self.random.uniform(-1, 1)).normalized()
            velocity = direction * self.random.uniform(3.0, 10.0)
            velocity = velocity + up * self.random.uniform(2.0, 6.0)
            tint = (color.rgb32(103, 72, 46) if self.random.random() < .48
                    else color.rgb32(47, 104, 52))
            self.world.spawn_debris(point, velocity, tint,
                                    self.random.uniform(.12, .35) * self.scale,
                                    min(4.0, self.world.settings.debris_lifetime))
        # A tree's landing can nudge nearby breakables once. The bounded depth
        # avoids chain reactions growing with each newly fallen tree.
        if self.chain_depth < 1:
            self.world.damage_nearby(point, 18.0 * self.scale,
                radius=3.0 * self.scale, impulse=12.0 * self.scale,
                ignore=None, chain_depth=1)

    def step(self, dt: float) -> None:
        dt = max(0.0, min(.05, float(dt)))
        self.age += dt
        # A rod pivoting at its foot: gravity's pull grows as it tips, so it starts slowly and ends fast.
        length = max(1.0, 7.0 * self.scale)
        self.angular_velocity += 1.5 * TREE_GRAVITY / length * sin(self.angle + TIP_START) * dt
        self.angle += self.angular_velocity * dt
        if self.angle >= LYING_ANGLE:
            self._impact()
            self.angle = LYING_ANGLE
            self.angular_velocity = -self.angular_velocity * TREE_BOUNCE if self.angular_velocity > .4 else 0.0
        rotation = self.axis * self.angle
        self.pivot.rotation = (rotation.x * 57.2958, rotation.y * 57.2958,
                               rotation.z * 57.2958)
        if self.age >= self.LIFETIME:
            self.world.effects.remove(self)
            if self.pivot and not self.pivot.is_empty():
                for part in tuple(self.pivot.children):
                    destroy(part, force_destroy=True)
                destroy(self.pivot, force_destroy=True)
