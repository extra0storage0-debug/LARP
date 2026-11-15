"""Omni-Man: physical only. His squad, his strikes, and the charge, slam and dive the squad and AI draw on."""

from __future__ import annotations

from math import atan2, ceil, cos, degrees, pi, sin
from typing import NamedTuple

from ursina import Vec3, scene

from config.power_schema import SQUAD_ACTIVE, SQUAD_CYCLE, SQUAD_MARK, SQUAD_VILTRUMITES
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.base import Ability, Motion, land, sweep_angle
from powers.common import launch_character, press_charge
from powers.fx import Bubble, SpeedStreak
from powers.universal import (MAX_LAUNCH_SPEED, PUNCH_STYLES, HighSpeedAttack, StrikeAndBreakAway, seize, settle)
from powers.vitals import DOWNED_SECONDS, EXPLOSION, HEAT, PHYSICAL

CEILING = 490.0
SLAM_RISE = 25.0
DIVE_RISE = 120.0
MIN_RISE_SPEED = 180.0
IMPACT_STANDOFF = 3.0
LAND_MARGIN = 40.0
MAX_CRATER = 30.0
SQUAD_RETIRE_AFTER = 3.0  # a fallen member lies this long before leaving the field
SQUAD_RING = 9.0
SHOCK_RING_PUFFS = 8
# Key 4.
RUSH, FOLLOW, ASSAULT, CLOSE, BURN, GRIP, AFTERMATH = "rush", "follow", "assault", "close", "burn", "grip", "aftermath"
EXECUTION_MAX_SECONDS = 20.0  # on top of the time it takes to get there
IMPACT_REACH = 3.0
INTERCEPT_SPEED = 500.0       # or the catches would be over before they could be seen
FOLLOW_SPEED = 90.0
FOLLOW_SECONDS = .3
IMPACT_RISE = .3              # enough to stay in the air until he catches them
THROW_MAX_SECONDS = 60.0
THROW_METRES = 240.0
OBSTACLE_SHARE = .03
# All of Damage: the impacts, the squad, the fire and the landing. The blasts are for whatever else is near.
IMPACT_SHARE, SQUAD_SHARE, FIRE_SHARE, LANDING_SHARE = .2, .15, .15, .1
BLAST_SHARE = .3
ASSAULT_MIN_HEIGHT = 8.0
SQUAD_SECONDS = 3.0
SQUAD_ARRIVE_SECONDS = .2
SQUAD_ATTACK_EVERY = .2
SQUAD_STRIKE_SECONDS = .18
SQUAD_RING_RADIUS, SQUAD_STRIKE_RADIUS, SQUAD_CHARGE_RADIUS = 5.5, 2.4, 11.0
SQUAD_MOVE_SPEED = 180.0
WATCH_METRES = 14.0
SQUAD_REST_SECONDS = 1.0
SQUAD_ATTACKS = ("punch", "kick", "grapple", "charge")
SQUAD_SPARK = (255, 235, 200, 220)
IMPACT_SMOKE = (80, 72, 66, 210)
BURN_SECONDS = 1.0
GRIP_SECONDS = .25
FIRE_TICK = .1
FIRE_RADIUS_SHARE, MAX_FIRE_RADIUS = .001, 45.0
FIRE_TINT = (255, 130, 40)
FLAME = (255, 120, 30, 120)
FLAME_PUFF = (255, 150, 50, 220)
BURN_SMOKE = (70, 60, 54, 200)
SPARK_TINT = (255, 220, 120, 240)
FLAME_EVERY = .08
AFTERMATH_SECONDS = .35



class Impact(NamedTuple):
    """One of the three: its own blow, its own size of blast, and a new direction for the target."""

    arms: tuple[float, float, float]  # right arm, left arm, right leg
    turn: float                       # degrees away from the line he hit along
    radius_share: float               # of Range
    max_radius: float
    crater_depth: float
    burst: float


IMPACTS = (Impact((-170.0, 30.0, 0.0), 0.0, .1, 180.0, 6.0, 4.0),      # a straight right, at full flight speed
           Impact((-165.0, -165.0, 0.0), 120.0, .05, 90.0, 3.0, 3.0),  # both fists together
           Impact((40.0, 40.0, -85.0), 120.0, .08, 140.0, 5.0, 3.5))  # the whole body behind one knee


