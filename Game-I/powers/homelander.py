"""Homelander: lasers, aerial charge, senses, Laser Overdrive and the aerial laser execution."""

from __future__ import annotations

from math import atan2, cos, degrees, floor, pi, sin
from random import Random

from ai.enemy_team_ai import CEILING
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, line_blocked_by_zinc, trace
from powers.base import Ability, BEAM_TRACE_INTERVAL, BeamAbility, Motion, sweep_angle
from powers.common import HurledDown, ground_blast, launch_character, press_charge
from powers.fx import Bubble, SpeedStreak
from powers.universal import settle
from powers.vitals import HEAT, PHYSICAL

FOCUSED, SWEEPING = "FOCUSED", "SWEEPING"
MOVING_SPEED = 2.0
SWEEP_DAMAGE_SHARE = .45
SWEEP_WIDTH_SCALE = 2.0
SWEEP_ARC = 30.0
SWEEP_SPEED = 120.0
OVERDRIVE_RANGE_SCALE = 2.0
IMPACT_INTERVAL = .35
RUSH, LIFT, LASER, CLONES, REGRAB, JUGGLE, FALL, AFTER = ("rush", "lift", "laser", "clones", "regrab", "juggle", "fall",
                                                          "after")
LASER_SECONDS = 4.0
CLONE_COUNT = 4
CLONE_SECONDS = 3.0
JUGGLE_SECONDS = 2.0
CLONE_ATTACK_SECONDS = .6
CLONE_RING, CLONE_STRIKE = 7.0, 2.2
CLONE_ATTACKS = ("punch", "kick", "aerial", "punch")
WATCH_METRES = 12.0
JUGGLE_BOUNCE_SECONDS = .4
JUGGLE_HEIGHT = 10.0
FALL_SPEED = 600.0
FALL_DRIFT = 2.0
IMPACT_RADIUS_SHARE, MAX_IMPACT_RADIUS = .01, 60.0  # of Range
AFTER_SECONDS = .3
LASER_SHARE, CLONE_SHARE, JUGGLE_SHARE, IMPACT_SHARE = .45, .2, .1, .25
IMPACT_FIRE = (255, 70, 50)
IMPACT_RING = (255, 90, 60, 225)
LASER_TICK = .1
LASER_WIDTH = .35
RUSH_MAX_SECONDS = 6.0
GRAB_DISTANCE = 3.0
NECK_HEIGHT = .55
LIFT_HEIGHT = 25.0
LIFT_SPEED = 90.0
OBSTACLE_DAMAGE_SHARE = .1
STREAK_TINT = (40, 70, 190, 170)
SPARK_TINT = (255, 190, 90, 230)
SMOKE_TINT = (70, 66, 62, 160)


class LaserVision(BeamAbility):
    ability_id = "laser_vision"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.mode = FOCUSED
        self._phase = 0.0

    def reset(self) -> None:
        super().reset()
        self.mode = FOCUSED

    def switch_mode(self) -> None:
        self.mode = SWEEPING if self.mode == FOCUSED else FOCUSED
        self.say(f"LASER: {self.mode}")

    def _overdrive(self):
        return self.owner.powers.abilities["laser_overdrive"]

    def beam_values(self):
        overdrive = self._overdrive()
        damage, width = self.p("damage"), self.beam_width()
        if self.mode == SWEEPING:
            damage, width = damage * SWEEP_DAMAGE_SHARE, width * SWEEP_WIDTH_SCALE
        return (damage * overdrive.damage_scale, self.reach() * overdrive.range_scale,
                width * (1.5 if overdrive.engaged else 1.0))

    def aim_offset(self, direction):
        if self.mode != SWEEPING:
            return direction
        self._phase += SWEEP_SPEED * .0174533 * BEAM_TRACE_INTERVAL
        return sweep_angle(direction, sin(self._phase) * SWEEP_ARC)

    def on_beam_hit(self, hit, damage, direction) -> None:
        super().on_beam_hit(hit, damage, direction)
        combat = self.combat
        combat.heat_effects(hit, self.owner, intensity=self.boost(.5, 2.0))
        overdrive = self._overdrive()
        if overdrive.engaged and hit.kind != "none":
            overdrive.impact(hit.point, damage)


