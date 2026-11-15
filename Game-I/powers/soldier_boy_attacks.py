"""Soldier Boy's keys 2, 3 and 4: time-stop attacks built on an enormous jump.

He cannot fly and none of this makes him: his flight state stays GROUNDED throughout, and the body is
placed directly, because normal movement holds anyone who is not flying down on the ground.
"""

from __future__ import annotations

from math import atan2, cos, degrees, pi, sin

from ursina import Vec3, scene

from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.base import BEAM_TRACE_INTERVAL, Ability, Motion, land
from powers.common import HurledDown, ground_blast, launch_character, nuclear_sphere
from powers.fx import Bubble, SpeedStreak
from powers.universal import MAX_LAUNCH_SPEED, StrikeAndBreakAway, seize
from powers.vitals import EXPLOSION, PHYSICAL, RADIATION

SEQUENCE_MAX_SECONDS = 10.0  # on top of the time it takes to get there
JUMP, APPROACH, GRIP, LIFT, SLAM, REGRAB, PUNCH, BEAM, DESCEND, AFTERMATH = (
    "jump", "approach", "grip", "lift", "slam", "regrab", "punch", "beam", "descend", "aftermath")
POSITION, CATCH, THROWN_DOWN = "position", "catch", "thrown_down"
JUMP_HEIGHT = 60.0
JUMP_SPEED = 180.0
REACH = 3.0                # the arm's length at which he grabs or hits
HOLD_HEIGHT = .55          # a held body's feet off the ground, with its head at his hand
FACE_HEIGHT = 2.5
GRIP_SECONDS = .18
MAX_FLYING_SECONDS = 1.5     # the Flying Punch arrives within this, from any distance
GIVE_UP_SECONDS = 3.0        # far more than that needs: only something blocking him gets this far
PUNCH_HOLD_SECONDS = .16     # the instant of the blow, before time resumes
PUNCH_SECONDS = .9         # slow motion: the world is stopped, so only these two bodies are slowed
ARM_DRAWN_BACK, ARM_THROWN = 45.0, -170.0
ARM_GRIPPING = -150.0
ARM_BRACED = 30.0
TRAIL = (150, 175, 105, 170)
FLASH = (205, 255, 185)
DUST = (190, 170, 140, 220)
GREEN_FIRE = (90, 255, 95, 110)
SMOKE = (80, 72, 66, 210)
SHOCKWAVE_PUFFS = 8
OBSTACLE_DAMAGE_SHARE = .05
LANDING_DAMAGE_SHARE = .1
THROW_RISE = .45
THROW_MAX_SECONDS = 60.0   # from the ceiling a thrown body falls this long, and must reach the ground
DESCEND_GRAVITY = 160.0
MAX_DESCEND_SPEED = 400.0
AFTERMATH_SECONDS = .3
PUNCH_SHOCK_RADIUS = 18.0
LIFT_HEIGHT = 30.0
LIFT_SPEED = 150.0
# Key 3.
PUNCH_DAMAGE_SHARE = .5    # the rest is the explosion's, which also reaches anyone else nearby
BLAST_RADIUS_SHARE = .1    # of Range
MAX_BLAST_RADIUS = 220.0
MAX_BLAST_CRATER = 40.0
BLAST_CRATER_DEPTH = 8.0
BLAST_SMOKE_PUFFS = 12
# Key 4. The shares add up to all of Damage.
SLAMS = 2
SLAM_SPEED = 400.0
SLAM_DAMAGE_SHARE = .1
SLAM_RADIUS_SHARE = .01
MAX_SLAM_RADIUS = 25.0
FINAL_PUNCH_SHARE = .1
FIRST_NUKE_SHARE = .2
BEAM_DAMAGE_SHARE = .2
FINAL_NUKE_SHARE = .15
LAST_IMPACT_SHARE = .15
BEAM_SECONDS = 2.5
FLAME_EVERY = .1
EXECUTION_JUMP_HEIGHT = 150.0
EXECUTION_EXTRA_SECONDS = 25.0
PUNCH_LAUNCH_RISE = .3
MIN_PUNCH_LAUNCH = 400.0
POSITION_SECONDS = .5      # the blast goes off where they are by then
MIN_POSITION_SPEED = 500.0
LAST_THROW_SPEED = 600.0
LAST_THROW_DRIFT = 1.5
NUKE_RADIUS_SHARE, MAX_NUKE_RADIUS = .1, 180.0   # of Range
LAST_IMPACT_RADIUS = 50.0
NUKE_FIRE = (90, 255, 95)
NUKE_RING = (150, 255, 130, 225)
# Key 1.
RADIATION_SECONDS = 3.0
RADIATION_RADIUS_SHARE, MAX_RADIATION_RADIUS = .06, 120.0   # of Range
RADIATION_CRATER = (14.0, 1.2)
RADIATION_SHAKE = 1.0      # a blast every three seconds must not shake the view as one big blast does


