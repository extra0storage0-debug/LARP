"""Keys 2, 3 and T for Superman, Homelander, Sentry and Omni-Man: the same for each of them.

Keys 2 and 3 run with the world stopped: only the attacker and the target are in time until the
sequence ends, and the target's flight carries on from there when everything else resumes.
"""

from __future__ import annotations

from characters.registry import definitions

from math import atan2, cos, degrees, pi, sin
from typing import NamedTuple

from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.base import Ability, Motion
from powers.common import RamMotion, launch_character
from powers.fx import SpeedStreak
from powers.vitals import EXPLOSION, PHYSICAL

STRIKE_MAX_SECONDS = 6.0
PUNCH_RISE = .28            # how steeply a punch sends someone up into the air
MAX_LAUNCH_SPEED = 600.0
LANDING_DAMAGE_SHARE = .1
SHOCKWAVE_RADIUS = 14.0
SHOCKWAVE_PUFFS = 8
TRAIL_INTERVAL = .03
BREAK_AWAY_SECONDS = .35
BREAK_AWAY_MIN_SPEED = 220.0
GRAB_DISTANCE = 3.0
NECK_HEIGHT = .55          # lifted by the neck: feet off the ground, head at the attacker's hand
RUSH, GRIP, RISE, CARRY, PUNCH, AFTERMATH = "rush", "grip", "rise", "carry", "punch", "aftermath"
SEQUENCE_MAX_SECONDS = 8.0
GRIP_SECONDS = .12
CARRY_FROM_HEIGHT = 30.0   # started near the ground, there must be somewhere to drive them down from
RISE_SPEED = 150.0
MAX_CARRY_SPEED = 600.0
OBSTACLE_DAMAGE_SHARE = .05
PUNCH_WINDUP_SECONDS = .25
AFTERMATH_SECONDS = .3
PUNCH_DAMAGE_SHARE = .5    # the rest is the explosion's, which also reaches anyone else nearby
NUCLEAR_RADIUS_SHARE = .1  # of Range
MAX_NUCLEAR_RADIUS = 220.0
MAX_NUCLEAR_CRATER = 40.0
NUCLEAR_CRATER_DEPTH = 10.0
NUCLEAR_SMOKE_PUFFS = 12
NUCLEAR_THROW_RISE = .6


def settle(owner, was_flying: bool) -> None:
    """Hand back to the player as they were: someone who started on the ground comes back down."""
    if not was_flying and owner.flight.is_flying:
        owner.flight.phase = FlightPhase.LANDING
        owner.flight.phase_time = 0.0


class PunchStyle(NamedTuple):
    """How one character's punch looks. What it does is the same for all four."""

    trail: tuple[int, int, int, int]
    flash: tuple[int, int, int]
    right_arm: float  # arm rotation at the moment of impact
    left_arm: float


PUNCH_STYLES = {item.character_id: PunchStyle(*item.punch) for item in definitions()}