class AerialCharge(Ability):
    ability_id = "aerial_charge"

    def press(self) -> None:
        press_charge(self, "AERIAL CHARGE")


class EnhancedSenses(Ability):
    ability_id = "enhanced_senses"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.detected: list = []

    def press(self) -> None:
        if self.active:
            self.cancel()
        elif self.usable():
            self.active = True
            self.say("ENHANCED SENSES")

    def detects(self, target) -> str | None:
        """How he notices someone: hearing for movement, X-ray for anything zinc doesn't hide."""
        origin = center_of(self.owner)
        point = center_of(target)
        if (point - origin).length() > self.reach():
            return None
        if not line_blocked_by_zinc(self.game, origin, point):
            return "xray"
        if target.velocity.length() >= MOVING_SPEED:
            return "hearing"
        return None

    def update(self, dt: float) -> None:
        if not self.active:
            return
        if self.vitals.nullified or self.vitals.immobile:
            self.cancel()
            return
        self.detected = [target for target in self.combat.hostiles_of(self.owner)
                         if self.detects(target)]
        if self.owner.controlled:
            self.combat.mark(self.owner, self.detected, self.reach(), (255, 70, 60, 240))

    def cancel(self) -> None:
        was_active, self.active = self.active, False
        self.detected = []
        if was_active and self.owner.controlled:
            self.combat.markers.hide()