class LeapingAttack(Motion):
    """Jump, reach the target wherever it is, do something to it, and come back down."""

    jump_height = JUMP_HEIGHT

    def __init__(self, ability, target) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.target = target
        self.phase = JUMP
        self.phase_time = 0.0
        self.grabbed = False
        self.thrown = False
        self.fall_speed = 0.0
        self.stages = [JUMP]
        self.streak = SpeedStreak(ability.combat, TRAIL)
        owner = self.owner
        away = (center_of(target) - center_of(owner)).length()
        self.time_limit = SEQUENCE_MAX_SECONDS + away / max(1.0, ability.p("speed"))
        highest = max(float(ability.game.planet.MAX_FLIGHT_ALTITUDE), float(owner.y), float(target.y))
        self.peak = SimVec3(float(owner.x), min(highest, max(float(owner.y) + self.jump_height, float(target.y))),
                            float(owner.z))
        # World time is stopped, but what this sequence sets off has to play out, not hang on screen.
        self.frozen_bursts = set(ability.game.world._active_explosions)
        ability.combat.begin_time_stop(owner, target)
        self._ground_burst(SimVec3(float(owner.x), float(owner.y), float(owner.z)), 3.0, .4, "jump")

    def _enter(self, phase: str) -> None:
        self.phase = phase
        self.phase_time = 0.0
        self.stages.append(phase)

    def _target_gone(self) -> bool:
        target = self.target
        return (target.parked or target.vitals.downed
                or not self.ability.combat.hostile(self.owner, target))

    def _total_damage(self) -> float:
        powers = self.owner.powers
        return self.ability.p("damage") * powers.strength * powers.attack_scale

    def _floor(self, x: float, z: float) -> float:
        return self.ability.game.world.height_at(x, z) + .25

    def _ground_burst(self, point: SimVec3, radius: float, depth: float, surface: str) -> None:
        """Dust and a small mark where he pushes off or comes down."""
        game = self.ability.game
        if float(point.y) > self._floor(point.x, point.z) + 1.0:
            return  # jumping from mid-air: there is no ground here to mark
        game.world.terrain_impact(point, radius=radius, depth=depth, intensity=.7, surface=surface)
        game.world._terrain_rebuild_wait = 0.0  # world time is stopped, but this should show now
        for index in range(SHOCKWAVE_PUFFS):
            angle = 2.0 * pi * index / SHOCKWAVE_PUFFS
            self.ability.combat.puffs.emit(point, SimVec3(sin(angle) * 22.0, 3.0, cos(angle) * 22.0), DUST,
                                           size=1.2, grow=5.0, life=.5)
        game.camera_impulse = max(game.camera_impulse, .8)

    def _leap_to(self, point: SimVec3, speed: float, dt: float) -> float:
        """Go straight at a point through the air, breaking what is in the way; returns distance left."""
        ability, owner = self.ability, self.owner
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        offset = point - here
        distance = offset.length()
        step = min(speed * dt, distance)
        if step <= 1e-6:
            return distance
        direction = offset.normalized()
        hit = trace(ability.game, center_of(owner), direction, step + 1.0, ignore=(owner, self.target),
                    characters=(), terrain=False)
        if hit.kind in ("object", "tree"):
            ability.combat.damage_hit(owner, hit, self._total_damage() * OBSTACLE_DAMAGE_SHARE, direction,
                                      kind=PHYSICAL, force=20.0)
        moved = here + direction * step
        x, z = ability.game.planet.clamp_to_land(moved.x, moved.z)
        # A super jump can have him above the flying ceiling already, and it must not snap him back to it.
        ceiling = max(float(ability.game.planet.MAX_FLIGHT_ALTITUDE), here.y, float(self.target.y))
        owner.position = (x, max(self._floor(x, z), min(ceiling, moved.y)), z)
        self.streak.show(center_of(owner), direction * (step / max(dt, 1e-4)))
        return distance - step

    def _side(self) -> SimVec3:
        owner, target = self.owner, self.target
        offset = SimVec3(float(target.x) - float(owner.x), 0.0, float(target.z) - float(owner.z))
        return offset.normalized() if offset.length() > 1e-3 else self.ability.facing()

    def _hold(self) -> None:
        owner, target = self.owner, self.target
        side = self._side()
        x, z = float(owner.x) + side.x * REACH, float(owner.z) + side.z * REACH
        target.position = (x, max(self._floor(x, z), float(owner.y) + HOLD_HEIGHT), z)
        owner.left_arm.rotation_x = ARM_GRIPPING

    def _let_go(self) -> None:
        """Cut short part-way through: anything held, or on its way down, simply falls."""
        target = self.target
        target.vitals.clear_status("held")
        if self.grabbed and not self.thrown and not target.parked:
            launch_character(self.owner, target, SimVec3())
        self.grabbed = False
        self.thrown = True

    # -- the sequence ----------------------------------------------------
    def step(self, dt: float) -> bool:
        self.elapsed += dt
        self.phase_time += dt
        owner, target = self.owner, self.target
        for burst in tuple(self.ability.game.world._active_explosions):
            if self.ability.combat.time_stopped and burst not in self.frozen_bursts:  # a running world steps its own
                burst.step(dt)
        if self.phase not in (DESCEND, AFTERMATH):
            if self._target_gone() or self.elapsed > self.time_limit:
                self._let_go()
                self.streak.release()
                self._enter(DESCEND)
            else:
                dx, dz = float(target.x) - float(owner.x), float(target.z) - float(owner.z)
                if dx * dx + dz * dz > .01:
                    self.facing = degrees(atan2(dx, dz))
                if self.grabbed:
                    target.vitals.add_status("held", .2)
        return getattr(self, f"_step_{self.phase}")(dt)

    def _step_jump(self, dt: float) -> bool:
        speed = min(JUMP_SPEED, self.ability.p("speed"))
        if self._leap_to(self.peak, speed, dt) <= 1e-3:
            self._enter(APPROACH)
        return True

    def _step_approach(self, dt: float) -> bool:
        owner = self.owner
        offset = center_of(self.target) - center_of(owner)
        # The margin matters: going to exactly arm's length can stop a rounding error short.
        remaining = offset.length() - REACH
        if remaining <= .05:
            self.streak.release()
            self.ability.game.world.play_power_sound(.35)
            self._arrived()
            return True
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        self._leap_to(here + offset.normalized() * remaining, self.ability.p("speed"), dt)
        return True

    def _arrived(self) -> None:
        raise NotImplementedError

    def _step_punch(self, dt: float) -> bool:
        progress = min(1.0, self.phase_time / PUNCH_SECONDS)
        self.owner.right_arm.rotation_x = ARM_DRAWN_BACK + (ARM_THROWN - ARM_DRAWN_BACK) * progress
        if self.grabbed:
            self._hold()
        if progress >= 1.0:
            self._connect()
        return True

    def _connect(self) -> None:
        raise NotImplementedError

    def _shockwave(self, point: SimVec3, speed: float, size: float, grow: float) -> None:
        for index in range(SHOCKWAVE_PUFFS):
            angle = 2.0 * pi * index / SHOCKWAVE_PUFFS
            self.ability.combat.puffs.emit(point, SimVec3(sin(angle) * speed, 0.0, cos(angle) * speed),
                                           (*FLASH, 210), size=size, grow=grow, life=.45)

    def _throw(self, landing_damage: float) -> None:
        """Send the target far away; it falls and lands by itself, and carries on when time resumes."""
        owner, target, ability = self.owner, self.target, self.ability
        target.vitals.clear_status("held")
        launch_character(owner, target, (self._side() + SimVec3(0.0, THROW_RISE, 0.0)).normalized()
                         * min(MAX_LAUNCH_SPEED, ability.p("speed")), landing_damage)
        target.motion.max_seconds = THROW_MAX_SECONDS
        target.motion.hard_landing_speed = 0.0  # air drag slows it, but this landing always counts
        self.grabbed = False
        self.thrown = True
        ability.game.camera_impulse = max(ability.game.camera_impulse, 2.5)
        self._enter(DESCEND)

    def _step_descend(self, dt: float) -> bool:
        owner = self.owner
        self.fall_speed = min(MAX_DESCEND_SPEED, self.fall_speed + DESCEND_GRAVITY * dt)
        x, z = float(owner.x), float(owner.z)
        floor = self._floor(x, z)
        if self._leap_to(SimVec3(x, floor, z), self.fall_speed, dt) <= 1e-3:
            self.streak.release()
            self._ground_burst(SimVec3(x, floor, z), 2.0, .25, "landing")
            owner.right_arm.rotation_x = owner.left_arm.rotation_x = 0.0
            self._enter(AFTERMATH)
        return True

    def _step_aftermath(self, dt: float) -> bool:
        return self.phase_time < AFTERMATH_SECONDS

    def finish(self) -> None:
        """Runs however this ends, even a character switch: time always resumes."""
        owner, target, ability = self.owner, self.target, self.ability
        self.streak.release()
        self._let_go()
        if not target.vitals.downed and target.motion is None:
            target.pose_root.setP(0.0)
        owner.right_arm.rotation_x = owner.left_arm.rotation_x = 0.0
        owner.knock = SimVec3()
        # Cut short in the air, ordinary gravity brings him down: there is no flight to fall back on.
        owner.jump_height = max(0.0, float(owner.y) - self._floor(float(owner.x), float(owner.z)))
        owner.jump_velocity = 0.0
        ability.combat.end_time_stop(owner)
        ability.after_sequence()


