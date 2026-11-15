"""Superman: heat vision, the ground execution, breaths, four visions and Solar Overcharge."""

from __future__ import annotations

from math import atan2, degrees

from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.base import Ability, BeamAbility, ConeAbility, Motion, land
from powers.common import launch_character
from powers.fx import Bubble
from powers.universal import settle
from powers.vitals import ENERGY, EXPLOSION, HEAT, PHYSICAL

FREEZE_SECONDS = 6.0
TELESCOPIC_ZOOM = 4.0
GRAB_DISTANCE = 3.0
GRAB_SECONDS = .25
LIFT_HEIGHT = 45.0         # a target on the ground is carried up first, so it has somewhere to fall
LIFT_SPEED = 90.0
CEILING = 480.0
THROW_DRIFT = .6           # how far sideways the throw lands, per metre of drop
MAX_FALL_SPEED = 500.0     # extreme, yet still seen on screen rather than one frame later
LAND_MARGIN = 40.0
PUNCH_SECONDS = .35
MAX_PUNCH_SPEED = 600.0    # air slows it, so this carries them a long way
MIN_PUNCH_SPEED = 400.0
PUNCH_RISE = .3
CHASE_DELAY = .45          # long enough to see them go
MIN_CHASE_SPEED = 500.0
THROWN_SECONDS = 60.0
BEAM_SECONDS = 2.5
BEAM_TICK = 1.0 / 15.0
BEAM_WIDTH = .3            # at arm's length, in the face: any wider hides them both
PUNCH_DAMAGE_SHARE = .2
IMPACT_DAMAGE_SHARE = .3   # the rest comes from the Heat Vision
IMPACT_RADIUS_SHARE, MAX_IMPACT_RADIUS = .01, 60.0  # of Range
OBSTACLE_DAMAGE_SHARE = .1
FLY_AWAY_SECONDS = .5
MIN_FLY_AWAY_SPEED = 220.0
SEQUENCE_MAX_SECONDS = 30.0
RUSH, HOLD, LIFT, PUNCH, CHASE, REGRIP, BURN, FALL, AWAY = ("rush", "hold", "lift", "punch", "chase", "regrip", "burn",
                                                            "fall", "away")
IN_HIS_GRIP = (HOLD, LIFT, PUNCH, REGRIP, BURN)
VISION_MODES = ("off", "xray", "telescopic", "infrared", "microscopic")
VISION_TINTS = {"xray": (70, 150, 255, 46), "telescopic": (255, 255, 255, 0),
                "infrared": (255, 90, 30, 52), "microscopic": (120, 255, 190, 34)}
VISION_LABELS = {"xray": "X-RAY VISION", "telescopic": "TELESCOPIC VISION",
                 "infrared": "INFRARED VISION", "microscopic": "MICROSCOPIC VISION"}


class HeatVision(BeamAbility):
    ability_id = "heat_vision"

    def beam_values(self):
        return self.p("damage"), self.reach(), self.beam_width()

    def on_beam_hit(self, hit, damage, direction) -> None:
        super().on_beam_hit(hit, damage, direction)
        self.combat.heat_effects(hit, self.owner, intensity=self.boost(.5, 2.0))


class FreezeBreath(ConeAbility):
    ability_id = "freeze_breath"
    PUFF = (190, 230, 255, 170)

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self._ice_timer = 0.0

    def on_character(self, target, direction, seconds) -> None:
        # Speed is how fast the cold takes hold: at 100% a target is solid in a second.
        build = seconds * self.p("speed") * .01
        self.combat.chill(self.owner, target, build, FREEZE_SECONDS, self.p("damage") * seconds)

    def on_object(self, obj, direction, seconds) -> None:
        obj.freeze(FREEZE_SECONDS)

    def on_tree(self, tree, direction, seconds) -> None:
        self.combat.elements.freeze_tree(tree, FREEZE_SECONDS)

    def on_tick(self, origin, direction, reach, seconds) -> None:
        self.combat.elements.extinguish(origin + direction * (reach * .6), reach * .6)
        self._ice_timer -= seconds
        if self._ice_timer > 0.0:
            return
        self._ice_timer = .5
        hit = trace(self.game, origin, direction, reach, ignore=(self.owner,), characters=(),
                    trees=False, objects=False)
        if hit.kind in ("terrain", "water"):
            self.combat.elements.add_ice(hit.point, on_water=hit.kind == "water",
                                         source=self.owner)