def impact_point_near(ability, target) -> SimVec3:
    """A safe place to land beside a target: on land, just short of them, on the ground."""
    owner = ability.owner
    game = ability.game
    offset = SimVec3(owner.x - target.x, 0.0, owner.z - target.z)
    side = offset.normalized() * IMPACT_STANDOFF if offset.length() > .1 else SimVec3()
    x, z = game.planet.clamp_to_land(target.x + side.x, target.z + side.z, LAND_MARGIN)
    return SimVec3(x, game.world.height_at(x, z) + .25, z)


class ImpactMotion(Motion):
    """Rise, then drive into a point on the ground beside the target."""

    def __init__(self, ability, point: SimVec3, target, rise_height: float) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.point = point
        self.target = target
        owner = self.owner
        self.top = min(CEILING, float(owner.y) + rise_height)
        self.rising = True
        owner.flight.phase = FlightPhase.CRUISE
        owner.flight.phase_time = 0.0

    def step(self, dt: float) -> bool:
        owner, ability = self.owner, self.ability
        speed = ability.p("speed")
        if self.rising:
            self._move(SimVec3(0.0, max(MIN_RISE_SPEED, speed * .5), 0.0), dt)
            if owner.y >= self.top:
                self.rising = False
                if self.target is not None and not self.target.vitals.downed:
                    self.point = impact_point_near(ability, self.target)
            return True
        to_point = self.point - SimVec3(owner.x, owner.y, owner.z)
        distance = to_point.length()
        if distance <= speed * dt + 1.0:
            owner.position = (self.point.x, self.point.y, self.point.z)
            land(owner)
            ability.impact()
            return False
        owner.flight.velocity = to_point.normalized() * speed
        self._move(owner.flight.velocity, dt)
        return True


class _ImpactAbility(Ability):
    RISE = SLAM_RISE

    def impact_damage(self) -> float:
        powers = self.owner.powers
        return self.p("damage") * powers.strength * powers.attack_scale

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or not owner.flight_allowed:
            return
        target = self.target()
        point = impact_point_near(self, target) if target is not None else self.fallback_point()
        owner.motion = ImpactMotion(self, point, target, self.RISE)

    def fallback_point(self) -> SimVec3:
        """Nobody in range: straight down where the character is."""
        owner = self.owner
        return SimVec3(owner.x, self.game.world.height_at(owner.x, owner.z) + .25, owner.z)

    def impact(self) -> None:
        raise NotImplementedError


class FlightCharge(Ability):
    ability_id = "flight_charge"

    def press(self) -> None:
        press_charge(self, "FLIGHT CHARGE")


class GroundSlam(_ImpactAbility):
    ability_id = "ground_slam"
    RISE = SLAM_RISE

    def impact(self) -> None:
        owner = self.owner
        radius = self.area(.1, 80.0)
        self.combat.blast(owner, SimVec3(owner.x, owner.y, owner.z), radius, self.impact_damage(),
                          self.force(40.0, 150.0), kind=EXPLOSION,
                          crater=(min(MAX_CRATER, radius * .55), 2.0, "ground-slam"), cracks=True,
                          burst_scale=1.2)


class ShockwavePunch(Ability):
    ability_id = "shockwave_punch"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.strikes = 0

    def press(self) -> None:
        if self.usable():
            self._strike()

    def reset(self) -> None:
        super().reset()
        self.strikes = 0

    def _strike(self) -> None:
        owner = self.owner
        self.strikes += 1
        owner.right_arm.rotation_x = -120.0
        powers = owner.powers
        damage = self.p("damage") * powers.strength * powers.attack_scale
        origin = center_of(owner)
        struck = self.target()
        direction = self.facing()
        if struck is not None:
            direction = (center_of(struck) - origin).normalized()
            self.combat.hit_character(owner, struck, damage, PHYSICAL, direction,
                                      self.force(40.0, 150.0))
            self.combat.burst(center_of(struck), 6.0, 1.0)
        radius = self.area(.2, 80.0)
        self.combat.blast(owner, SimVec3(owner.x, owner.y, owner.z), radius, damage * .6,
                          self.force(30.0, 120.0), kind=EXPLOSION,
                          crater=(min(MAX_CRATER, radius * .25), .7, "shockwave-punch"), cracks=True,
                          ignore=(struck,) if struck is not None else ())