class FlyingPunch(StrikeAndBreakAway):
    """Key 2: straight at the target at extreme speed, one huge punch, and time resumes. He never enters any flight state."""

    def __init__(self, ability, target) -> None:
        super().__init__(ability, target)
        owner = self.owner
        owner.flight.phase = FlightPhase.GROUNDED  # the charge it shares with the flyers would have him flying
        owner.jump_height = owner.jump_velocity = 0.0
        self.was_flying = False
        self.connected_for = None
        self.blur_speed = 0.0

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        if self.connected_for is not None:
            self.connected_for += dt
            return self.connected_for < PUNCH_HOLD_SECONDS  # the blow lands, and the world starts again
        ability, owner, target = self.ability, self.owner, self.target
        if target.vitals.downed or target.parked or not ability.combat.hostile(owner, target):
            return False
        if self.elapsed > GIVE_UP_SECONDS:
            return False  # whatever kept him from it, time must not stay stopped
        offset = center_of(target) - center_of(owner)
        distance = offset.length()
        if distance <= REACH:
            self._land(offset.normalized() if distance > 1e-3 else ability.facing())
            return True
        # However low Speed is set and however far away the target is, it arrives: time cannot be left stopped for long.
        self.speed = max(ability.p("speed"), distance / MAX_FLYING_SECONDS)
        self.direction = offset * (1.0 / distance)
        length = min(self.speed * dt, distance - REACH * .9)
        hit = trace(ability.game, center_of(owner), self.direction, length + 1.0, ignore=(owner, target, *self.already_hit),
                    characters=(), terrain=False)
        if hit.kind in ("object", "tree"):  # on through it: nothing stands between him and the target
            self.already_hit.add(hit.target)
            ability.combat.damage_hit(owner, hit, self.impact_damage(), self.direction, kind=PHYSICAL, force=ability.force(30.0, 150.0))
            ability.combat.burst(hit.point, 5.0, .9)
        self._carry(self.direction * length)
        self.blur_speed = self.speed
        self.facing = degrees(atan2(self.direction.x, self.direction.z))
        owner.right_arm.rotation_x = self.style.right_arm * .4
        self._draw_speed(self.direction * self.speed, dt)
        return True

    def _carry(self, step: SimVec3) -> None:
        """Straight along the line, up or down: the world's usual clamp would hold someone who is not flying to the ground."""
        owner, game = self.owner, self.ability.game
        x, z = game.planet.clamp_to_land(float(owner.x) + step.x, float(owner.z) + step.z)
        floor = game.world.height_at(x, z) + .25
        # Up in a super jump he can already be above the ceiling, and it must not snap him back down to it.
        ceiling = max(float(game.planet.MAX_FLIGHT_ALTITUDE), float(owner.y))
        owner.position = (x, max(floor, min(float(owner.y) + step.y, ceiling)), z)

    def _land(self, direction: SimVec3) -> None:
        """Where the target really is: the distance has just been measured."""
        ability, owner, target = self.ability, self.owner, self.target
        self.direction = direction
        ability.combat.hit_character(owner, target, self.impact_damage(), PHYSICAL, direction, ability.force(30.0, 150.0))
        if not target.vitals.downed:
            self._connect()
        self.away = None
        self.connected_for = 0.0
        self.blur_speed = 0.0
        ability.game.camera_impulse = max(ability.game.camera_impulse, 2.6)

    def finish(self) -> None:
        super().finish()
        owner = self.owner
        self.ability.after_sequence()
        owner.flight.phase = FlightPhase.GROUNDED
        owner.flight.velocity = SimVec3()
        # Wherever the punch found him, gravity takes it from here: he was never flying.
        floor = owner.team.game.world.height_at(float(owner.x), float(owner.z)) + .25
        owner.jump_height = max(0.0, float(owner.y) - floor)
        owner.jump_velocity = 0.0