class SuperBreath(ConeAbility):
    ability_id = "super_breath"
    PUFF = (235, 240, 250, 110)

    def on_character(self, target, direction, seconds) -> None:
        self.combat.push(target, direction * (self.force(30.0, 300.0) * seconds * 6.0))

    def on_object(self, obj, direction, seconds) -> None:
        if not obj.anchored:
            obj.apply_impulse(direction * (self.force(30.0, 300.0) * seconds))

    def on_tree(self, tree, direction, seconds) -> None:
        self.game.world.damage_tree(tree, self.p("damage") * seconds * .25, direction,
                                    impact_speed=self.force(30.0, 300.0))
        self.combat.elements.extinguish_tree(tree)

    def on_tick(self, origin, direction, reach, seconds) -> None:
        self.combat.elements.extinguish(origin + direction * (reach * .6), reach * .6)
        world = self.game.world
        push = direction * (self.force(30.0, 300.0) * seconds * 2.0)
        for piece in world.debris:
            offset = SimVec3(piece.x - origin.x, piece.y - origin.y, piece.z - origin.z)
            if offset.length() < reach:
                piece.velocity = piece.velocity + push


class KryptonianVision(Ability):
    ability_id = "kryptonian_vision"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.mode = "off"
        self._ghosted = []
        self.inspected = ""

    def press(self) -> None:
        if not self.usable():
            return
        self._apply_mode(VISION_MODES[(VISION_MODES.index(self.mode) + 1) % len(VISION_MODES)])

    def _apply_mode(self, mode: str) -> None:
        self._restore_buildings()
        self.mode = mode
        self.active = mode != "off"
        self.inspected = ""
        hud = self.game.hud
        if not self.owner.controlled:
            return
        rig = self.game.camera
        rig.vision_zoom = {"telescopic": 1.0 / TELESCOPIC_ZOOM, "microscopic": .55}.get(mode, 1.0)
        if mode == "off":
            hud.set_vision(None, "")
            self.combat.markers.hide()
        else:
            hud.set_vision(VISION_TINTS[mode], VISION_LABELS[mode])
            self.say(VISION_LABELS[mode])
        if mode == "xray":
            self._ghost_buildings()
        if mode in ("telescopic", "microscopic"):
            self.combat.markers.hide()

    def _ghost_buildings(self) -> None:
        for building in self.game.world.buildings:
            facade = getattr(building, "facade_detail", None)
            if facade is not None and not building.health.broken:
                facade.setTransparency(True)
                facade.setAlphaScale(.3)
                self._ghosted.append(facade)

    def _restore_buildings(self) -> None:
        for facade in self._ghosted:
            if not facade.is_empty():
                facade.setAlphaScale(1.0)
                facade.setTransparency(False)
        self._ghosted = []

    def cancel(self) -> None:
        if self.mode != "off":
            self._apply_mode("off")

    def update(self, dt: float) -> None:
        if self.mode == "off" or not self.owner.controlled:
            return
        if self.vitals.immobile:
            self.cancel()
            return
        combat = self.combat
        if self.mode == "microscopic":
            self.inspected = self._inspect()
            self.game.hud.set_vision(VISION_TINTS[self.mode],
                                     f"MICROSCOPIC: {self.inspected}")
        elif self.mode == "xray":
            combat.mark(self.owner, combat.hostiles_of(self.owner), self.reach(),
                        (90, 190, 255, 240))
        elif self.mode == "infrared":
            combat.mark(self.owner, combat.others_of(self.owner), self.reach(),
                        (255, 120, 30, 240), extra=combat.elements.heat_sources())

    def _inspect(self) -> str:
        target = self.target()
        if target is not None:
            vitals = target.vitals
            return f"{target.display_name} {vitals.health:.0f}/{vitals.max_health:.0f} hp"
        hit = self.aim_hit(self.reach())
        if hit.kind == "object":
            health = hit.target.health
            return f"{hit.target.display_name} {health.health:.0f}/{health.maximum_health:.0f}"
        if hit.kind == "tree":
            return f"Tree {hit.target.tree_health:.0f}/{hit.target.tree_max_health:.0f}"
        return "ground" if hit.kind == "terrain" else ("water" if hit.kind == "water" else "nothing")