class StrikeAndBreakAway(RamMotion):
    """Charge the target, land one huge punch that launches them, and carry on past them."""

    def __init__(self, ability, target) -> None:
        self.was_flying = ability.owner.flight.is_flying
        super().__init__(ability)
        self.target = target
        ability.combat.begin_time_stop(self.owner, target)
        self.style = PUNCH_STYLES[self.owner.character_id]
        self.streak = SpeedStreak(ability.combat, self.style.trail)
        self.trail_timer = 0.0
        self.away = None
        self.away_left = 0.0
        self.owner.right_arm.rotation_x = self.style.right_arm * .4
        self.owner.left_arm.rotation_x = self.style.left_arm * .4

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        if self.away is not None:
            self.away_left -= dt
            self._move(self.away, dt)
            self.owner.flight.velocity = self.away
            self._draw_speed(self.away, dt)
            return self.away_left > 0.0
        target = self.target
        if (target.vitals.downed or target.parked or self.elapsed > STRIKE_MAX_SECONDS
                or not self.ability.combat.hostile(self.owner, target)):
            return False
        if super().step(dt):
            self._draw_speed(self.direction * self.speed, dt)
            return True
        if not self.struck:
            return False
        self._connect()
        return True

    def _draw_speed(self, velocity: SimVec3, dt: float) -> None:
        here = center_of(self.owner)
        self.streak.show(here, velocity)
        self.trail_timer -= dt
        if self.trail_timer <= 0.0:
            self.trail_timer = TRAIL_INTERVAL
            self.ability.combat.puffs.emit(here, SimVec3(0.0, 0.0, 0.0), self.style.trail, size=1.2,
                                           grow=1.5, life=.3)

    def _connect(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat, style = ability.combat, self.style
        forward = SimVec3(self.direction.x, 0.0, self.direction.z)
        forward = forward.normalized() if forward.length() > 1e-3 else ability.facing()
        if not target.is_evading:
            launch_character(owner, target,
                             (forward + SimVec3(0.0, PUNCH_RISE, 0.0)).normalized()
                             * min(MAX_LAUNCH_SPEED, self.speed),
                             self.impact_damage() * LANDING_DAMAGE_SHARE)
        point = center_of(target)
        combat.burst(point, SHOCKWAVE_RADIUS, 1.6, style.flash)
        for index in range(SHOCKWAVE_PUFFS):
            angle = 2.0 * pi * index / SHOCKWAVE_PUFFS
            combat.puffs.emit(point, SimVec3(sin(angle) * 45.0, 0.0, cos(angle) * 45.0),
                              (*style.flash, 200), size=1.0, grow=4.0, life=.35)
        ability.game.camera_impulse = max(ability.game.camera_impulse, 2.0)
        ability.game.world.play_power_sound(.7)
        owner.right_arm.rotation_x = style.right_arm
        owner.left_arm.rotation_x = style.left_arm
        # Straight on, over and to one side of them, so nobody ends up inside anybody.
        side = SimVec3(forward.z, 0.0, -forward.x)
        self.away = (forward + SimVec3(0.0, .55, 0.0) + side * .35).normalized() * max(BREAK_AWAY_MIN_SPEED,
                                                                                       self.speed * .4)
        self.away_left = BREAK_AWAY_SECONDS

    def finish(self) -> None:
        super().finish()
        self.streak.release()
        self.owner.right_arm.rotation_x = self.owner.left_arm.rotation_x = 0.0
        self.ability.combat.end_time_stop(self.owner)
        settle(self.owner, self.was_flying)


def seize(owner, target) -> None:
    """Whatever the target was doing ends now; it is about to be moved by someone else."""
    target.powers.cancel_all()
    target.release_motion()
    target.knock = SimVec3()
    target.jump_velocity = target.jump_height = 0.0
    vision = owner.powers.abilities.get("kryptonian_vision")
    if vision is not None:
        vision.cancel()


class HighSpeedAttack(Ability):
    ability_id = "high_speed_attack"
    strike = StrikeAndBreakAway

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or not owner.flight_allowed:
            return
        target = self.target()
        if target is None:
            self.say("NO ENEMY IN RANGE")
            return
        seize(owner, target)
        owner.motion = self.strike(self, target)
        self.say("TIME STOPPED")

    def hud_state(self) -> str:
        return "ON" if type(self.owner.motion) is self.strike else super().hud_state()


class WorldTimeStop(Ability):
    """T: the world stops for exactly 30 seconds and the player carries on. It has no values."""

    ability_id = "world_stop"

    def press(self) -> None:
        if self.usable() and self.owner.controlled and self.combat.begin_world_stop():
            self.say("TIME STOPPED")

    def hud_state(self) -> str:
        return "ON" if self.combat.world_stopped else super().hud_state()


class NuclearExecution(Motion):
    """Key 3: rush, take them by the neck, drive them into the ground, one punch, one huge explosion."""

    def __init__(self, ability, target) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.target = target
        self.style = PUNCH_STYLES[self.owner.character_id]
        self.phase = RUSH
        self.phase_time = 0.0
        self.was_flying = self.owner.flight.is_flying
        self.grabbed = False
        self.thrown = False
        self.top = 0.0
        self.detonated_at = None
        self.streak = SpeedStreak(ability.combat, self.style.trail)
        self.owner.flight.phase = FlightPhase.CRUISE
        self.owner.flight.phase_time = 0.0
        ability.combat.begin_time_stop(self.owner, target)

    def _enter(self, phase: str) -> None:
        self.phase = phase
        self.phase_time = 0.0

    def _target_gone(self) -> bool:
        target = self.target
        return (target.parked or target.vitals.downed
                or not self.ability.combat.hostile(self.owner, target))

    def _total_damage(self) -> float:
        powers = self.owner.powers
        return self.ability.p("damage") * powers.strength * powers.attack_scale

    def _hold_by_the_neck(self) -> None:
        owner, target = self.owner, self.target
        offset = SimVec3(target.x - owner.x, 0.0, target.z - owner.z)
        side = offset.normalized() if offset.length() > 1e-3 else self.ability.facing()
        x, z = owner.x + side.x * GRAB_DISTANCE, owner.z + side.z * GRAB_DISTANCE
        floor = self.ability.game.world.height_at(x, z) + .25
        target.position = (x, max(floor, owner.y + NECK_HEIGHT), z)
        target.vitals.add_status("held", .2)
        owner.right_arm.rotation_x = -150.0

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        self.phase_time += dt
        owner, target = self.owner, self.target
        if self.phase != AFTERMATH:
            if self._target_gone() or self.elapsed > SEQUENCE_MAX_SECONDS:
                return False
            self.facing = degrees(atan2(target.x - owner.x, target.z - owner.z))
        return getattr(self, f"_step_{self.phase}")(dt)

    def _clear_the_way(self, direction: SimVec3, length: float) -> None:
        """Anything in the way takes the hit; the sequence goes on through or past it."""
        ability, owner = self.ability, self.owner
        hit = trace(ability.game, center_of(owner), direction, length + 1.0, ignore=(owner, self.target),
                    characters=(), terrain=False)
        if hit.kind in ("object", "tree"):
            ability.combat.damage_hit(owner, hit, self._total_damage() * OBSTACLE_DAMAGE_SHARE, direction,
                                      kind=PHYSICAL, force=20.0)

    def _step_rush(self, dt: float) -> bool:
        ability, owner, target = self.ability, self.owner, self.target
        origin = center_of(owner)
        offset = center_of(target) - origin
        distance = offset.length()
        # The margin matters: flying to exactly the grab distance can stop a rounding error short.
        if distance <= GRAB_DISTANCE + .05:
            self.streak.release()
            self.grabbed = True
            target.pose_root.setP(18.0)
            ability.game.world.play_power_sound(.35)
            self._enter(GRIP)
            return True
        direction = offset.normalized()
        step = min(ability.p("speed") * dt, distance - GRAB_DISTANCE)
        self._clear_the_way(direction, step)
        velocity = direction * (step / max(dt, 1e-4))
        self._move(velocity, dt)
        owner.flight.velocity = velocity
        here = center_of(owner)
        self.streak.show(here, velocity)
        return True

    def _step_grip(self, dt: float) -> bool:
        self._hold_by_the_neck()
        self.owner.flight.velocity = SimVec3()
        if self.phase_time >= GRIP_SECONDS:
            ground = self.ability.game.world.height_at(self.owner.x, self.owner.z)
            self.top = min(float(self.ability.game.planet.MAX_FLIGHT_ALTITUDE),
                           max(float(self.owner.y), ground + CARRY_FROM_HEIGHT))
            self._enter(RISE)
        return True

    def _step_rise(self, dt: float) -> bool:
        owner = self.owner
        if owner.y >= self.top:
            target = self.target
            target.pose_root.setP(-60.0)
            self._enter(CARRY)
            return True
        speed = min(RISE_SPEED, self.ability.p("speed"))
        self._move(SimVec3(0.0, speed, 0.0), dt)
        owner.flight.velocity = SimVec3(0.0, speed, 0.0)
        self._hold_by_the_neck()
        return True

    def _step_carry(self, dt: float) -> bool:
        ability, owner = self.ability, self.owner
        speed = min(MAX_CARRY_SPEED, ability.p("speed"))
        floor = ability.game.world.height_at(owner.x, owner.z) + .25
        if float(owner.y) > floor + 1e-3:
            self._clear_the_way(SimVec3(0.0, -1.0, 0.0), speed * dt)
            self._move(SimVec3(0.0, -speed, 0.0), dt)
            owner.flight.velocity = SimVec3(0.0, -speed, 0.0)
            self._hold_by_the_neck()
            here = center_of(owner)
            self.streak.show(here, SimVec3(0.0, -speed, 0.0))
            return True
        self.streak.release()
        owner.flight.velocity = SimVec3()
        self._hold_by_the_neck()
        self._ground_impact()
        owner.y = ability.game.world.height_at(owner.x, owner.z) + .25  # down into the crater just made
        self._hold_by_the_neck()
        self._enter(PUNCH)
        return True

    def _ground_impact(self) -> None:
        """The first blow: into the ground, still held. It leaves a mark; the punch does the damage."""
        ability, target = self.ability, self.target
        combat = ability.combat
        point = SimVec3(float(target.x), float(target.y), float(target.z))
        target.pose_root.setP(-82.0)
        ability.game.world.terrain_impact(point, radius=8.0, depth=1.5, intensity=1.0, surface="execution")
        combat.burst(point, 10.0, 1.2)
        combat.puffs.emit(point, SimVec3(0.0, 8.0, 0.0), (190, 170, 140, 220), size=2.0, grow=9.0, life=.7)
        ability.game.camera_impulse = max(ability.game.camera_impulse, 1.5)
        ability.game.world.play_power_sound(.6)

    def _step_punch(self, dt: float) -> bool:
        owner = self.owner
        self._hold_by_the_neck()
        owner.left_arm.rotation_x = 45.0  # drawn back
        if self.phase_time >= PUNCH_WINDUP_SECONDS:
            self._detonate()
            self._enter(AFTERMATH)
        return True

    def _detonate(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        total = self._total_damage()
        point = SimVec3(float(target.x), float(target.y), float(target.z))
        self.detonated_at = point
        owner.left_arm.rotation_x = -170.0
        target.vitals.clear_status("held")
        combat.hit_character(owner, target, total * PUNCH_DAMAGE_SHARE, PHYSICAL)
        radius = ability.area(NUCLEAR_RADIUS_SHARE, MAX_NUCLEAR_RADIUS)
        combat.blast(owner, point, radius, total * (1.0 - PUNCH_DAMAGE_SHARE), ability.force(80.0, 180.0),
                     kind=EXPLOSION, crater=(min(MAX_NUCLEAR_CRATER, radius * .4), NUCLEAR_CRATER_DEPTH, "nuclear"),
                     burst_scale=4.0)
        for index in range(NUCLEAR_SMOKE_PUFFS):  # the first ring of the shockwave, and rising smoke
            angle = 2.0 * pi * index / NUCLEAR_SMOKE_PUFFS
            combat.puffs.emit(point + SimVec3(0.0, 1.0, 0.0),
                              SimVec3(sin(angle) * 70.0, 6.0 + (index % 3) * 10.0, cos(angle) * 70.0),
                              (*self.style.flash, 210) if index % 2 else (80, 72, 66, 210), size=3.0,
                              grow=14.0, life=.9)
        ability.game.camera_impulse = max(ability.game.camera_impulse, 3.0)
        side = SimVec3(target.x - owner.x, 0.0, target.z - owner.z)
        side = side.normalized() if side.length() > 1e-3 else ability.facing()
        launch_character(owner, target, (side + SimVec3(0.0, NUCLEAR_THROW_RISE, 0.0)).normalized()
                         * min(MAX_LAUNCH_SPEED, ability.p("speed")))
        self.thrown = True

    def _step_aftermath(self, dt: float) -> bool:
        self.owner.flight.velocity = SimVec3()
        return self.phase_time < AFTERMATH_SECONDS

    def finish(self) -> None:
        """Runs however this ends: the target is let go and falls, and time always resumes."""
        owner, target = self.owner, self.target
        self.streak.release()
        target.vitals.clear_status("held")
        if self.grabbed and not self.thrown and not target.parked:
            launch_character(owner, target, SimVec3())
        elif not self.grabbed and not target.vitals.downed:
            target.pose_root.setP(0.0)
        owner.left_arm.rotation_x = owner.right_arm.rotation_x = 0.0
        self.ability.combat.end_time_stop(owner)
        settle(owner, self.was_flying)


class TimeStopNuclearExecution(Ability):
    ability_id = "time_stop"

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or not owner.flight_allowed:
            return  # one already running is a motion, so it can never start twice
        target = self.target()
        if target is None:
            self.say("NO ENEMY IN RANGE")
            return
        seize(owner, target)
        owner.motion = NuclearExecution(self, target)
        self.say("TIME STOPPED")

    def hud_state(self) -> str:
        return "ON" if isinstance(self.owner.motion, NuclearExecution) else super().hud_state()