class DiveBomb(_ImpactAbility):
    ability_id = "dive_bomb"
    RISE = DIVE_RISE

    def fallback_point(self) -> SimVec3:
        origin, direction = self.owner.aim_ray()
        hit = trace(self.game, origin, direction, self.reach(), ignore=(self.owner,), characters=(),
                    trees=False)
        if hit.kind == "none":
            return super().fallback_point()
        x, z = self.game.planet.clamp_to_land(hit.point.x, hit.point.z, LAND_MARGIN)
        return SimVec3(x, self.game.world.height_at(x, z) + .25, z)

    def press(self) -> None:
        had_motion = self.owner.motion
        super().press()
        if self.owner.motion is not had_motion:
            self.say("VILTRUMITE DIVE BOMB")

    def impact(self) -> None:
        owner = self.owner
        radius = self.area(.1, 120.0)
        self.combat.blast(owner, SimVec3(owner.x, owner.y, owner.z), radius, self.impact_damage(),
                          self.force(60.0, 200.0), kind=EXPLOSION,
                          crater=(min(MAX_CRATER, radius * .5), 5.0, "dive-bomb"), cracks=True,
                          burst_scale=1.8)


class SquadSummon(Ability):
    """Key 1: on until pressed again. Those chosen on the menu come for part of every cycle: by default
    five Viltrumites and Invincible, for 30 seconds in every 60.

    The same six bodies come back every time, so there can never be a second squad.
    """

    ability_id = "squad_summon"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.members: list = []
        self.called = 0
        self.cycle = 0.0
        self.summons_made = 0

    def press(self) -> None:
        if self.active:
            self.dismiss()
            self.say("SQUAD DISMISSED")
        elif self.usable():
            self.active = True
            self.cycle = 0.0
            self._call()
            self.say(f"SQUAD: {self.called} ALLIES")

    def _call(self) -> None:
        self.members = self.owner.team.deploy_squad(self.owner, round(self.p(SQUAD_VILTRUMITES)),
                                                    self.p(SQUAD_MARK) >= 1.0)
        self.called = len(self.members)
        self.summons_made += 1

    def _send_back(self) -> None:
        members, self.members = self.members, []
        if members:
            self.owner.team.withdraw_squad(members)

    def dismiss(self) -> None:
        self.active = False
        self._send_back()

    def update(self, dt: float) -> None:
        self.retire_fallen()
        if not self.active or self.combat.time_stopped or isinstance(self.owner.motion, TripleImpactExecution):
            return  # world time; and key 4 has the squad for now, and hands back the ones it brought
        self.cycle += dt
        length = self.p(SQUAD_CYCLE)
        active = min(self.p(SQUAD_ACTIVE), length)
        if self.members and active < length and self.cycle >= active:
            self._send_back()
        if self.cycle >= length:
            self.cycle %= length
            if not self.members and not self.vitals.downed:  # with no time off, the ones out just stay out
                self._call()

    def retire_fallen(self, everyone_down: bool = False) -> None:
        fallen = [member for member in self.members if member.vitals.downed
                  and (everyone_down or member.vitals.downed_for <= DOWNED_SECONDS - SQUAD_RETIRE_AFTER)]
        if not fallen:
            return
        self.members = [member for member in self.members if member not in fallen]
        self.owner.team.withdraw_squad(fallen)
        if not self.members:
            self.say("SQUAD DOWN")

    def status_line(self) -> str:
        if not self.members:
            return f"SQUAD BACK IN {ceil(self.p(SQUAD_CYCLE) - self.cycle):.0f} s"
        names = ", ".join(sorted({member.display_name for member in self.members}))
        return f"SQUAD {len(self.members)}/{self.called}: {names}"

    def cancel(self) -> None:
        """A swap, or Omni-Man going down, does not end the fight they were called to."""
        return None

    def reset(self) -> None:
        self.dismiss()
        self.cycle = 0.0
        self.summons_made = 0

    def hud_state(self) -> str:
        return f"{len(self.members)}/{self.called}" if self.active else super().hud_state()