class ExecutionSequence(Motion):
    """Key 4: rush, grab, lift, punch them away, catch them, Heat Vision in the face, hurl down, leave."""

    def __init__(self, ability, target) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.target = target
        self.phase = RUSH
        self.phase_time = 0.0
        self.was_flying = self.owner.flight.is_flying
        self.point = SimVec3()
        self.top = 0.0
        self.fall_speed = 0.0
        self.fall_clear = False
        self.landed = False
        self.beam = None
        self.beam_stored = 0.0
        self.beam_timer = 0.0
        self.damage_dealt = 0.0
        self.stages = [RUSH]
        self.caught_above = 0.0
        self.owner.flight.phase = FlightPhase.CRUISE
        self.owner.flight.phase_time = 0.0
        # World time is stopped, but what this sets off has to play out, not hang on screen.
        self.frozen_bursts = set(ability.game.world._active_explosions)
        ability.combat.begin_time_stop(self.owner, target)

    # -- shared steps ----------------------------------------------------
    def _enter(self, phase: str) -> None:
        self.phase = phase
        self.phase_time = 0.0
        self.stages.append(phase)

    def _target_gone(self) -> bool:
        target = self.target
        return (target.parked or target.vitals.downed
                or not self.ability.combat.hostile(self.owner, target))

    def _damage(self) -> float:
        powers = self.owner.powers
        return self.ability.p("damage") * powers.strength * powers.attack_scale

    def _fly_to(self, point: SimVec3, speed: float, dt: float, ignore=()) -> float:
        """Fly straight at a point, breaking through whatever is in the way; returns distance left."""
        owner, ability = self.owner, self.ability
        here = SimVec3(owner.x, owner.y, owner.z)
        offset = point - here
        distance = offset.length()
        step = min(speed * dt, distance)
        if step <= 1e-6:
            return distance
        direction = offset.normalized()
        hit = trace(ability.game, center_of(owner), direction, step + 1.0, ignore=(owner, self.target, *ignore),
                    characters=(), terrain=False)
        if hit.kind in ("object", "tree"):
            ability.combat.damage_hit(owner, hit, self._damage() * OBSTACLE_DAMAGE_SHARE, direction,
                                      kind=PHYSICAL, force=20.0)
        velocity = direction * (step / max(dt, 1e-4))
        self._move(velocity, dt)
        owner.flight.velocity = velocity
        return distance - step

    def _hold_by_the_neck(self, height: float = .55) -> None:
        owner, target = self.owner, self.target
        offset = SimVec3(target.x - owner.x, 0.0, target.z - owner.z)
        side = offset.normalized() if offset.length() > 1e-3 else self.ability.facing()
        target.position = (owner.x + side.x * GRAB_DISTANCE, owner.y + height, owner.z + side.z * GRAB_DISTANCE)
        owner.right_arm.rotation_x = -150.0

    def _face_target(self) -> None:
        owner, target = self.owner, self.target
        self.facing = degrees(atan2(target.x - owner.x, target.z - owner.z))

    # -- the sequence ----------------------------------------------------
    def step(self, dt: float) -> bool:
        self.elapsed += dt
        self.phase_time += dt
        target = self.target
        world = self.ability.game.world
        if self.ability.combat.time_stopped:  # a running world steps its own
            for burst in tuple(world._active_explosions):
                if burst not in self.frozen_bursts:
                    burst.step(dt)
        if self.phase != AWAY:
            if self._target_gone() or self.elapsed > SEQUENCE_MAX_SECONDS:
                self._start_away()
            else:
                target.vitals.add_status("held", .2)
                self._face_target()
        return getattr(self, f"_step_{self.phase}")(dt)

    def _step_rush(self, dt: float) -> bool:
        offset = center_of(self.target) - center_of(self.owner)
        # The margin matters: flying to exactly the grab distance can stop a rounding error short.
        if offset.length() <= GRAB_DISTANCE + .05:
            self._enter(HOLD)
            self.ability.game.world.play_power_sound(.3)
            return True
        aim = SimVec3(self.target.x, self.target.y, self.target.z)
        remaining = offset.length() - GRAB_DISTANCE
        here = SimVec3(self.owner.x, self.owner.y, self.owner.z)
        self._fly_to(here + (aim - here).normalized() * remaining, self.ability.p("speed"), dt)
        return True

    def _step_hold(self, dt: float) -> bool:
        self._hold_by_the_neck()
        self.owner.flight.velocity = SimVec3()
        if self.phase_time >= GRAB_SECONDS:
            ground = self.ability.game.world.height_at(self.owner.x, self.owner.z)
            self.top = min(CEILING, max(float(self.owner.y), ground + LIFT_HEIGHT))
            self._enter(LIFT)
        return True

    def _step_lift(self, dt: float) -> bool:
        owner = self.owner
        if owner.y < self.top:
            speed = min(LIFT_SPEED, self.ability.p("speed"))
            self._move(SimVec3(0.0, speed, 0.0), dt)
            owner.flight.velocity = SimVec3(0.0, speed, 0.0)
            self._hold_by_the_neck()
            return True
        owner.flight.velocity = SimVec3()
        self._enter(PUNCH)
        return True

    def _step_punch(self, dt: float) -> bool:
        owner = self.owner
        self._hold_by_the_neck()
        owner.flight.velocity = SimVec3()
        progress = min(1.0, self.phase_time / PUNCH_SECONDS)
        owner.left_arm.rotation_x = 45.0 - 215.0 * progress
        if progress >= 1.0:
            self._punch()
        return True

    def _punch(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        self.damage_dealt += combat.hit_character(owner, target, self._damage() * PUNCH_DAMAGE_SHARE, PHYSICAL)
        combat.burst(center_of(target), 14.0, 2.0, (255, 235, 200))
        ability.game.camera_impulse = max(ability.game.camera_impulse, 2.0)
        ability.game.world.play_power_sound(.8)
        side = SimVec3(target.x - owner.x, 0.0, target.z - owner.z)
        side = side.normalized() if side.length() > 1e-3 else ability.facing()
        speed = min(MAX_PUNCH_SPEED, max(MIN_PUNCH_SPEED, ability.p("speed")))
        launch_character(owner, target, (side + SimVec3(0.0, PUNCH_RISE, 0.0)).normalized() * speed)
        target.motion.max_seconds = THROWN_SECONDS
        owner.left_arm.rotation_x = 0.0
        self._enter(CHASE)

    def _step_chase(self, dt: float) -> bool:
        """After them, before they reach the ground, at whatever speed that takes."""
        ability, owner, target = self.ability, self.owner, self.target
        owner.flight.velocity = SimVec3()
        if self.phase_time < CHASE_DELAY:
            return True
        speed = max(MIN_CHASE_SPEED, ability.p("speed"))
        offset = center_of(target) - center_of(owner)
        remaining = offset.length() - GRAB_DISTANCE
        if remaining > speed * dt + .05:
            here = SimVec3(owner.x, owner.y, owner.z)
            self._fly_to(here + offset.normalized() * remaining, speed, dt)
            return True
        self.caught_above = float(target.y) - ability.game.world.height_at(target.x, target.z)
        target.release_motion()
        target.jump_height = target.jump_velocity = 0.0
        target.knock = SimVec3()
        target.pose_root.setP(18.0)
        ability.game.world.play_power_sound(.35)
        self._enter(REGRIP)
        return True

    def _step_regrip(self, dt: float) -> bool:
        self._hold_by_the_neck(0.0)
        self.owner.flight.velocity = SimVec3()
        if self.phase_time >= GRAB_SECONDS:
            self.beam_timer = 0.0
            self.ability.combat.elements.add_scorch(SimVec3(float(self.target.x), self.ability.game.world.height_at(float(self.target.x), float(self.target.z)), float(self.target.z)), 3.0)
            self._enter(BURN)
        return True

    def _throw(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        game = ability.game
        side = SimVec3(target.x - owner.x, 0.0, target.z - owner.z)
        side = side.normalized() if side.length() > 1e-3 else ability.facing()
        drop = max(1.0, float(target.y) - game.world.height_at(target.x, target.z))
        x, z = game.planet.clamp_to_land(target.x + side.x * drop * THROW_DRIFT,
                                         target.z + side.z * drop * THROW_DRIFT, LAND_MARGIN)
        self.point = SimVec3(x, game.world.height_at(x, z) + .25, z)
        self.fall_speed = min(MAX_FALL_SPEED, max(MIN_PUNCH_SPEED, ability.p("speed")))
        target.pose_root.setP(-60.0)
        owner.right_arm.rotation_x = 60.0
        game.world.play_power_sound(.35)
        self._enter(FALL)

    def _step_fall(self, dt: float) -> bool:
        self.owner.flight.velocity = SimVec3()
        if not self.landed:
            self._fall(dt)
        if self.landed and not self._target_gone():
            self.target.pose_root.setP(-82.0)
            self._start_away()
        return True

    def _fall(self, dt: float) -> None:
        ability, target = self.ability, self.target
        here = SimVec3(float(target.x), float(target.y), float(target.z))
        offset = self.point - here
        distance = offset.length()
        step = self.fall_speed * dt
        if distance <= step:
            target.position = (self.point.x, self.point.y, self.point.z)
            self._impact()
            return
        direction = offset.normalized()
        if not self.fall_clear:
            hit = trace(ability.game, here, direction, step + 1.0, ignore=(target, self.owner), characters=(),
                        terrain=False)
            if hit.kind in ("object", "tree"):
                ability.combat.damage_hit(self.owner, hit, self._damage() * OBSTACLE_DAMAGE_SHARE, direction,
                                          kind=PHYSICAL, force=30.0)
                if hit.kind == "object" and not hit.target.health.broken:
                    # It held: straight down its side from here, rather than through it.
                    self.fall_clear = True
                    world = ability.game.world
                    self.point = SimVec3(here.x, world.height_at(here.x, here.z) + .25, here.z)
        moved = here + direction * step
        target.position = (moved.x, moved.y, moved.z)

    def _impact(self) -> None:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        self.landed = True
        land(target)
        point = SimVec3(float(target.x), float(target.y), float(target.z))
        radius = ability.area(IMPACT_RADIUS_SHARE, MAX_IMPACT_RADIUS)
        damage = self._damage() * IMPACT_DAMAGE_SHARE
        self.damage_dealt += combat.hit_character(owner, target, damage, PHYSICAL)
        combat.blast(owner, point, radius, damage, ability.force(30.0, 120.0), kind=EXPLOSION,
                     crater=(min(18.0, radius * .5), 3.0, "execution"), cracks=True, burst_scale=2.5,
                     ignore=(target,))
        # World time is stopped, but this crater should show now, not when it resumes.
        ability.game.world._terrain_rebuild_wait = 0.0
        combat.puffs.emit(point, SimVec3(0.0, 8.0, 0.0), (190, 170, 140, 220), size=2.0, grow=9.0, life=.7)

    def _step_burn(self, dt: float) -> bool:
        ability, owner, target = self.ability, self.owner, self.target
        combat = ability.combat
        self._hold_by_the_neck(0.0)
        owner.flight.velocity = SimVec3()
        share = (1.0 - IMPACT_DAMAGE_SHARE - PUNCH_DAMAGE_SHARE) / BEAM_SECONDS
        self.beam_stored += self._beam_damage() * share * dt
        self.beam_timer -= dt
        left, right = target.eye_points()
        face = SimVec3((left.x + right.x) * .5, (left.y + right.y) * .5, (left.z + right.z) * .5)
        if self.beam is None:
            self.beam = combat.acquire_beam()
        done = self.phase_time >= BEAM_SECONDS
        if self.beam_timer <= 0.0 or done:
            self.beam_timer = BEAM_TICK
            self.damage_dealt += combat.hit_character(owner, target, self.beam_stored, HEAT)
            self.beam_stored = 0.0
            combat.puffs.emit(face, SimVec3(0.0, 4.0, 0.0), (255, 150, 60, 220), size=.4, grow=1.2, life=.3)
        if self.beam is not None:
            self.beam.show(owner.eye_points(), face, BEAM_WIDTH, BeamAbility.CORE, BeamAbility.GLOW)
        if done:
            self._stop_beam()
            if not self._target_gone():
                self._throw()
        return True

    def _beam_damage(self) -> float:
        return self.ability.p("damage") * self.owner.powers.energy_scale * self.owner.powers.strength

    def _start_away(self) -> None:
        self._stop_beam()
        self._release_target()
        self.facing = None
        self._enter(AWAY)

    def _step_away(self, dt: float) -> bool:
        owner = self.owner
        away = SimVec3(owner.x - self.target.x, 0.0, owner.z - self.target.z)
        away = away.normalized() if away.length() > 1e-3 else SimVec3(1.0, 0.0, 0.0)
        velocity = (away + SimVec3(0.0, 1.0, 0.0)).normalized() * max(MIN_FLY_AWAY_SPEED,
                                                                      self.ability.p("speed") * .3)
        self._move(velocity, dt)
        owner.flight.velocity = velocity
        return self.phase_time < FLY_AWAY_SECONDS

    # -- leaving everything as it was ------------------------------------
    def _stop_beam(self) -> None:
        if self.beam is not None:
            self.ability.combat.release_beam(self.beam)
            self.beam = None

    def _release_target(self) -> None:
        target = self.target
        target.vitals.clear_status("held")
        if not target.vitals.downed and self.phase != AWAY:
            target.pose_root.setP(0.0)
        if self.phase == FALL or self.landed:
            land(target)  # never left hanging part-way down
        elif self.phase in IN_HIS_GRIP and not target.parked:
            launch_character(self.owner, target, SimVec3())

    def finish(self) -> None:
        """Runs however the sequence ends, even a character switch part-way through."""
        self._stop_beam()
        if self.phase != AWAY:
            self._release_target()
        self.owner.right_arm.rotation_x = self.owner.left_arm.rotation_x = 0.0
        self.ability.combat.end_time_stop(self.owner)
        settle(self.owner, self.was_flying)


class GroundExecution(Ability):
    ability_id = "ground_execution"

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or not owner.flight_allowed:
            return  # a sequence already running is a motion, so it can never start twice
        target = self.target()
        if target is None:
            self.say("NO ENEMY IN RANGE")
            return
        target.powers.cancel_all()
        target.release_motion()
        target.knock = SimVec3()
        target.jump_velocity = 0.0
        owner.motion = ExecutionSequence(self, target)
        self.say("TIME STOPPED")

    def hud_state(self) -> str:
        return "ON" if isinstance(self.owner.motion, ExecutionSequence) else super().hud_state()


class SolarOvercharge(Ability):
    ability_id = "solar_overcharge"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.aura = Bubble(owner, (255, 216, 90, 0))

    @property
    def damage_scale(self) -> float:
        return self.boost(1.2, 2.5) if self.active else 1.0

    def press(self) -> None:
        if self.active:
            self._end()
        elif self.usable():
            self._discharge()

    def update(self, dt: float) -> None:
        if self.active:
            if self.vitals.downed:
                self._end()
            else:
                self.aura.show(3.4, (255, 216, 90, 55))

    def _discharge(self) -> None:
        self.active = True
        self.say("SOLAR OVERCHARGE")
        owner = self.owner
        radius = self.area(.1, 120.0)
        self.combat.blast(owner, center_of(owner), radius, self.p("damage"), self.force(30.0, 150.0),
                          kind=ENERGY, crater=(min(30.0, radius * .35), 2.2, "solar"), cracks=True,
                          burst_scale=1.4)

    def _end(self) -> None:
        self.active = False
        self.aura.hide()

    def cancel(self) -> None:
        self._end()
