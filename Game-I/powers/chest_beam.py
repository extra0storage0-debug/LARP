"""Sentry's and Soldier Boy's key 1: a continuous energy beam from the centre of the chest."""

from __future__ import annotations

from math import atan2, degrees
from random import Random

from panda3d.core import Point3
from ursina import color, scene

from movement.flight_physics import Vec3 as SimVec3, rotate_towards_degrees
from powers.base import BEAM_TRACE_INTERVAL, BeamAbility
from powers.vitals import HEAT, RADIATION

CHEST_POINT = Point3(0.0, 2.08, .33)  # on the body's own front, where the chest emblem sits
WIDTH_SCALE = 2.4
TURN_RATE = 360.0                     # degrees per second, to keep the chest towards the target
STREAM_EVERY, GLOW_EVERY = 2, 4       # in beam ticks, so a long beam stays cheap on the particle pool


class ChestBeam(BeamAbility):
    """Press to fire, press again to stop. It follows the nearest enemy and stops when none are left.

    Damage comes in beam ticks, fifteen a second. Speed is how fast the beam's front travels: it has
    to reach a target before it can hurt it, and starts again from the chest on a new target.
    """

    ability_id = "chest_beam"
    SPARK = (255, 255, 255, 255)
    STREAM = (255, 255, 255, 180)
    CHEST_GLOW = (255, 255, 255, 170)
    ARMS_BACK = 20.0  # the chest pushes forward, arms drawn behind it

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.front = 0.0
        self.tracking = None
        self.engaged = False
        self.body_yaw = None
        self.ticks = 0
        self.rng = Random(hash(self.ability_id) & 0xffff)

    def beam_values(self):
        return self.p("damage"), self.reach(), self.beam_width() * WIDTH_SCALE

    def beam_origin(self) -> SimVec3:
        point = scene.getRelativePoint(self.owner.pose_root, CHEST_POINT)
        return SimVec3(point.x, point.y, point.z)

    def beam_starts(self) -> tuple:
        return (self.beam_origin(),)

    def press(self) -> None:
        self.front = 0.0
        self.tracking = None
        self.engaged = False
        self.body_yaw = None
        was_on = self.active
        super().press()
        if self.active != was_on:
            self.say(f"{self.name.upper()} {'ON' if self.active else 'OFF'}")

    def keep_firing(self, target) -> bool:
        if target is not self.tracking:
            self.front = 0.0  # the stream has to cross to whoever it has turned to
            self.tracking = target
        if target is not None:
            self.engaged = True
            return True
        if self.engaged:  # it was on someone and nobody is left
            self.say("NO TARGET: BEAM OFF")
            return False
        return True  # switched on with nobody about: it goes where the camera points

    def beam_limit(self, limit: float) -> float:
        return min(limit, self.front)

    def update(self, dt: float) -> None:
        if self.active:
            self.front += self.p("speed") * dt
            self._turn_to_target(dt)
            self.owner.left_arm.rotation_x = self.owner.right_arm.rotation_x = self.ARMS_BACK
        super().update(dt)

    def _turn_to_target(self, dt: float) -> None:
        target, owner = self.tracking, self.owner
        if target is None or target.parked or target.vitals.downed:
            self.body_yaw = None
            return
        # Its own record of the turn, because normal movement turns the body to the camera every frame.
        if self.body_yaw is None:
            self.body_yaw = float(owner.local_yaw)
        dx, dz = target.x - owner.x, target.z - owner.z
        if dx * dx + dz * dz > .01:
            self.body_yaw = rotate_towards_degrees(self.body_yaw, degrees(atan2(dx, dz)), TURN_RATE * dt)
        owner.local_yaw = self.body_yaw
        self.game.planet.orient_entity(owner, SimVec3(owner.x, owner.y, owner.z), owner.local_yaw)

    def on_beam_hit(self, hit, damage, direction) -> None:
        super().on_beam_hit(hit, damage, direction)
        self.ticks += 1
        self._effects(hit)

    def _effects(self, hit) -> None:
        puffs, rng = self.combat.puffs, self.rng
        start = self.beam_origin()
        if self.ticks % GLOW_EVERY == 0:
            puffs.emit(start, SimVec3(0.0, 0.0, 0.0), self.CHEST_GLOW, size=.7, grow=.5, life=BEAM_TRACE_INTERVAL * 3.0)
        if hit.kind == "none":
            return
        spark = SimVec3(rng.uniform(-9.0, 9.0), rng.uniform(2.0, 12.0), rng.uniform(-9.0, 9.0))
        puffs.emit(hit.point, spark, self.SPARK, size=.2, grow=.2, life=.25)
        if self.ticks % STREAM_EVERY == 0:
            along = start + (hit.point - start) * rng.random()
            puffs.emit(along, SimVec3(rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0)),
                       self.STREAM, size=.4, grow=.6, life=.35)


class GoldenChestBeam(ChestBeam):
    """Sentry: golden-yellow, and hot enough to burn, melt and scorch what it touches."""

    CORE = color.rgb32(255, 248, 205)
    GLOW = color.rgba32(255, 195, 40, 130)
    FLARE = color.rgba32(255, 210, 70, 225)
    SPARK = (255, 225, 120, 235)
    STREAM = (255, 205, 60, 170)
    CHEST_GLOW = (255, 225, 110, 190)
    KIND = HEAT

    def on_beam_hit(self, hit, damage, direction) -> None:
        super().on_beam_hit(hit, damage, direction)
        self.combat.heat_effects(hit, self.owner, intensity=self.boost(.5, 2.0))


class RadioactiveChestBeam(ChestBeam):
    """Soldier Boy: green and radioactive. It breaks things, but it does not set them alight."""

    CORE = color.rgb32(225, 255, 220)
    GLOW = color.rgba32(70, 255, 90, 130)
    FLARE = color.rgba32(110, 255, 120, 225)
    SPARK = (150, 255, 140, 235)
    STREAM = (70, 240, 90, 170)
    CHEST_GLOW = (120, 255, 130, 190)
    KIND = RADIATION
    ARMS_BACK = 30.0  # he braces harder; he has no flight to hold him up