class ShockwaveStrike(StrikeAndBreakAway):
    """His key 2: the universal strike, and the impact itself hurts everything around it."""

    RADIUS_SHARE, MAX_RADIUS = .004, 40.0   # of Range
    DAMAGE_SHARE = .35
    FORCE = (50.0, 160.0)
    BURST = 2.0
    CRATER_DEPTH = 1.5
    SPARES_TARGET = True                    # it has just had the punch

    def _connect(self) -> None:
        target = self.target
        point = center_of(target)
        super()._connect()
        ability = self.ability
        combat, world = ability.combat, ability.game.world
        radius = ability.area(self.RADIUS_SHARE, self.MAX_RADIUS)
        near_ground = point.y - world.height_at(point.x, point.z) < radius * .4
        crater = (min(MAX_CRATER, radius * .4), self.CRATER_DEPTH, "viltrumite-impact") if near_ground else None
        combat.blast(self.owner, point, radius, self.impact_damage() * self.DAMAGE_SHARE,
                     ability.force(*self.FORCE), kind=EXPLOSION, crater=crater, cracks=near_ground,
                     burst_scale=self.BURST, ignore=(target,) if self.SPARES_TARGET else ())
        world._terrain_rebuild_wait = 0.0  # world time is stopped, but this should show now
        tint = (*self.style.flash, 210)
        for index in range(SHOCK_RING_PUFFS):
            angle = 2.0 * pi * index / SHOCK_RING_PUFFS
            combat.puffs.emit(point, SimVec3(sin(angle) * radius * 2.5, 2.0, cos(angle) * radius * 2.5), tint,
                              size=2.0, grow=radius * .3, life=.5)


class ShockwaveAttack(HighSpeedAttack):
    strike = ShockwaveStrike