class NeckLaserExecution(Motion):
    """Key 4: by the neck, up, 4 seconds of lasers, 3 of four clones, 2 of juggling, then the ground."""

    def __init__(self, ability, target) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.target = target
        self.phase = RUSH
        self.was_flying = self.owner.flight.is_flying
        self.top = 0.0
        self.grabbed = False
        self.thrown = False
        self.laser_time = 0.0
        self.beam = None
        self.stored = 0.0
        self.tick_left = 0.0
        self.damage_dealt = 0.0
        self.clones: list = []
        self.clone_time = 0.0
        self.clone_ages: list = []
        self.clone_hits = 0
        self.juggle_time = 0.0
        self.bounces = 0
        self.anchor = SimVec3()
        self.fall = None
        self.after = 0.0
        self.stages = [RUSH]
        self.rng = Random(4)
        self.streak = SpeedStreak(ability.combat, STREAK_TINT)
        self.owner.flight.phase = FlightPhase.CRUISE
        self.owner.flight.phase_time = 0.0
        self.owner.right_arm.rotation_x = -60.0

    def _target_gone(self) -> bool:
        target = self.target
        return (target.parked or target.vitals.downed
                or not self.ability.combat.hostile(self.owner, target))

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        owner, target = self.owner, self.target
        if self.phase == AFTER:
            self.after += dt
            owner.flight.velocity = SimVec3()
            return self.after < AFTER_SECONDS
        if self._target_gone() or (self.phase == RUSH and self.elapsed > RUSH_MAX_SECONDS):
            return False
        target.vitals.add_status("held", .2)
        self.facing = degrees(atan2(target.x - owner.x, target.z - owner.z))
        return getattr(self, f"_step_{self.phase}")(dt)

    def _step_rush(self, dt: float) -> bool:
        ability, owner, target = self.ability, self.owner, self.target
        origin = center_of(owner)
        offset = center_of(target) - origin
        distance = offset.length()
        # The margin matters: flying to exactly the grab distance can stop a rounding error short.
        if distance <= GRAB_DISTANCE + .05:
            self.streak.release()
            self.grabbed = True
            ground = ability.game.world.height_at(owner.x, owner.z)
            self.top = min(CEILING, max(float(owner.y), ground + LIFT_HEIGHT))
            target.pose_root.setP(18.0)
            target.left_arm.rotation_x = target.right_arm.rotation_x = -35.0
            owner.flight.velocity = SimVec3()
            ability.game.world.play_power_sound(.35)
            self._enter(LIFT)
            return True
        direction = offset.normalized()
        step = min(ability.p("speed") * dt, distance - GRAB_DISTANCE)
        hit = trace(ability.game, origin, direction, step + 1.0, ignore=(owner, target), characters=(),
                    terrain=False)
        if hit.kind in ("object", "tree"):
            ability.combat.damage_hit(owner, hit, self._total_damage() * OBSTACLE_DAMAGE_SHARE, direction,
                                      kind=PHYSICAL, force=20.0)
        velocity = direction * (step / max(dt, 1e-4))
        self._move(velocity, dt)
        owner.flight.velocity = velocity
        here = center_of(owner)
        self.streak.show(here, velocity)
        return True

    def _enter(self, phase: str) -> None:
        self.phase = phase
        self.stages.append(phase)

    def _hold_by_the_neck(self) -> None:
        owner, target = self.owner, self.target
        offset = SimVec3(target.x - owner.x, 0.0, target.z - owner.z)
        side = offset.normalized() if offset.length() > 1e-3 else self.ability.facing()
        target.position = (owner.x + side.x * GRAB_DISTANCE, owner.y + NECK_HEIGHT,
                           owner.z + side.z * GRAB_DISTANCE)
        owner.right_arm.rotation_x = -150.0

    def _step_lift(self, dt: float) -> bool:
        owner = self.owner
        self._hold_by_the_neck()
        if owner.y >= self.top:
            owner.flight.velocity = SimVec3()
            self._enter(LASER)
            self.tick_left = 0.0
            return True
        speed = min(LIFT_SPEED, self.ability.p("speed"))
        self._move(SimVec3(0.0, speed, 0.0), dt)
        owner.flight.velocity = SimVec3(0.0, speed, 0.0)
        return True

    def _total_damage(self) -> float:
        powers = self.owner.powers
        return self.ability.p("damage") * powers.strength * powers.energy_scale

    def _face_of_target(self) -> SimVec3:
        left, right = self.target.eye_points()
        return SimVec3((left.x + right.x) * .5, (left.y + right.y) * .5, (left.z + right.z) * .5)

    def _step_laser(self, dt: float) -> bool:
        ability, owner = self.ability, self.owner
        combat = ability.combat
        self._hold_by_the_neck()
        owner.flight.velocity = SimVec3()
        # Real seconds, so a slow frame cannot stretch the four seconds, and all of its share is dealt.
        seconds = min(ability.game.frame_seconds, LASER_SECONDS - self.laser_time)
        self.laser_time += seconds
        self.stored += self._total_damage() * LASER_SHARE * seconds / LASER_SECONDS
        done = self.laser_time >= LASER_SECONDS - 1e-6
        face = self._face_of_target()
        if self.beam is None:
            self.beam = combat.acquire_beam()
        if self.beam is not None:
            self.beam.show(owner.eye_points(), face, LASER_WIDTH, LaserVision.CORE, LaserVision.GLOW)
        self.tick_left -= seconds
        if self.tick_left <= 0.0 or done:
            self.tick_left = LASER_TICK
            self._burn(face)
            if self._target_gone():
                return False
        if done:
            self._stop_beam()
            self._start_clones()
        return True

    def _stop_beam(self) -> None:
        if self.beam is not None:
            self.ability.combat.release_beam(self.beam)
            self.beam = None

    def _burn(self, face: SimVec3) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        direction = (face - center_of(owner)).normalized()
        self.damage_dealt += combat.hit_character(owner, target, self.stored, HEAT, direction, 0.0)
        self.stored = 0.0
        rng = self.rng
        for _ in range(2):
            spark = SimVec3(rng.uniform(-9.0, 9.0), rng.uniform(2.0, 12.0), rng.uniform(-9.0, 9.0))
            combat.puffs.emit(face, spark, SPARK_TINT, size=.18, grow=.1, life=.25)
        combat.puffs.emit(face, SimVec3(rng.uniform(-1.0, 1.0), 4.0, rng.uniform(-1.0, 1.0)), SMOKE_TINT,
                          size=.5, grow=2.0, life=.8)
        ability.game.camera_impulse = max(ability.game.camera_impulse, .35)

    # -- the four clones --------------------------------------------------
    def _start_clones(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        self.anchor = SimVec3(float(target.x), float(target.y), float(target.z))
        self.clones = owner.team.borrow_puppets(self.owner.character_id, CLONE_COUNT)
        self.clone_ages = [-index * CLONE_ATTACK_SECONDS / CLONE_COUNT for index in range(CLONE_COUNT)]
        self.clone_time = 0.0
        for index, clone in enumerate(self.clones):
            point = self._clone_spot(index, CLONE_RING, 0.0)
            clone.position = (point.x, point.y, point.z)
            ability.combat.puffs.emit(point + SimVec3(0.0, 1.4, 0.0), SimVec3(0.0, 2.0, 0.0), IMPACT_RING, size=1.0, grow=2.5,
                                      life=.4)
        owner.right_arm.rotation_x = 0.0
        ability.game.world.play_power_sound(.5)
        self._enter(CLONES)

    def _clone_spot(self, index: int, radius: float, height: float) -> SimVec3:
        """Round the target, each on its own line, so that no two ever move alike."""
        angle = 2.0 * pi * index / CLONE_COUNT + self.clone_time * (.5 + index * .15)
        return self.anchor + SimVec3(sin(angle) * radius, height - 1.0 + index % 2 * .8, cos(angle) * radius)

    def _place_clone(self, clone, point: SimVec3) -> None:
        clone.position = (point.x, point.y, point.z)
        dx, dz = self.anchor.x - point.x, self.anchor.z - point.z
        if dx * dx + dz * dz > .01:
            clone.local_yaw = degrees(atan2(dx, dz))
        self.ability.game.planet.orient_entity(clone, point, clone.local_yaw)

    def _step_clones(self, dt: float) -> bool:
        """Exactly three seconds, with the blows staggered round the ring. The damage is his, so it can
        only ever land on his enemy."""
        ability, owner, target = self.ability, self.owner, self.target
        seconds = min(ability.game.frame_seconds, CLONE_SECONDS - self.clone_time)
        self.clone_time += seconds
        self._watch(dt)
        for index, clone in enumerate(self.clones):
            before = self.clone_ages[index]
            age = before + seconds
            self.clone_ages[index] = age
            if age < 0.0:
                self._place_clone(clone, self._clone_spot(index, CLONE_RING, 0.0))
                continue
            kind = CLONE_ATTACKS[(index + int(age / CLONE_ATTACK_SECONDS)) % len(CLONE_ATTACKS)]
            progress = (age / CLONE_ATTACK_SECONDS) % 1.0
            reach = sin(progress * pi)
            radius = CLONE_RING + (CLONE_STRIKE - CLONE_RING) * reach
            self._place_clone(clone, self._clone_spot(index, radius, (1.0 - reach) * 6.0 if kind == "aerial" else 0.0))
            clone.right_arm.rotation_x = -150.0 * reach if kind != "kick" else 0.0
            clone.left_leg.rotation_x = -85.0 * reach if kind == "kick" else 0.0
            middle_passed = floor(age / CLONE_ATTACK_SECONDS + .5) > floor(max(0.0, before) / CLONE_ATTACK_SECONDS + .5)
            if middle_passed:
                self._clone_hit(clone)
                if self._target_gone():
                    return False
        target.position = (self.anchor.x + sin(self.clone_time * 31.0) * .35, self.anchor.y,
                           self.anchor.z + cos(self.clone_time * 27.0) * .35)
        target.pose_root.setP(sin(self.clone_time * 19.0) * 16.0)
        if self.clone_time >= CLONE_SECONDS - 1e-6:
            for clone in self.clones:
                clone.right_arm.rotation_x = clone.left_leg.rotation_x = 0.0
            self._enter(REGRAB)
        return True

    def _clone_hit(self, clone) -> None:
        ability, target = self.ability, self.target
        combat = ability.combat
        self.clone_hits += 1
        hits = CLONE_COUNT * CLONE_SECONDS / CLONE_ATTACK_SECONDS
        self.damage_dealt += combat.hit_character(self.owner, target, self._total_damage() * CLONE_SHARE / hits, PHYSICAL)
        combat.puffs.emit(center_of(target), SimVec3(0.0, 2.0, 0.0), SPARK_TINT, size=.7, grow=2.2, life=.22)
        ability.game.camera_impulse = max(ability.game.camera_impulse, .35)
        ability.game.world.play_power_sound(.25)

    def _watch(self, dt: float) -> None:
        owner = self.owner
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        away = here - self.anchor
        spot = self.anchor + (away.normalized() if away.length() > 1e-3 else self.ability.facing()) * WATCH_METRES
        offset = spot - here
        distance = offset.length()
        if distance > .1:
            self._move(offset * (min(120.0 * dt, distance) / distance / max(dt, 1e-4)), dt)
        owner.flight.velocity = SimVec3()

    def _step_regrab(self, dt: float) -> bool:
        owner, target = self.owner, self.target
        target.position = (self.anchor.x, self.anchor.y, self.anchor.z)
        target.pose_root.setP(18.0)
        offset = center_of(target) - center_of(owner)
        speed = max(120.0, self.ability.p("speed"))
        remaining = offset.length() - GRAB_DISTANCE
        if remaining <= speed * dt + .05:
            owner.flight.velocity = SimVec3()
            self.juggle_time = 0.0
            self.bounces = 0
            self.ability.game.world.play_power_sound(.35)
            self._enter(JUGGLE)
            return True
        self._move(offset.normalized() * speed, dt)
        return True

    def _step_juggle(self, dt: float) -> bool:
        """Exactly two seconds: up off his fist, down, and up again, with no idea which way is up."""
        ability, owner, target = self.ability, self.owner, self.target
        seconds = min(ability.game.frame_seconds, JUGGLE_SECONDS - self.juggle_time)
        self.juggle_time += seconds
        owner.flight.velocity = SimVec3()
        bounce = int(self.juggle_time / JUGGLE_BOUNCE_SECONDS)
        progress = (self.juggle_time / JUGGLE_BOUNCE_SECONDS) % 1.0
        offset = SimVec3(float(target.x) - float(owner.x), 0.0, float(target.z) - float(owner.z))
        side = offset.normalized() if offset.length() > 1e-3 else ability.facing()
        target.position = (float(owner.x) + side.x * GRAB_DISTANCE,
                           float(owner.y) + NECK_HEIGHT + sin(progress * pi) * JUGGLE_HEIGHT,
                           float(owner.z) + side.z * GRAB_DISTANCE)
        target.pose_root.setP((self.juggle_time * 720.0) % 360.0)
        owner.right_arm.rotation_x = -150.0 * (1.0 - min(1.0, progress * 5.0)) - 40.0
        if bounce > self.bounces:
            self.bounces = bounce
            self._juggle_hit()
            if self._target_gone():
                return False
        if self.juggle_time >= JUGGLE_SECONDS - 1e-6:
            target.position = (float(owner.x) + side.x * GRAB_DISTANCE, float(owner.y) + NECK_HEIGHT,
                               float(owner.z) + side.z * GRAB_DISTANCE)
            self.fall = HurledDown(ability, owner, target, FALL_SPEED, FALL_DRIFT)
            target.pose_root.setP(-60.0)
            owner.right_arm.rotation_x = 60.0
            ability.game.camera_impulse = max(ability.game.camera_impulse, 1.5)
            ability.game.world.play_power_sound(.6)
            self._enter(FALL)
        return True

    def _juggle_hit(self) -> None:
        ability, target = self.ability, self.target
        hits = JUGGLE_SECONDS / JUGGLE_BOUNCE_SECONDS
        self.damage_dealt += ability.combat.hit_character(self.owner, target, self._total_damage() * JUGGLE_SHARE / hits,
                                                          PHYSICAL)
        ability.combat.puffs.emit(center_of(target), SimVec3(0.0, 3.0, 0.0), SPARK_TINT, size=.8, grow=2.5, life=.25)
        ability.game.world.play_power_sound(.3)

    def _step_fall(self, dt: float) -> bool:
        ability, owner, target = self.ability, self.owner, self.target
        owner.flight.velocity = SimVec3()
        if self.fall.step(dt, self._total_damage() * OBSTACLE_DAMAGE_SHARE):
            radius = ability.area(IMPACT_RADIUS_SHARE, MAX_IMPACT_RADIUS)
            ground_blast(ability, owner, target, self.fall.point, self._total_damage() * IMPACT_SHARE, radius,
                         ability.force(30.0, 120.0), IMPACT_FIRE, IMPACT_RING, "laser-execution")
            self.thrown = True
            self.after = 0.0
            self._return_clones()
            self._enter(AFTER)
        return True

    def _return_clones(self) -> None:
        clones, self.clones = self.clones, []
        if clones:
            for clone in clones:
                clone.right_arm.rotation_x = clone.left_leg.rotation_x = 0.0
                self.ability.combat.puffs.emit(center_of(clone), SimVec3(0.0, 2.0, 0.0), IMPACT_RING, size=.8, grow=2.0,
                                               life=.3)
            self.owner.team.return_puppets(clones)

    def finish(self) -> None:
        """Runs however this ends: the clones go, and anyone he was holding falls under their own weight."""
        owner, target = self.owner, self.target
        self.streak.release()
        self._stop_beam()
        self._return_clones()
        target.vitals.clear_status("held")
        if not target.vitals.downed and self.phase != AFTER:
            target.pose_root.setP(0.0)
        target.left_arm.rotation_x = target.right_arm.rotation_x = 0.0
        if self.grabbed and not self.thrown and not target.parked:
            launch_character(owner, target, SimVec3())
        owner.right_arm.rotation_x = 0.0
        owner.flight.velocity = SimVec3()
        settle(owner, self.was_flying)


class NeckLaserExecutionAbility(Ability):
    ability_id = "neck_laser_execution"

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or not owner.flight_allowed:
            return  # one already running is a motion, so it can never start twice
        target = self.target()
        if target is None:
            self.say("NO ENEMY IN RANGE")
            return
        target.powers.cancel_all()
        target.release_motion()
        target.knock = SimVec3()
        target.jump_velocity = target.jump_height = 0.0
        owner.motion = NeckLaserExecution(self, target)
        self.say("LASER EXECUTION")

    def hud_state(self) -> str:
        return "ON" if isinstance(self.owner.motion, NeckLaserExecution) else super().hud_state()


class LaserOverdrive(Ability):
    ability_id = "laser_overdrive"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self._impact_timer = 0.0
        self.aura = Bubble(owner, (255, 40, 20, 0), center=2.5)

    @property
    def engaged(self) -> bool:
        return self.active

    @property
    def damage_scale(self) -> float:
        return self.boost(1.5, 4.0) if self.active else 1.0

    @property
    def range_scale(self) -> float:
        return OVERDRIVE_RANGE_SCALE if self.active else 1.0

    def press(self) -> None:
        if self.active:
            self.cancel()
        elif self.usable():
            self.active = True
            self.say("MAXIMUM LASER OVERDRIVE")

    def update(self, dt: float) -> None:
        self._impact_timer -= dt
        if self.active:
            if self.vitals.nullified or self.vitals.downed:
                self.cancel()
            else:
                self.aura.show(.7, (255, 40, 20, 120))

    def impact(self, point, damage: float) -> None:
        """Beam hits blast the area while engaged, a few times a second."""
        if self._impact_timer > 0.0:
            return
        self._impact_timer = IMPACT_INTERVAL
        area = self.area(.02, 25.0)
        self.combat.blast(self.owner, point, area, min(self.p("damage"), max(damage * 3.0, 30.0)),
                          self.force(10.0, 40.0), kind=HEAT, crater=(area * .3, .5, "laser"),
                          play_sound=False)

    def cancel(self) -> None:
        self.active = False
        self.aura.hide()