class AerialGrabBlast(LeapingAttack):
    """Key 3: catch them, hold them up in the air, and a punch in the face sets off a huge sphere."""

    def __init__(self, ability, target) -> None:
        super().__init__(ability, target)
        self.top = 0.0

    def _arrived(self) -> None:
        self.grabbed = True
        self.target.pose_root.setP(18.0)
        self._enter(GRIP)

    def _step_grip(self, dt: float) -> bool:
        self._hold()
        if self.phase_time >= GRIP_SECONDS:
            self._start_lift()
        return True

    def _start_lift(self) -> None:
        owner = self.owner
        game = self.ability.game
        ground = game.world.height_at(float(owner.x), float(owner.z))
        self.top = max(float(owner.y), min(float(game.planet.MAX_FLIGHT_ALTITUDE), ground + LIFT_HEIGHT))
        self._enter(LIFT)

    def _step_lift(self, dt: float) -> bool:
        owner = self.owner
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        left = self._leap_to(SimVec3(here.x, self.top, here.z), min(LIFT_SPEED, self.ability.p("speed")), dt)
        self._hold()
        if left <= 1e-3:
            self.streak.release()
            self._lifted()
        return True

    def _lifted(self) -> None:
        self._enter(PUNCH)

    def _connect(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat, total = ability.combat, self._total_damage()
        target.vitals.clear_status("held")
        combat.hit_character(owner, target, total * PUNCH_DAMAGE_SHARE, PHYSICAL)
        point = SimVec3(float(target.x), float(target.y) + FACE_HEIGHT, float(target.z))
        radius = ability.area(BLAST_RADIUS_SHARE, MAX_BLAST_RADIUS)
        crater = None
        ground = ability.game.world.height_at(point.x, point.z)
        if point.y - ground < radius * .25:  # high above the ground, the sphere never reaches it
            crater = (min(MAX_BLAST_CRATER, radius * .4), BLAST_CRATER_DEPTH, "spherical-blast")
        combat.blast(owner, point, radius, total * (1.0 - PUNCH_DAMAGE_SHARE), ability.force(80.0, 180.0),
                     kind=EXPLOSION, crater=crater, burst_scale=4.0)
        ability.game.world._terrain_rebuild_wait = 0.0
        for index in range(BLAST_SMOKE_PUFFS):  # the first ring of the shockwave, and rising smoke
            angle = 2.0 * pi * index / BLAST_SMOKE_PUFFS
            combat.puffs.emit(point, SimVec3(sin(angle) * 70.0, 6.0 + (index % 3) * 10.0, cos(angle) * 70.0),
                              (*FLASH, 210) if index % 2 else SMOKE, size=3.0, grow=14.0, life=.9)
        self._throw(total * LANDING_DAMAGE_SHARE)


class RadioactiveExecution(AerialGrabBlast):
    """Key 4: two slams, a punch that sends them flying, a nuclear sphere, the chest beam and fire with them
    in his hand, a last nuclear sphere, and the ground."""

    jump_height = EXECUTION_JUMP_HEIGHT

    def __init__(self, ability, target) -> None:
        super().__init__(ability, target)
        self.time_limit += EXECUTION_EXTRA_SECONDS
        self.fall = None
        self.slams = 0
        self.landed = False
        self.punched = False
        self.visual = None
        self.beam_timer = 0.0
        self.beam_stored = 0.0
        self.flame_timer = 0.0

    def _lifted(self) -> None:
        if self.slams >= SLAMS:
            self._enter(PUNCH)
            return
        self.landed = False  # thrown down: he goes after it, and it is still his until it is thrown away
        self.target.pose_root.setP(-60.0)
        self.owner.left_arm.rotation_x = 60.0
        self.ability.game.world.play_power_sound(.35)
        self._enter(SLAM)

    def _step_slam(self, dt: float) -> bool:
        ability, target = self.ability, self.target
        speed = min(SLAM_SPEED, ability.p("speed"))
        x, z = float(target.x), float(target.z)
        floor = self._floor(x, z)
        if not self.landed:
            y = float(target.y) - speed * dt
            if y > floor:
                target.position = (x, y, z)
            else:
                self._ground_impact(x, floor, z)
                if self._target_gone():
                    return True  # that was enough; step() brings him down next frame
        # Straight down beside it, and it is back in his hand as soon as he gets there.
        side = self._side()
        spot_x, spot_z = x - side.x * REACH, z - side.z * REACH
        left = self._leap_to(SimVec3(spot_x, self._floor(spot_x, spot_z), spot_z), speed, dt)
        if self.landed and left <= .5:
            self.streak.release()
            self._enter(REGRAB)
        return True

    def _ground_impact(self, x: float, floor: float, z: float) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        self.landed = True
        self.slams += 1
        target.position = (x, floor, z)
        land(target)
        point = SimVec3(x, float(target.y), z)
        damage = self._total_damage() * SLAM_DAMAGE_SHARE
        combat.hit_character(owner, target, damage, PHYSICAL)
        radius = ability.area(SLAM_RADIUS_SHARE, MAX_SLAM_RADIUS)
        combat.blast(owner, point, radius, damage, ability.force(30.0, 120.0), kind=EXPLOSION,
                     crater=(min(12.0, radius * .5), 2.0, "soldier-boy-slam"), cracks=True, burst_scale=1.5,
                     ignore=(target,))
        ability.game.world._terrain_rebuild_wait = 0.0
        self._shockwave(point, 45.0, 1.5, 7.0)
        land(target)  # down into the crater just made
        target.pose_root.setP(-82.0)
        ability.game.camera_impulse = max(ability.game.camera_impulse, 2.0)

    def _step_regrab(self, dt: float) -> bool:
        self._hold()
        if self.phase_time >= GRIP_SECONDS:
            self.target.pose_root.setP(18.0)
            self._start_lift()
        return True

    def _connect(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        self.punched = True
        combat.hit_character(owner, target, self._total_damage() * FINAL_PUNCH_SHARE, PHYSICAL)
        point = center_of(target)
        combat.burst(point, PUNCH_SHOCK_RADIUS, 2.0, FLASH)
        self._shockwave(point, 60.0, 1.2, 6.0)
        ability.game.camera_impulse = max(ability.game.camera_impulse, 2.0)
        ability.game.world.play_power_sound(.8)
        target.vitals.clear_status("held")
        self.grabbed = False
        owner.right_arm.rotation_x = owner.left_arm.rotation_x = 0.0
        speed = max(MIN_PUNCH_LAUNCH, min(MAX_LAUNCH_SPEED, ability.p("speed")))
        launch_character(owner, target, (self._side() + SimVec3(0.0, PUNCH_LAUNCH_RISE, 0.0)).normalized() * speed)
        target.motion.max_seconds = THROW_MAX_SECONDS
        self._enter(POSITION)

    def _nuke(self, share: float) -> None:
        ability, owner = self.ability, self.owner
        radius = ability.area(NUKE_RADIUS_SHARE, MAX_NUKE_RADIUS)
        nuclear_sphere(ability, owner, center_of(self.target), radius, self._total_damage() * share,
                       ability.force(80.0, 180.0), NUKE_FIRE, NUKE_RING)

    def _after_them(self, dt: float) -> float:
        """Through the air at them, however far the punch has sent them. Returns how far is left."""
        owner = self.owner
        offset = center_of(self.target) - center_of(owner)
        remaining = offset.length() - REACH
        speed = max(MIN_POSITION_SPEED, self.ability.p("speed"))
        if remaining > 0.0:
            here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
            self._leap_to(here + offset.normalized() * remaining, speed, dt)
        return remaining - speed * dt

    def _step_position(self, dt: float) -> bool:
        self._after_them(dt)
        if self.phase_time >= POSITION_SECONDS:
            self.streak.release()
            self._nuke(FIRST_NUKE_SHARE)
            self._enter(CATCH)
        return True

    def _step_catch(self, dt: float) -> bool:
        if self._after_them(dt) <= .05:
            target = self.target
            self.streak.release()
            target.release_motion()
            target.jump_height = target.jump_velocity = 0.0
            target.pose_root.setP(18.0)
            self.grabbed = True
            self.beam_timer = 0.0
            self.ability.game.world.play_power_sound(.35)
            self._enter(BEAM)
        return True

    def _step_beam(self, dt: float) -> bool:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        self._hold()
        owner.left_arm.rotation_x = owner.right_arm.rotation_x = ARM_BRACED
        chest_beam = owner.powers.abilities["chest_beam"]
        center = center_of(target)
        if self.visual is None:
            self.visual = combat.acquire_beam()
        if self.visual is not None:
            self.visual.show((chest_beam.beam_origin(),), center, chest_beam.beam_values()[2],
                             chest_beam.CORE, chest_beam.GLOW, chest_beam.FLARE)
        self._burn(dt)
        self.beam_stored += self._total_damage() * BEAM_DAMAGE_SHARE / BEAM_SECONDS * dt
        self.beam_timer -= dt
        if self.beam_timer <= 0.0:  # in ticks, as the real beam is
            self.beam_timer = BEAM_TRACE_INTERVAL
            combat.hit_character(owner, target, self.beam_stored, RADIATION)
            self.beam_stored = 0.0
        if self.phase_time >= BEAM_SECONDS:
            self._stop_beam()
            if not self._target_gone():
                self._last_throw()
        return True

    def _last_throw(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        self._nuke(FINAL_NUKE_SHARE)
        self._hold()
        self.fall = HurledDown(ability, owner, target, LAST_THROW_SPEED, LAST_THROW_DRIFT)
        target.pose_root.setP(-60.0)
        owner.left_arm.rotation_x = 60.0
        owner.right_arm.rotation_x = 0.0
        self._enter(THROWN_DOWN)

    def _step_thrown_down(self, dt: float) -> bool:
        ability, owner, target = self.ability, self.owner, self.target
        self._burn(dt)
        if self.fall.step(dt, self._total_damage() * OBSTACLE_DAMAGE_SHARE):
            ground_blast(ability, owner, target, self.fall.point, self._total_damage() * LAST_IMPACT_SHARE,
                         LAST_IMPACT_RADIUS, ability.force(40.0, 160.0), NUKE_FIRE, NUKE_RING, "radioactive-execution")
            target.vitals.clear_status("held")
            self.grabbed = False
            self.thrown = True
            self._enter(DESCEND)
        return True

    def _burn(self, dt: float) -> None:
        """Green fire around the target, for as long as it is on fire."""
        ability, target = self.ability, self.target
        center = center_of(target)
        flames = ability.flames
        flames.entity.position = Vec3(center.x, center.y, center.z)
        flames.show(5.0 + sin(self.elapsed * 14.0) * .8, GREEN_FIRE)
        self.flame_timer -= dt
        if self.flame_timer <= 0.0:
            self.flame_timer = FLAME_EVERY
            angle = self.elapsed * 9.0
            ability.combat.puffs.emit(center + SimVec3(sin(angle) * 1.2, -1.0, cos(angle) * 1.2),
                                      SimVec3(0.0, 9.0, 0.0), GREEN_FIRE, size=.9, grow=2.5, life=.5)

    def _step_descend(self, dt: float) -> bool:
        if self.punched and not self.target.vitals.downed and not self.target.parked:
            self._burn(dt)
        return super()._step_descend(dt)

    def _stop_beam(self) -> None:
        if self.visual is not None:
            self.ability.combat.release_beam(self.visual)
            self.visual = None

    def finish(self) -> None:
        self._stop_beam()
        self.ability.flames.hide()
        super().finish()


class RadiationBlast(Ability):
    """Key 1: on until pressed again, and every three seconds a huge green sphere around him.

    The clock keeps running while it is off, so that pressing the key cannot make them come faster.
    """

    ability_id = "radiation_blast"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.wait = 0.0
        self.blasts = 0

    def press(self) -> None:
        if self.active:
            self.active = False
            self.say("RADIATION OFF")
        elif self.usable():
            self.active = True
            self.say("RADIATION ON")

    def update(self, dt: float) -> None:
        self.wait -= dt
        if not self.active:
            self.wait = max(0.0, self.wait)
            return
        if self.vitals.nullified or self.vitals.immobile or self.owner.motion is not None:
            self.wait = max(0.0, self.wait)  # one of his sequences is running, or he cannot use it now
            return
        if self.wait <= 0.0:
            self.wait += RADIATION_SECONDS
            self._detonate()

    def _detonate(self) -> None:
        owner, game = self.owner, self.game
        self.blasts += 1
        radius = self.area(RADIATION_RADIUS_SHARE, MAX_RADIATION_RADIUS)
        point = center_of(owner)
        shake = game.camera_impulse
        self.combat.blast(owner, point, radius, self.p("damage"), self.force(60.0, 160.0), kind=EXPLOSION,
                          crater=(min(RADIATION_CRATER[0], radius * .3), RADIATION_CRATER[1], "radiation"),
                          cracks=True, burst_scale=3.0, tint=NUKE_FIRE, even_damage=True)
        game.camera_impulse = max(shake, RADIATION_SHAKE if owner.controlled else shake)
        for index in range(SHOCKWAVE_PUFFS):
            angle = 2.0 * pi * index / SHOCKWAVE_PUFFS
            self.combat.puffs.emit(point, SimVec3(sin(angle) * radius * .8, 4.0, cos(angle) * radius * .8),
                                   NUKE_RING if index % 2 else SMOKE, size=3.0, grow=radius * .15, life=.7)

    def cancel(self) -> None:
        self.active = False

    def reset(self) -> None:
        super().reset()
        self.active = False
        self.wait = 0.0
        self.blasts = 0

    def hud_state(self) -> str:
        return "ON" if self.active else super().hud_state()


class TimeStopAttack(Ability):
    """Pressed once, at full output. The world's stop and the motion both end with the sequence."""

    sequence = None

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.resume_beam = False

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or self.combat.sequence_running:
            return  # one already running is a motion, so it can never start twice
        target = self.target()
        if target is None:
            self.say("NO ENEMY IN RANGE")
            return
        # Key 1 stays switched on, but its own turning and pose must not fight the sequence.
        chest_beam = owner.powers.abilities["chest_beam"]
        self.resume_beam = chest_beam.active
        chest_beam.cancel()
        seize(owner, target)
        owner.motion = self.sequence(self, target)
        self.say("TIME STOPPED")

    def after_sequence(self) -> None:
        resume, self.resume_beam = self.resume_beam, False
        if resume:
            self.owner.powers.abilities["chest_beam"].press()

    def cancel(self) -> None:
        super().cancel()
        self.resume_beam = False

    def hud_state(self) -> str:
        return "ON" if type(self.owner.motion) is self.sequence else super().hud_state()


class FlyingPunchAttack(TimeStopAttack):
    ability_id = "flying_punch"
    sequence = FlyingPunch


class AerialGrabBlastAttack(TimeStopAttack):
    ability_id = "aerial_grab_blast"
    sequence = AerialGrabBlast


class RadioactiveExecutionAttack(TimeStopAttack):
    ability_id = "radioactive_execution"
    sequence = RadioactiveExecution

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.flames = Bubble(scene, GREEN_FIRE, center=0.0)