class TripleImpactExecution(Motion):
    """Key 4: three separate impacts, a three-second squad assault, then fire and one great throw.

    The body only ever flies; the target is thrown between impacts by the same launch every thrown
    body uses, and is simply caught again in the air before it can come down.
    """

    def __init__(self, ability, target) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.target = target
        self.phase = RUSH
        self.phase_time = 0.0
        self.impacts = 0
        self.impact_points: list = []
        self.throw_directions: list = []
        self.holding = False
        self.thrown = False
        self.was_flying = self.owner.flight.is_flying
        self.squad: list = []
        self.temporary: list = []
        self.anchor = SimVec3()
        self.squad_hits = 0
        self.attack = None
        self.attack_timer = 0.0
        self.attack_index = 0
        self.fire_timer = 0.0
        self.fire_stored = 0.0
        self.fire_dealt = 0.0
        self.streak = SpeedStreak(ability.combat, PUNCH_STYLES[ability.owner.character_id].trail)
        away = (center_of(target) - center_of(self.owner)).length()
        self.time_limit = EXECUTION_MAX_SECONDS + away / max(1.0, ability.p("speed"))
        self.owner.flight.phase = FlightPhase.CRUISE
        self.owner.flight.phase_time = 0.0
        # World time is stopped, but what this sets off has to play out, not hang on screen.
        self.frozen_bursts = set(ability.game.world._active_explosions)
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

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        self.phase_time += dt
        ability, owner, target = self.ability, self.owner, self.target
        for burst in tuple(ability.game.world._active_explosions):
            if ability.combat.time_stopped and burst not in self.frozen_bursts:  # a running world steps its own
                burst.step(dt)
        if self.phase != AFTERMATH:
            if self._target_gone() or self.elapsed > self.time_limit:
                self._let_go()
                self._enter(AFTERMATH)
                return True
            dx, dz = float(target.x) - float(owner.x), float(target.z) - float(owner.z)
            if dx * dx + dz * dz > .01:
                self.facing = degrees(atan2(dx, dz))
            if self.holding:
                target.vitals.add_status("held", .2)
            if owner.controlled:  # it all happens a long way apart, and the player has to see it
                ability.game.camera._track_lock(center_of(target), dt)
        return getattr(self, f"_step_{self.phase}")(dt)

    def _fly_at_target(self, speed: float, dt: float) -> bool:
        """Close on the target wherever it has got to, through whatever is in the way."""
        ability, owner = self.ability, self.owner
        offset = center_of(self.target) - center_of(owner)
        left = offset.length() - IMPACT_REACH
        if left <= .05:
            self.streak.release()
            return True
        direction = offset.normalized()
        step = min(speed * dt, left)
        hit = trace(ability.game, center_of(owner), direction, step + 1.0, ignore=(owner, self.target),
                    characters=(), terrain=False)
        if hit.kind in ("object", "tree"):
            ability.combat.damage_hit(owner, hit, self._total_damage() * OBSTACLE_SHARE, direction,
                                      kind=PHYSICAL, force=20.0)
        velocity = direction * (step / max(dt, 1e-4))
        self._move(velocity, dt)
        owner.flight.velocity = velocity
        self.streak.show(center_of(owner), velocity)
        # Within this frame's reach counts as there: a target still moving would otherwise stay a step ahead.
        if left <= speed * dt:
            self.streak.release()
            return True
        return False

    # -- the three impacts -----------------------------------------------
    def _step_rush(self, dt: float) -> bool:
        speed = self.ability.p("speed")
        if self.impacts:  # after the first he has to find them again, and it has to be seen
            speed = min(speed, INTERCEPT_SPEED)
        if self._fly_at_target(speed, dt):
            self._impact()
        return True

    def _impact(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat, world = ability.combat, ability.game.world
        pose = IMPACTS[self.impacts]
        self.impacts += 1
        total = self._total_damage()
        point = center_of(target)
        self.impact_points.append(point)
        owner.flight.velocity = SimVec3()
        owner.right_arm.rotation_x, owner.left_arm.rotation_x, owner.right_leg.rotation_x = pose.arms
        combat.hit_character(owner, target, total * IMPACT_SHARE, PHYSICAL)
        radius = ability.area(pose.radius_share, pose.max_radius)
        near_ground = point.y - world.height_at(point.x, point.z) < radius * .4
        crater = (min(MAX_CRATER, radius * .3), pose.crater_depth, "viltrumite-impact") if near_ground else None
        combat.blast(owner, point, radius, total * BLAST_SHARE, ability.force(80.0, 180.0), kind=EXPLOSION,
                     crater=crater, cracks=near_ground, burst_scale=pose.burst, ignore=(target,))
        world._terrain_rebuild_wait = 0.0  # world time is stopped, but this should show now
        for index in range(SHOCK_RING_PUFFS):
            angle = 2.0 * pi * index / SHOCK_RING_PUFFS
            combat.puffs.emit(point, SimVec3(sin(angle) * radius * 1.5, 3.0, cos(angle) * radius * 1.5),
                              (*PUNCH_STYLES["GREEN"].flash, 210) if index % 2 else IMPACT_SMOKE,
                              size=2.5, grow=radius * .2, life=.6)
        ability.game.camera_impulse = max(ability.game.camera_impulse, 2.5)
        ability.game.world.play_power_sound(.9)
        flat = SimVec3(float(target.x) - float(owner.x), 0.0, float(target.z) - float(owner.z))
        flat = flat.normalized() if flat.length() > 1e-3 else ability.facing()
        turned = sweep_angle(flat, pose.turn)
        direction = SimVec3(turned.x, IMPACT_RISE, turned.z).normalized()
        self.throw_directions.append(direction)
        if not target.vitals.downed:
            launch_character(owner, target, direction * min(MAX_LAUNCH_SPEED, ability.p("speed")))
            target.motion.max_seconds = THROW_MAX_SECONDS
        self._enter(FOLLOW)

    def _step_follow(self, dt: float) -> bool:
        """He carries on through the impact, while the target flies, and then turns after it."""
        owner = self.owner
        direction = self.throw_directions[-1]
        carry = direction * (FOLLOW_SPEED * max(0.0, 1.0 - self.phase_time / FOLLOW_SECONDS))
        self._move(carry, dt)
        owner.flight.velocity = carry
        if self.phase_time >= FOLLOW_SECONDS:
            owner.right_arm.rotation_x = owner.left_arm.rotation_x = owner.right_leg.rotation_x = 0.0
            if self.impacts < len(IMPACTS):
                self._enter(RUSH)
            else:
                self._begin_assault()
        return True

    # -- the squad --------------------------------------------------------
    def _begin_assault(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        game = ability.game
        target.release_motion()
        floor = game.world.height_at(float(target.x), float(target.z)) + ASSAULT_MIN_HEIGHT
        self.anchor = SimVec3(float(target.x), max(floor, float(target.y)), float(target.z))
        target.position = (self.anchor.x, self.anchor.y, self.anchor.z)
        target.flight.velocity = SimVec3()
        target.knock = SimVec3()
        target.jump_height = target.jump_velocity = 0.0
        self.holding = True
        target.vitals.add_status("held", .2)
        owner.flight.velocity = SimVec3()
        # A squad he already called stays his; only what is missing is brought in, and only for now.
        summon = owner.powers.abilities["squad_summon"]
        summon.retire_fallen(everyone_down=True)
        self.temporary = owner.team.deploy_squad(target)
        self.squad = [member for member in owner.team.summons if not member.parked]
        for member in self.squad:
            member.release_motion()
            member._end_ai_move()
            member.flight.phase = FlightPhase.CRUISE
            member.flight.velocity = SimVec3()
            member.ai_target = None
        game.world.play_power_sound(.5)
        self.attack_timer = SQUAD_ARRIVE_SECONDS
        self._enter(ASSAULT)

    def _ring_point(self, index: int, radius: float) -> SimVec3:
        angle = 2.0 * pi * index / max(1, len(self.squad))
        return self.anchor + SimVec3(sin(angle) * radius, (index % 3 - 1) * 1.1, cos(angle) * radius)

    def _place_member(self, member, point: SimVec3, dt: float, speed: float) -> None:
        here = SimVec3(float(member.x), float(member.y), float(member.z))
        offset = point - here
        distance = offset.length()
        moved = point if distance <= speed * dt else here + offset * (speed * dt / distance)
        member.position = (moved.x, moved.y, moved.z)
        dx, dz = self.anchor.x - moved.x, self.anchor.z - moved.z
        if dx * dx + dz * dz > .01:
            member.local_yaw = degrees(atan2(dx, dz))
        self.ability.game.planet.orient_entity(member, moved, member.local_yaw)

    def _step_assault(self, dt: float) -> bool:
        """Exactly three seconds. One attacker at a time comes in, from wherever they are in the ring."""
        ability, target = self.ability, self.target
        self._stand_off(dt)
        attacker = self.attack[0] if self.attack is not None else None
        for index, member in enumerate(self.squad):
            if member is not attacker and not member.parked:
                self._place_member(member, self._ring_point(index, SQUAD_RING_RADIUS), dt, SQUAD_MOVE_SPEED)
        self.attack_timer -= dt
        if self.attack is not None:
            self._step_attack(dt)
        if self.attack is None and self.attack_timer <= 0.0 and self.squad:
            self.attack_index += 1
            index = self.attack_index % len(self.squad)
            self.attack = [self.squad[index], self.attack_index % len(SQUAD_ATTACKS), index, 0.0, False]
            self.attack_timer = SQUAD_ATTACK_EVERY
        # It rocks under the blows and settles back, and it never drifts away from where they are.
        here = SimVec3(float(target.x), float(target.y), float(target.z))
        settled = here + (self.anchor - here) * min(1.0, dt * 9.0)
        target.position = (settled.x, settled.y, settled.z)
        target.pose_root.setP(sin(self.phase_time * 19.0) * 16.0)
        if self.phase_time >= SQUAD_SECONDS:
            self._end_assault()
            self._enter(CLOSE)
            ability.game.world.play_power_sound(.4)
        return True

    def _stand_off(self, dt: float) -> None:
        """He comes back to watch from nearby, clear of the ring."""
        owner = self.owner
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        away = here - self.anchor
        spot = self.anchor + (away.normalized() if away.length() > 1e-3 else self.ability.facing()) * WATCH_METRES
        offset = spot - here
        distance = offset.length()
        if distance > .1:
            step = min(INTERCEPT_SPEED * dt, distance)
            self._move(offset * (step / distance / max(dt, 1e-4)), dt)
        owner.flight.velocity = SimVec3()

    def _step_attack(self, dt: float) -> None:
        ability, target = self.ability, self.target
        member, kind, index, age, landed = self.attack
        if member.parked:
            self.attack = None
            return
        age += dt
        self.attack[3] = age
        progress = min(1.0, age / SQUAD_STRIKE_SECONDS)
        reach = sin(progress * pi)  # in and back out, so nobody ends up inside anybody
        start = SQUAD_CHARGE_RADIUS if SQUAD_ATTACKS[kind] == "charge" else SQUAD_RING_RADIUS
        self._place_member(member, self._ring_point(index, start + (SQUAD_STRIKE_RADIUS - start) * reach), dt, 400.0)
        name = SQUAD_ATTACKS[kind]
        if name == "kick":
            member.left_leg.rotation_x = -80.0 * reach
        elif name == "grapple":
            member.left_arm.rotation_x = member.right_arm.rotation_x = -130.0 * reach
        else:
            member.right_arm.rotation_x = -150.0 * reach
        if not landed and progress >= .5:
            self.attack[4] = True
            self.squad_hits += 1
            combat = ability.combat
            away = (center_of(target) - center_of(member)).normalized()
            combat.hit_character(self.owner, target, self._total_damage() * SQUAD_SHARE
                                 * SQUAD_ATTACK_EVERY / SQUAD_SECONDS, PHYSICAL)
            target.position = (float(target.x) + away.x * .6, float(target.y) + away.y * .6, float(target.z) + away.z * .6)
            combat.puffs.emit(center_of(target) - away * 1.0, SimVec3(0.0, 2.0, 0.0), SQUAD_SPARK, size=.8, grow=2.5,
                              life=.22)
            ability.game.camera_impulse = max(ability.game.camera_impulse, .35)
            ability.game.world.play_power_sound(.3)
        if progress >= 1.0:
            member.left_leg.rotation_x = member.left_arm.rotation_x = member.right_arm.rotation_x = 0.0
            self.attack = None

    def _end_assault(self) -> None:
        for index, member in enumerate(self.squad):
            if not member.parked:
                member.left_leg.rotation_x = member.left_arm.rotation_x = member.right_arm.rotation_x = 0.0
                member._ai_next_attack = self.ability.game.elapsed + SQUAD_REST_SECONDS + index * .2
        self.attack = None
        team = self.owner.team
        temporary, self.temporary = [member for member in self.temporary if not member.parked], []
        if temporary:
            team.withdraw_squad(temporary)

    # -- fire and the throw -----------------------------------------------
    def _step_close(self, dt: float) -> bool:
        ability, target = self.ability, self.target
        if self._fly_at_target(min(ability.p("speed"), INTERCEPT_SPEED), dt):
            combat = ability.combat
            point = center_of(target)
            owner = self.owner
            owner.flight.velocity = SimVec3()
            owner.right_arm.rotation_x = -170.0
            total = self._total_damage()
            radius = ability.area(FIRE_RADIUS_SHARE, MAX_FIRE_RADIUS)
            combat.blast(owner, point, radius, total * BLAST_SHARE, ability.force(40.0, 120.0), kind=HEAT,
                         ignore=(target,), burst_scale=3.0, tint=FIRE_TINT)
            ground = SimVec3(point.x, ability.game.world.height_at(point.x, point.z), point.z)
            if point.y - ground.y < radius:  # the blast reaches the ground, so the ground burns
                combat.elements.add_scorch(ground, radius * .4)
                combat.elements.start_fire(ground, owner)
            ability.game.camera_impulse = max(ability.game.camera_impulse, 2.0)
            ability.game.world.play_power_sound(.8)
            self.fire_timer = 0.0
            self._enter(BURN)
        return True

    def _burn_visuals(self, dt: float) -> None:
        ability = self.ability
        center = center_of(self.target)
        flames = ability.flames
        flames.entity.position = Vec3(center.x, center.y, center.z)
        flames.show(5.5 + sin(self.elapsed * 15.0) * .9, FLAME)
        puffs = ability.combat.puffs
        if int(self.elapsed / FLAME_EVERY) != int((self.elapsed - dt) / FLAME_EVERY):
            angle = self.elapsed * 11.0
            at = center + SimVec3(sin(angle) * 1.3, -.8, cos(angle) * 1.3)
            puffs.emit(at, SimVec3(0.0, 10.0, 0.0), FLAME_PUFF if int(self.elapsed * 10) % 2 else BURN_SMOKE,
                       size=1.0, grow=3.0, life=.55)
            puffs.emit(at, SimVec3(sin(angle) * 8.0, 6.0, cos(angle) * 8.0), SPARK_TINT, size=.25, grow=.2, life=.35)

    def _step_burn(self, dt: float) -> bool:
        ability, target = self.ability, self.target
        self._burn_visuals(dt)
        self.fire_stored += self._total_damage() * FIRE_SHARE / BURN_SECONDS * dt
        self.fire_timer -= dt
        if self.fire_timer <= 0.0:
            self.fire_timer = FIRE_TICK
            self.fire_dealt += ability.combat.hit_character(self.owner, target, self.fire_stored, HEAT)
            self.fire_stored = 0.0
            if target.vitals.downed:
                return True  # step() ends it next frame
        if self.phase_time >= BURN_SECONDS:
            self.owner.right_arm.rotation_x = self.owner.left_arm.rotation_x = -150.0
            self._enter(GRIP)
        return True

    def _step_grip(self, dt: float) -> bool:
        self._burn_visuals(dt)
        if self.phase_time >= GRIP_SECONDS:
            self._throw()
        return True

    def _throw(self) -> None:
        """Hard at a spot on the ground a long way off, so that it arrives with real force."""
        ability, owner, target = self.ability, self.owner, self.target
        game = ability.game
        flat = SimVec3(float(target.x) - float(owner.x), 0.0, float(target.z) - float(owner.z))
        flat = flat.normalized() if flat.length() > 1e-3 else ability.facing()
        x, z = game.planet.clamp_to_land(float(target.x) + flat.x * THROW_METRES, float(target.z) + flat.z * THROW_METRES,
                                         40.0)
        aim = SimVec3(x, game.world.height_at(x, z), z) - SimVec3(float(target.x), float(target.y), float(target.z))
        target.vitals.clear_status("held")
        launch_character(owner, target, aim.normalized() * MAX_LAUNCH_SPEED,
                         self._total_damage() * LANDING_SHARE)
        target.motion.max_seconds = THROW_MAX_SECONDS
        target.motion.hard_landing_speed = 0.0  # the landing always counts
        self.holding = False
        self.thrown = True
        owner.right_arm.rotation_x = 45.0
        game.camera_impulse = max(game.camera_impulse, 3.0)
        game.world.play_power_sound(.7)
        self._enter(AFTERMATH)

    def _step_aftermath(self, dt: float) -> bool:
        return self.phase_time < AFTERMATH_SECONDS

    # -- leaving everything as it was ------------------------------------
    def _let_go(self) -> None:
        target = self.target
        target.vitals.clear_status("held")
        if self.holding and not self.thrown and not target.parked:
            launch_character(self.owner, target, SimVec3())
        self.holding = False
        self.thrown = True
        self.streak.release()

    def finish(self) -> None:
        """Runs however this ends, even a character switch: time always resumes, the squad goes back."""
        owner, target, ability = self.owner, self.target, self.ability
        self._let_go()
        self._end_assault()
        ability.flames.hide()
        if not target.vitals.downed and target.motion is None:
            target.pose_root.setP(0.0)
        owner.right_arm.rotation_x = owner.left_arm.rotation_x = owner.right_leg.rotation_x = 0.0
        owner.knock = SimVec3()
        ability.combat.end_time_stop(owner)
        settle(owner, self.was_flying)


class SpeedExecution(Ability):
    ability_id = "speed_execution"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.flames = Bubble(scene, FLAME, center=0.0)

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or not owner.flight_allowed \
                or self.combat.sequence_running:
            return  # one already running is a motion, so it can never start twice
        target = self.target()
        if target is None:
            self.say("NO ENEMY IN RANGE")
            return
        seize(owner, target)
        owner.motion = TripleImpactExecution(self, target)
        self.say("TIME STOPPED")

    def hud_state(self) -> str:
        return "ON" if isinstance(self.owner.motion, TripleImpactExecution) else super().hud_state()


__all__ = ["DiveBomb", "ShockwaveAttack", "ShockwaveStrike", "SpeedExecution", "SquadSummon", "TripleImpactExecution", "FlightCharge", "GroundSlam", "ImpactMotion", "ShockwavePunch", "center_of"]
