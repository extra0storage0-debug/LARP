"""A roster character: the shared body and movement, flown by the player or by AI.

SentryCharacter only reaches the outside world through ``self.game``. Pointing that at
the real game hands the character to the player, and pointing it at a CharacterContext
hands it to AI, with no second controller and no respawn.
"""

from __future__ import annotations

from math import atan2, degrees, exp, sqrt
from random import Random

from ursina import Vec3, camera
from ursina.collider import BoxCollider

from ai.combat_ai import CINEMATIC_IDS, CLOSE_METRES, MOVES, Situation, choose_move
from characters.sentry import JUMP_GRAVITY, MAX_JUMP_SPEED
from ai.enemy_team_ai import (AgentView, EnemyBrain, Intent, Personality, CEILING,
                              steer_flight, terrain_safe_altitude)
from characters.registry import BASE_BODY
from characters.roster import KITS, kit_of
from characters.sentry import SentryCharacter
from characters.sentry_clone import (CLONE_PALETTES, CloneVisual, CostumePalette, NEAR_DISTANCE, SENTRY_COPY_PALETTE,
                                      SQUAD_PALETTES)
from characters.skinned_visual import SkinnedVisual, is_available
from combat.sentry_combat import BoostGate
from config.character_roster import FLIGHT_BOOSTS, FLIGHT_SPEEDS
from config.power_schema import BOOST_SPEED, CHARACTER, FLY_SPEED, RUN_SPEED
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from characters.sentry import POSE_SETTLE_SECONDS
from movement.flight_pose import blend_amount
from powers.aiming import center_of, trace
from powers.common import DashMotion
from powers.loadout import PowerSet
from world.destruction_math import sweep_point_aabb

FAR_SIMULATION_DISTANCE = 350.0
FAR_STEP_SECONDS = .1
TRAVEL_CLEARANCE = 24.0
NEAR_CLEARANCE = 4.0
KNOCK_DECAY = 3.0
DUST = (190, 172, 142, 150)
FOOTSTEP_VOLUME = .035
MAX_POSTURE_SPEED, RUSH_LEGS_SPEED = 20000.0, 12.0  # beyond the first, a teleport-like jump between frames says nothing
RUNNING_WIND = 3.5  # a running body's cape streams behind it, as a flying one's does
VAPOUR = (235, 240, 248, 70)
VAPOUR_SPEED, VAPOUR_EVERY, SOUND_SPEED = 150.0, .09, 340.0
EYE_HEIGHT = 2.5
AI_ATTACK_GAP = (1.4, 4.0)
AI_GRACE_SECONDS = 8.0   # a moment to look around before anyone attacks
MAX_LAUNCH_SPEED = 26.0  # how hard a blast can throw someone standing on the ground
MAX_FLYING_KNOCK = 600.0
FAST_TARGET = 30.0       # metres per second
OUTRUN_SHARE = 1.1       # Soldier Boy's top running speed, against the fastest anyone can fly
RUN_ACCELERATION = 25.0  # his top speed, per second, on the ground: there in about a tenth of a second
AIR_ACCELERATION = 1.2   # and in the air, where there is nothing to push against
GROUNDED, FLYING, SUPER_JUMPING = "GROUNDED", "FLYING", "SUPER_JUMPING"
SLAM_FROM = 30.0         # metres away along the ground, for AI to come down on someone
SLAM_ABOVE = 6.0         # metres over them, at least
SLAM_CHANCE = .35
# AI's super jump. It leaps when the fight is up in the air or a long way off, and not otherwise.
LEAP_UP_FOR = 6.0        # metres of height difference
LEAP_ACROSS_FOR = 90.0   # metres away along the ground
LEAP_MIN_GAP = 1.0       # seconds, so that it lands and fights rather than bouncing all the time
LEAP_CLEARANCE = 3.0     # metres over the target
LEAP_ACROSS_RISE = 28.0  # metres per second, going across to someone on the ground
MAX_LEAP_ACROSS = 500.0  # metres per second


class AICamera:
    """Answers SentryCharacter's camera-heading reads with the AI's facing."""

    __slots__ = ("yaw",)

    def __init__(self) -> None:
        self.yaw = 0.0


class AIWorld:
    """World view for one AI character, with collision limited to nearby trees."""

    def __init__(self, team) -> None:
        self._team = team
        self._world = team.game.world

    def __getattr__(self, name):
        return getattr(self._world, name)

    def resolve_sentry(self, sentry, *, previous_position=None) -> None:
        world = self._world
        end = SimVec3(sentry.x, sentry.y, sentry.z)
        start = previous_position if previous_position is not None else end
        self._team.trees.sweep(sentry, start, end)
        self._stop_at_buildings(sentry, start, end)
        clamp_to_world(sentry, world, world.planet)

    def _stop_at_buildings(self, sentry, start: SimVec3, end: SimVec3) -> None:
        """AI characters go around standing structures rather than through them."""
        a, b = (start.x, start.y, start.z), (end.x, end.y, end.z)
        for obj in self._world._nearby_objects(end.x, end.z, 0):
            if not obj.anchored or obj.health.broken:
                continue
            half_x, half_y, half_z = (abs(obj.scale_x) * .5 + .48, abs(obj.scale_y) * .5 + 1.05,
                                      abs(obj.scale_z) * .5 + .48)
            hit = sweep_point_aabb(a, b, (obj.x - half_x, obj.y - half_y, obj.z - half_z),
                                   (obj.x + half_x, obj.y + half_y, obj.z + half_z))
            if hit is not None:
                t, normal = hit
                center = start + (end - start) * t
                sentry.position = (center.x + normal[0] * .025, center.y + normal[1] * .025,
                                   center.z + normal[2] * .025)
                return


def clamp_to_world(character, world, planet) -> None:
    """Apply the island boundary, terrain floor and 500 m ceiling."""
    x, z = planet.clamp_to_land(character.x, character.z)
    character.x, character.z = x, z
    floor = world.height_at(x, z) + .25
    if character.keeps_own_height:  # a super jump has no ceiling, and only has to stay above the ground
        character.y = max(float(character.y), floor)
        return
    if not character.flight.is_flying:
        character.y = floor + character.jump_height
        if character.flight.velocity.y < 0.0:
            character.flight.velocity.y = 0.0
    elif character.y < floor:
        character.y = floor
        if character.flight.velocity.y < 0.0:
            character.flight.velocity.y = 0.0
    if character.y > planet.MAX_FLIGHT_ALTITUDE:
        character.y = planet.MAX_FLIGHT_ALTITUDE
        if character.flight.velocity.y > 0.0:
            character.flight.velocity.y = 0.0


class CharacterContext:
    """The ``game`` object an AI character sees while nobody is controlling it."""

    def __init__(self, team, kit, palette: CostumePalette | None) -> None:
        self.team = team
        self.kit = kit
        self.palette = palette
        self._game = team.game
        self.sentry = None
        self.camera = AICamera()
        self.world = AIWorld(team)

    def __getattr__(self, name):
        return getattr(self._game, name)

    @property
    def sentry_config(self):
        return self.team.power_config

    @property
    def tuning(self):
        return self.team.ai_view

    def notify(self, *_args, **_kwargs) -> None:
        return None


def skinned_bodies_ready() -> bool:
    """Every baked body or none: a mix of the two would look like two different games."""
    return all(is_available(palette.name) for palette in (SENTRY_COPY_PALETTE, *CLONE_PALETTES, *SQUAD_PALETTES))


class RosterCharacter(SentryCharacter):
    POWERS = PowerSet
    ai_moves = None    # whose list of AI moves, if not its own character's
    own_run_speed = 0.0
    falling_from_blow = False  # out of a tumble and still coming down: F recovers into flight, it does not slam
    default_run_speed = default_fly_speed = default_boost_speed = 0.0  # what its profile and passives come to, before any chosen speed
    _kit = None
    team = None
    controlled = False
    parked = False
    powers = None
    vitals = None
    motion = None
    ai_target = None

    def __init__(self, team, palette: CostumePalette, personality: Personality,
                 position, seed: int) -> None:
        context = CharacterContext(team, kit_of(palette.name), palette)
        super().__init__(context, position=position, name=f"{palette.name.lower()}-character")
        self._kit = context.kit
        self.palette = palette
        self.reentry_glow.hide()
        self.collider = BoxCollider(self, center=Vec3(0, 1.4, 0), size=Vec3(2.6, 3.8, 2.6))
        self._attach(team, context, personality, seed, position)

    def _attach(self, team, context, personality: Personality, seed: int, position) -> None:
        self.team = team
        self._was_airborne = False
        self._motion_from = SimVec3(*position)
        self._vapour_wait = 0.0
        self._through_sound = False
        self._fall_speed = 0.0
        self._body_yaw = 0.0
        self._body_pace = 0.0
        self.context = context
        self.character_id = self.kit.character_id
        self.display_name = self.kit.display
        context.sentry = self
        self.tuning = context.tuning if not self.controlled else self.tuning
        self.boost_gate = BoostGate()
        self.brain = EnemyBrain(self.character_id, personality, seed=seed)
        self.brain.tuning = team.ai_tuning
        self.brain.can_fly = self.kit.can_fly
        self.view = AgentView(self.character_id, SimVec3(*position), SimVec3())
        self.intent: Intent | None = None
        self._rng = Random(seed)
        self.next_decision = 0.0
        self._next_mode_change = 0.0
        self._safe_altitude = 0.0
        self._cape_timer = 0.0
        self._far_timer = 0.0
        self._stuck_timer = 0.0
        self._stuck_from = SimVec3(*position)
        self._unstuck_until = 0.0
        self.knock = SimVec3()
        self.powers = self.POWERS(self)
        self._ai_move = None
        self._ai_uses: dict[str, int] = {}
        self._next_leap = 0.0
        self._ai_hold_left = 0.0
        self._ai_next_attack = AI_GRACE_SECONDS + seed % 7 * .5

    def _build_body(self) -> None:
        self.parts = {}
        if skinned_bodies_ready():
            self.visual = SkinnedVisual(self, self._visual_name())
        else:
            self.visual = CloneVisual(self, self.game.team.clone_assets, self.game.palette)
        self.pose_root = self.visual.pose_root
        self.left_arm = self.visual.left_arm
        self.right_arm = self.visual.right_arm
        self.left_elbow = self.visual.left_elbow
        self.right_elbow = self.visual.right_elbow
        self.left_leg = self.visual.left_leg
        self.right_leg = self.visual.right_leg
        self.cape = self.visual.cape
        self.hair_locks = self.visual.lock_joints
        self.eye_left = self.visual.eye_left
        self.eye_right = self.visual.eye_right

    def _visual_name(self) -> str:
        return self.game.palette.name

    def _react_to_ground(self, airborne: bool) -> None:
        """The legs take a landing and gather for a leap, and big arrivals and departures raise the dust."""
        if airborne == self._was_airborne:
            self._fall_speed = max(self._fall_speed, -min(self.jump_velocity, self.flight.velocity.y if self.flight.is_flying else 0.0))
            return
        self._was_airborne = airborne
        team, combat = self.team, getattr(self.team.game if self.team else None, "combat", None)
        point = SimVec3(float(self.x), float(self.y) - .2, float(self.z))
        if airborne:
            self.visual.squat(.75)  # a leap or a take-off starts from bent knees
            if combat is not None and team is not None and team.game.elapsed > 1.0:
                combat.puffs.emit(point, SimVec3(0.0, 3.0, 0.0), DUST, size=.9, grow=4.0, life=.45)
        else:
            self.visual.squat(min(1.0, .3 + self._fall_speed / 26.0))
            if combat is not None and self._fall_speed > 7.0:
                combat.puffs.emit(point, SimVec3(0.0, 2.0, 0.0), DUST, size=.9, grow=min(9.0, 3.0 + self._fall_speed * .1), life=.5)
        self._fall_speed = 0.0

    def _flight_effects(self, seconds: float) -> None:
        """Air streaming off the body at speed, and one boom on the way through the speed of sound."""
        combat = self.team.game.combat
        speed = self.flight.speed_mps
        if combat is None:
            return
        if speed > VAPOUR_SPEED:
            self._vapour_wait -= seconds
            if self._vapour_wait <= 0.0:
                self._vapour_wait = VAPOUR_EVERY
                combat.puffs.emit(SimVec3(float(self.x), float(self.y) + 1.4, float(self.z)), self.flight.velocity * .12, VAPOUR, size=.9, grow=5.0, life=.35)
        if speed > SOUND_SPEED and not self._through_sound:
            self._through_sound = True
            combat.puffs.emit(SimVec3(float(self.x), float(self.y) + 1.4, float(self.z)), self.flight.velocity * .2, VAPOUR, size=2.5, grow=26.0, life=.5)
            self.team.game.world.play_power_sound(.4)
            self.team.game.camera_impulse = max(self.team.game.camera_impulse, .9)
        elif speed < SOUND_SPEED * .7:
            self._through_sound = False

    def _on_footfall(self, pace: float) -> None:
        """A running foot kicks up dust, more the harder it runs; the player also hears their own."""
        if self.team is None or not self.visual.is_near:
            return
        combat = self.team.game.combat
        if combat is None:
            return
        if pace > 13.0:
            point = SimVec3(float(self.x), float(self.y) - .15, float(self.z))
            combat.puffs.emit(point, SimVec3(0.0, 1.4, 0.0), DUST, size=.3 + min(.6, pace * .004), grow=2.2, life=.32)
        if self.controlled and pace > 6.0:
            self.team.game.world.play_power_sound(FOOTSTEP_VOLUME)

    # -- capabilities ----------------------------------------------------
    @property
    def kit(self):
        return self._kit or self.game.kit

    @property
    def uses_skinned_body(self) -> bool:
        return isinstance(getattr(self, "visual", None), SkinnedVisual)

    @property
    def has_super_jump(self) -> bool:
        return self.kit.super_jump

    @property
    def flight_status(self) -> str:
        return "AIRBORNE" if self.keeps_own_height else super().flight_status

    @property
    def movement_state(self) -> str:
        """The one state F and the body's movement answer to, read straight from what is really going on."""
        state = self.motion.movement_state if self.motion is not None else None
        if state is not None:
            return state
        if self.flight.is_flying:
            return FLYING
        return SUPER_JUMPING if self.keeps_own_height else GROUNDED

    def _outrun_everyone(self) -> None:
        """Faster on foot than anyone can fly, boosted, at whatever their flight settings are right now."""
        team = self.team
        if team is None:
            return
        fastest = max((max(body.flight.config.boost_speed, body.flight.config.cruise_speed)
                       for body in (*team.characters.values(), *team._squad) if body.kit.can_fly), default=0.0)
        run = max(self.ground.walk_speed, self.own_run_speed, fastest * OUTRUN_SHARE)
        ground = self.ground
        ground.max_running_speed = run
        ground.sprint_multiplier = run / max(1.0, ground.walk_speed)
        ground.acceleration = run * RUN_ACCELERATION
        ground.air_acceleration = run * AIR_ACCELERATION

    @property
    def flight_allowed(self) -> bool:
        """Soldier Boy's answer is always False, whatever a save or AI asks for."""
        if not self.kit.can_fly:
            return False
        if self.vitals is not None and self.vitals.nullified:
            return False  # Compound V removed: this also takes flight away
        return self.team is None or self.team.state.flight_allowed(self.kit.character_id)

    def apply_sentry_config(self) -> None:
        super().apply_sentry_config()
        self.flight.allowed = self.flight_allowed
        team = self.team
        if team is None:
            return
        settings = team.state.settings(self.kit.character_id)
        scale = FLIGHT_SPEEDS[settings["flight_speed"]]
        boost = FLIGHT_BOOSTS[settings["flight_boost"]]
        fc = self.flight.config
        fc.cruise_speed *= scale
        fc.boost_speed *= scale * boost
        fc.acceleration *= scale
        fc.boost_acceleration *= scale * boost
        self.visual.set_helmet(settings["helmet"])
        if self.powers is not None:
            speed = self.powers.speed
            fc.cruise_speed *= speed
            fc.boost_speed *= speed
            self.ground.walk_speed *= speed
            self.ground.max_running_speed *= speed
        self._apply_chosen_speeds()

    def _apply_chosen_speeds(self) -> None:
        """Running and Flying Speed from the configuration menu, for player and AI alike, if they have been set.

        Everything else about moving scales with them, so that boost stays the same multiple of Flying Speed,
        and the feel of it stays the same at any speed.
        """
        ground, fc = self.ground, self.flight.config
        top = min(ground.max_running_speed, ground.walk_speed * ground.sprint_multiplier)
        self.default_run_speed, self.default_fly_speed = top, fc.cruise_speed
        self.own_run_speed = top
        combat = self.team.game.combat
        if combat is None or self.ai_moves is not None:
            return
        run = combat.settings.chosen(self.kit.character_id, CHARACTER, RUN_SPEED)
        if run is not None:
            scale = run / max(top, 1e-3)
            ground.walk_speed *= scale
            ground.acceleration *= scale
            ground.max_running_speed = run
            ground.sprint_multiplier = run / max(ground.walk_speed, 1e-3)
            self.own_run_speed = run
        fly = combat.settings.chosen(self.kit.character_id, CHARACTER, FLY_SPEED)
        if fly is not None and self.kit.can_fly:
            scale = fly / max(fc.cruise_speed, 1e-3)
            fc.cruise_speed = fly
            fc.boost_speed *= scale
            fc.acceleration *= scale
            fc.boost_acceleration *= scale
        self.default_boost_speed = fc.boost_speed
        boost = combat.settings.chosen(self.kit.character_id, CHARACTER, BOOST_SPEED)
        if boost is not None and self.kit.can_fly:
            scale = max(boost, fc.cruise_speed) / max(fc.boost_speed, 1e-3)  # a boost is never slower than cruising
            fc.boost_speed *= scale
            fc.boost_acceleration *= scale

    def enforce_flight(self) -> None:
        """The capability check every movement path passes through, once per step."""
        flight = self.flight
        flight.allowed = self.flight_allowed
        if flight.allowed or flight.phase is FlightPhase.GROUNDED:
            return
        if self.kit.can_fly:
            if flight.phase is not FlightPhase.LANDING:  # flight switched off in the air
                flight.phase = FlightPhase.LANDING
                flight.phase_time = 0.0
            return
        flight.phase = FlightPhase.GROUNDED
        flight.phase_time = 0.0
        flight.velocity = SimVec3()

    def simulate(self, dt: float, move, vertical: float, **options) -> None:
        if self.jump_height <= 0.0:
            self.falling_from_blow = False
        self.enforce_flight()
        self.jump_held = vertical > 0.0
        if self.has_super_jump:
            self._outrun_everyone()
        if not self.flight_allowed:
            vertical = 0.0
        vitals = self.vitals
        if vitals is not None:
            if self.motion is not None:
                if (self.motion.ballistic or not vitals.immobile) and self.motion.step(dt):
                    if self.motion is not None:  # going down in its own attack ends the motion from inside
                        self._after_motion(dt)
                    return
                self.release_motion()
            if vitals.has("held"):
                return  # whoever is holding this character sets its position
            if vitals.immobile:
                move, vertical = SimVec3(), 0.0
                options.update(boost=False, sprint=False, steering_direction=None)
                if self.flight.is_flying and not vitals.downed:
                    self.flight.velocity = SimVec3()
            else:
                scale = vitals.speed_scale
                if scale != 1.0:
                    move = move * scale
            self._step_knock(dt)
        super().simulate(dt, move, vertical, **options)
        if vitals is not None and vitals.downed:
            self.pose_root.setP(-82.0)

    def _after_motion(self, dt: float) -> None:
        """A dash, charge or dive moved the body; keep its facing, pose and cape going."""
        position = SimVec3(self.x, self.y, self.z)
        planet = self.game.planet
        up = planet.normal(position)
        facing = self.motion.facing
        self.local_yaw = self.game.camera.yaw if facing is None else facing
        planet.orient_entity(self, position, self.local_yaw)
        self._update_airflow(dt, up)
        if not self.motion.ballistic:  # a thrown body tumbles; it does not hold a flying pose
            # A rush moves the body directly, without flight: the lean has to come from where it is really going.
            here = position
            seconds = max(dt, 1e-3)
            travel = SimVec3((here.x - self._motion_from.x) / seconds, (here.y - self._motion_from.y) / seconds,
                             (here.z - self._motion_from.z) / seconds)
            self._motion_from = here
            self._update_flight_posture(dt, up, velocity=travel if travel.length() < MAX_POSTURE_SPEED else None)
            self._hold_legs(1.0 if travel.length() > RUSH_LEGS_SPEED else 0.0, 1.0 if travel.length() > RUSH_LEGS_SPEED else 0.0, dt)
        self._relax_elbows(dt)  # attacks pose the shoulder; a bent flying arm must not stay bent
        self.left_arm.rotation_z -= self.left_arm.rotation_z * blend_amount(dt)
        self.right_arm.rotation_z -= self.right_arm.rotation_z * blend_amount(dt)
        self._deform_cape()

    def _step_knock(self, dt: float) -> None:
        knock = self.knock
        if abs(knock.x) + abs(knock.z) < .1:
            return
        self.x += knock.x * dt
        self.z += knock.z * dt
        self.knock = knock * exp(-KNOCK_DECAY * dt)
        clamp_to_world(self, self.game.world, self.game.planet)

    # -- what powers ask of a body ---------------------------------------
    @property
    def is_evading(self) -> bool:
        return isinstance(self.motion, DashMotion)

    @property
    def moving_velocity(self) -> SimVec3:
        if self.flight.is_flying:
            return self.flight.velocity
        return self.ground.velocity + self.knock + SimVec3(0.0, self.jump_velocity, 0.0)

    def apply_knockback(self, impulse: SimVec3) -> None:
        if self.motion is not None and self.motion.ballistic:
            self.motion.add_impulse(impulse)
            return
        if self.flight.is_flying:
            self.flight.velocity = (self.flight.velocity + impulse).clamped(MAX_FLYING_KNOCK)
            return
        self.knock = self.knock + SimVec3(impulse.x, 0.0, impulse.z)
        if impulse.y > 0.0:
            self.jump_velocity = min(MAX_LAUNCH_SPEED, max(self.jump_velocity, 0.0) + impulse.y)

    def stop_knockback(self) -> None:
        self.knock = SimVec3()
        self.jump_velocity = min(self.jump_velocity, 0.0)
        if self.flight.is_flying:
            self.flight.velocity = SimVec3()

    def recover_from_knockdown(self) -> SimVec3 | None:
        """A blow's tumble ends here. Still where it was, still moving as it was: only now it is the body's own to use.

        Returns the velocity it had, or None if nothing had knocked it down. Only the player's keys come here.
        """
        motion = self.motion
        if motion is None or not motion.knocked_down:
            return None
        velocity = motion.velocity
        self.release_motion()  # which leaves it falling, if it is in the air
        self.ground.velocity = SimVec3(velocity.x, 0.0, velocity.z)
        self._pose_settling = POSE_SETTLE_SECONDS
        return velocity

    def recover_into_flight(self) -> bool:
        """F while a blow has it falling, or lying on the ground: straight into flight, keeping its speed."""
        if not self.flight_allowed or (self.motion is not None and not self.motion.knocked_down):
            return False  # a motion of its own, such as a slam under way, is not interrupted
        velocity = self.recover_from_knockdown()
        if velocity is None and not self.falling_from_blow:
            return False
        if velocity is None:
            velocity = self.ground.velocity + SimVec3(0.0, self.jump_velocity, 0.0)
        self.falling_from_blow = False
        self.jump_height = self.jump_velocity = 0.0
        self.ground.velocity = SimVec3()
        position = SimVec3(self.x, self.y, self.z)
        self.flight.velocity = velocity
        self.flight.toggle_flight(self.team.game.planet.normal(position))
        return True

    def release_motion(self) -> None:
        motion, self.motion = self.motion, None
        if motion is not None:
            motion.finish()

    def show_shield(self, visible: bool) -> None:
        self.visual.set_shield(visible)

    def aim_ray(self) -> tuple[SimVec3, SimVec3]:
        """Where this character is aiming: along the camera for the player, at a target for AI."""
        if self.controlled:
            start = camera.world_position
            forward = camera.forward
            origin = SimVec3(start.x, start.y, start.z)
            direction = SimVec3(forward.x, forward.y, forward.z).normalized()
            # Begin level with the body, so nothing behind the character can be hit.
            offset = SimVec3(self.x, self.y, self.z) - origin
            ahead = offset.x * direction.x + offset.y * direction.y + offset.z * direction.z
            return origin + direction * max(0.0, ahead), direction
        origin = SimVec3(self.x, self.y + EYE_HEIGHT, self.z)
        if self.ai_target is not None:
            return origin, (self.ai_target - origin).normalized()
        return origin, self.game.planet.heading(origin, self.local_yaw)

    def aim_direction_from(self, origin: SimVec3, limit: float) -> SimVec3:
        """Direction from a point on the body to whatever the crosshair is on."""
        start, direction = self.aim_ray()
        if not self.controlled:
            return direction
        game = self.team.game
        hit = trace(game, start, direction, limit, ignore=(self,),
                    characters=game.combat.hostiles_of(self))
        offset = hit.point - origin
        return offset.normalized() if offset.length() > 1.0 else direction

    def eye_points(self) -> tuple:
        return (self.eye_left.world_position, self.eye_right.world_position)

    def mouth_point(self) -> SimVec3:
        origin = SimVec3(self.x, self.y + EYE_HEIGHT - .25, self.z)
        return origin + self.team.game.planet.heading(origin, self.local_yaw) * .6

    def wanted_direction(self):
        """The direction the player is holding, for dashes; AI simply dashes forward."""
        if not self.controlled:
            return None
        game = self.team.game
        move, _vertical = game.input_manager.movement(flying=self.flight.is_flying)
        return move if move.length() > 1e-4 else None

    def on_downed(self) -> None:
        self.powers.cancel_all()
        if self.motion is None or not self.motion.ballistic:
            self.release_motion()
        self.knock = SimVec3()
        if self.flight.is_flying:
            self.flight.phase = FlightPhase.LANDING
            self.flight.phase_time = 0.0
        if self.controlled:
            self.team.game.notify("DOWN: RECOVERING", 4.0)

    def on_revived(self) -> None:
        self.pose_root.setP(0.0)
        if self.controlled:
            self.team.game.notify("BACK ON YOUR FEET")

    def on_nullified(self) -> None:
        if self.controlled:
            self.team.game.notify("COMPOUND V NULLIFIED: POWERS LOST", 3.0)

    # -- who is in charge ------------------------------------------------
    def set_controlled(self, controlled: bool) -> None:
        if self.powers is not None:
            self.powers.cancel_all()
            self.release_motion()
        self._end_ai_move()
        self.ai_target = None
        self.controlled = controlled
        self.game = self.team.game if controlled else self.context
        self.tuning = self.game.tuning
        self.ground.walk_pace = self.tuning.number("walking_pace", 3.0) if controlled else None
        self.intent = None
        self.next_decision = 0.0
        self.boost_gate = BoostGate()
        if controlled:
            self.visual.set_detail(True)
            self.hair_locks = self.visual.lock_joints
        self.apply_sentry_config()

    def set_parked(self, parked: bool) -> None:
        """Available characters leave the world but keep existing, with no respawn."""
        if parked and self.powers is not None:  # what they had going leaves with them, and on nobody else either
            self.powers.cancel_all()
            self.release_motion()
        self.parked = parked
        self.enabled = not parked

    # -- AI --------------------------------------------------------------
    @property
    def velocity(self) -> SimVec3:
        return self.flight.velocity if self.flight.is_flying else self.ground.velocity

    def refresh_view(self) -> AgentView:
        view = self.view
        view.position = SimVec3(self.x, self.y, self.z)
        view.velocity = self.velocity
        view.flying = self.flight.is_flying
        return view

    def refresh_detail(self, distance: float) -> None:
        near = distance < NEAR_DISTANCE
        self.visual.set_detail(near)
        self.hair_locks = self.visual.lock_joints if near else []

    def adopt_intent(self, intent: Intent) -> None:
        self.intent = intent
        clearance = TRAVEL_CLEARANCE if intent.distance_to_target > 70.0 else NEAR_CLEARANCE
        self._safe_altitude = terrain_safe_altitude(
            self.view.position, self.flight.velocity, self.game.world.height_at,
            clearance=clearance)
        self.refresh_detail(intent.distance_to_target)
        self._update_flight_mode(self.game.elapsed)

    def _update_flight_mode(self, now: float) -> None:
        if now < self._next_mode_change or self.intent is None or self.motion is not None:
            return  # a motion owns the body, including its flight state, until it has finished
        flight = self.flight
        position = SimVec3(self.x, self.y, self.z)
        altitude = self.game.planet.altitude(position)
        wants_flight = self.intent.want_flight and self.flight_allowed
        if wants_flight and flight.phase in (FlightPhase.GROUNDED, FlightPhase.LANDING):
            flight.toggle_flight(self.game.planet.normal(position))
            self._next_mode_change = now + 1.2
        elif (not wants_flight and flight.phase is FlightPhase.CRUISE
              and altitude < 3.0 and flight.speed_mps < 45.0):
            flight.phase = FlightPhase.LANDING
            flight.phase_time = 0.0
            self._next_mode_change = now + 1.2

    def _destination(self) -> SimVec3:
        intent = self.intent
        planet = self.game.planet
        x, z = planet.clamp_to_land(intent.destination.x, intent.destination.z, 40.0)
        if (intent.want_flight and self.flight_allowed) or self.flight.phase is FlightPhase.TAKEOFF:
            y = max(intent.destination.y, self._safe_altitude)
        else:
            y = self.game.world.height_at(x, z) + .25
        return SimVec3(x, min(CEILING, y), z)

    def _flight_command(self, dt: float):
        destination = self._destination()
        position = SimVec3(self.x, self.y, self.z)
        fc = self.flight.config
        command = steer_flight(position, self.flight.velocity, destination,
                               self.intent.match_velocity, cruise_speed=fc.cruise_speed,
                               boost_speed=fc.boost_speed, thrust=fc.acceleration,
                               braking=fc.braking_deceleration, dt=dt,
                               push=self.team.separation_push(self))
        if self.game.elapsed < self._unstuck_until:
            command.vertical = 1.0
        command.boost = self.boost_gate.allow(command.boost, dt,
                                              self.tuning.seconds("boost_duration_cs"),
                                              self.tuning.seconds("boost_cooldown_cs"))
        return command

    def _ground_command(self) -> tuple[SimVec3, bool]:
        destination = self._destination()
        delta = SimVec3(destination.x - self.x, 0.0, destination.z - self.z)
        distance = delta.length()
        push = self.team.separation_push(self)
        if distance < 1.6 and push.length() < .05:
            return SimVec3(), False
        # At Soldier Boy's speed the last of a run has to be a walk, or he goes straight past them.
        return (delta.normalized() + push).clamped(1.0), distance > max(25.0, self.ground.max_running_speed * .25
                                                                        if self.has_super_jump else 0.0)

    def _face(self) -> None:
        camera = self.context.camera
        player = self.team.player_position
        dx, dz = player.x - self.x, player.z - self.z
        velocity = self.velocity
        if dx * dx + dz * dz > 40000.0 and velocity.length() > 20.0:
            dx, dz = velocity.x, velocity.z
        if dx * dx + dz * dz > .01:
            camera.yaw = degrees(atan2(dx, dz))

    def step(self, dt: float, player_distance_sq: float) -> None:
        """Advance AI; far flyers run a reduced model at a lower rate."""
        self.enforce_flight()
        if (self.motion is not None or self.vitals.immobile
                or abs(self.knock.x) + abs(self.knock.z) > .1):
            self._step_motion_only(dt)
            return
        if self.intent is None:
            return
        if player_distance_sq > FAR_SIMULATION_DISTANCE ** 2 and self.flight_allowed:
            self._far_timer += dt
            if self._far_timer >= FAR_STEP_SECONDS:
                self._step_far(min(self._far_timer, .1))
                self._far_timer = 0.0
            return
        self._far_timer = 0.0
        if self.flight.is_flying:
            command = self._flight_command(dt)
            self._step_motion(dt, command.move, command.vertical, command.boost,
                              command.brake, False, command.heading)
        else:
            move, sprint = self._ground_command()
            if self.has_super_jump:
                self._think_about_leaping()
                if self.keeps_own_height:
                    move, sprint = SimVec3(), False  # the leap was aimed; it carries on where it was sent
            self._step_motion(dt, move, 0.0, False, False, sprint, None)
        self._check_stuck(dt)

    def _think_about_leaping(self) -> None:
        """Up after someone in the air, or across a long gap, aimed at where they are going to be."""
        combat = self.team.game.combat
        now = self.team.game.elapsed
        if not combat.ai_powers_enabled or now < self._next_leap or self.vitals.immobile:
            return
        target = combat.targets.lock_of(self)
        if target is None:
            return
        rising = self.jump_velocity > 0.0
        high = float(target.y) - float(self.y)
        dx, dz = float(target.x) - float(self.x), float(target.z) - float(self.z)
        flat = sqrt(dx * dx + dz * dz)
        if rising or (high < LEAP_UP_FOR and flat < LEAP_ACROSS_FOR):
            return  # still on the way up; or the ground is the better place to fight this one
        upward, seconds = self._leap_for(max(0.0, high))
        if high < LEAP_UP_FOR:
            upward, seconds = LEAP_ACROSS_RISE, 2.0 * LEAP_ACROSS_RISE / JUMP_GRAVITY  # over and down beside them
        else:  # they will have moved by the time he gets there
            ahead = target.velocity * seconds
            upward, seconds = self._leap_for(max(0.0, high + ahead.y))
            ahead = target.velocity * seconds
            dx, dz = dx + ahead.x, dz + ahead.z
        across = SimVec3(dx / max(seconds, .1), 0.0, dz / max(seconds, .1)).clamped(MAX_LEAP_ACROSS)
        self.leap(upward, across)
        self._next_leap = now + LEAP_MIN_GAP

    @staticmethod
    def _leap_for(height: float) -> tuple[float, float]:
        """How fast to go up to arrive a little over ``height``, and how long the climb takes."""
        upward = min(MAX_JUMP_SPEED, sqrt(2.0 * JUMP_GRAVITY * (height + LEAP_CLEARANCE)))
        return upward, upward / JUMP_GRAVITY

    def _step_motion_only(self, dt: float) -> None:
        altitude = self.game.planet.altitude(SimVec3(self.x, self.y, self.z))
        self._face()
        self.simulate(dt, SimVec3(), 0.0, ground_distance=max(0.0, altitude - .25))

    # -- AI combat -------------------------------------------------------
    def _end_ai_move(self) -> None:
        move, self._ai_move = self._ai_move, None
        tokens = getattr(self.team, "attack_tokens", None) if self.team is not None else None
        if tokens is not None:
            tokens.give_back(self)
            self.team.squad_tokens.give_back(self)
        if move is not None and self.powers is not None:
            ability = self.powers.abilities[move.ability_id]
            ability.release()
            if not move.stays_on:
                ability.cancel()  # AI switches sustained powers back off when its turn ends

    def run_ai_combat(self, dt: float, now: float, tokens, hostiles) -> None:
        """Pick a target and, when its turn comes, one of this character's real abilities."""
        vitals = self.vitals
        if vitals.immobile or not hostiles:
            self._end_ai_move()
            self.ai_target = None
            return
        here = center_of(self)
        target = self.team.game.combat.targets.lock_of(self)
        if target is None:
            self._end_ai_move()
            self.ai_target = None
            return
        self.ai_target = center_of(target)
        if self._ai_move is not None:
            self._ai_hold_left -= dt
            if self._ai_hold_left <= 0.0:
                self._end_ai_move()
                self._ai_next_attack = now + self._rng.uniform(*AI_ATTACK_GAP) / max(
                    .2, self.brain.personality.aggression)
            return
        if self.motion is not None and now >= self._ai_next_attack and self.motion.ballistic:
            self._try_slam_out_of_a_fall(now)
        if now < self._ai_next_attack or self.motion is not None:
            return
        distance = (self.ai_target - here).length()
        if distance > self.team.ai_tuning.detection_range:
            return
        abilities = self.powers.abilities

        def ready(ability_id: str) -> bool:
            ability = abilities[ability_id]
            if ability_id in CINEMATIC_IDS and not self.team.cinematic_ready(now):
                return False
            return not ability.active and ability.usable(quiet=True)

        if self._try_ai_slam(target, distance):
            return
        table = self.ai_moves or self.character_id
        if self.keeps_own_height and distance <= MOVES["RED_AIR"][0].high:
            table = "RED_AIR"
        move = choose_move(table, distance, ready, self._rng,
                           self._situation(target, hostiles, here))
        if move is None or not tokens.take(self):
            self._ai_next_attack = now + .4
            return
        self._ai_move = move
        self._ai_hold_left = move.hold
        self._ai_uses[move.ability_id] = self._ai_uses.get(move.ability_id, 0) + 1
        if move.cinematic:
            self.team.cinematic_started(now, self)
        if move.kick:
            abilities[move.ability_id].kick()
        else:
            abilities[move.ability_id].press()

    def _try_slam_out_of_a_fall(self, now: float) -> None:
        """Thrown and on the way down: the F the player has here, not on every throw."""
        dive = self.powers.abilities.get("impact_dive")
        if dive is None or getattr(self.motion, "velocity", SimVec3()).y >= 0.0:
            return
        self._ai_next_attack = now + .4
        if self._rng.random() <= SLAM_CHANCE:
            dive.press()

    def _try_ai_slam(self, target, distance: float) -> bool:
        """Up in the air, over someone: the same F-slam the player has."""
        dive = self.powers.abilities.get("impact_dive")
        if dive is None or not dive.available():
            return False
        if float(self.y) - float(target.y) < SLAM_ABOVE or distance > SLAM_ABOVE + SLAM_FROM * 2.0:
            return False
        dx, dz = float(target.x) - float(self.x), float(target.z) - float(self.z)
        if dx * dx + dz * dz > SLAM_FROM * SLAM_FROM or self._rng.random() > SLAM_CHANCE:
            self._ai_next_attack = self.team.game.elapsed + .4
            return False
        dive.press()
        self._ai_next_attack = self.team.game.elapsed + AI_ATTACK_GAP[0]
        return True

    def _situation(self, target, hostiles, here) -> Situation:
        vitals = target.vitals
        return Situation(target_flying=target.flight.is_flying, target_health=vitals.fraction,
                         target_helpless=vitals.immobile, target_attacking=target.motion is not None,
                         target_moving_fast=target.moving_velocity.length() > FAST_TARGET,
                         enemies_close=sum((center_of(other) - here).length() < CLOSE_METRES for other in hostiles),
                         uses=self._ai_uses)

    def _step_motion(self, dt, move, vertical, boost, brake, sprint, heading) -> None:
        position = SimVec3(self.x, self.y, self.z)
        altitude = self.game.planet.altitude(position)
        self._face()
        if (self.flight.phase in (FlightPhase.TAKEOFF, FlightPhase.CRUISE)
                and vertical < 0 and altitude <= 1.4 and not self.intent.want_flight):
            self.flight.phase = FlightPhase.LANDING
            self.flight.phase_time = 0.0
        self.simulate(dt, move, vertical, boost=boost, brake=brake, sprint=sprint,
                      ground_distance=max(0.0, altitude - .25), steering_direction=heading)

    def _step_far(self, dt: float) -> None:
        """Distant pursuit: same flight model, without animation or tree sweeps."""
        flight = self.flight
        planet = self.game.planet
        position = SimVec3(self.x, self.y, self.z)
        if flight.phase is FlightPhase.GROUNDED:
            flight.toggle_flight(planet.normal(position))
        if flight.phase is FlightPhase.LANDING:
            flight.phase = FlightPhase.CRUISE
        command = self._flight_command(dt)
        velocity = flight.step(command.move, command.vertical, dt, boost=command.boost,
                               brake=command.brake, ground_distance=100.0,
                               steering_direction=command.heading, up=planet.normal(position),
                               gravity=planet.gravity(position), air_density=1.0)
        self.x += velocity.x * dt
        self.y += velocity.y * dt
        self.z += velocity.z * dt
        clamp_to_world(self, self.game.world, planet)
        self._face()
        self.local_yaw = self.context.camera.yaw
        planet.orient_entity(self, position, self.local_yaw)

    def _check_stuck(self, dt: float) -> None:
        """Climb out when thrust produces no progress, for example inside a tree."""
        if not self.flight.is_flying:
            self._stuck_timer = 0.0
            return
        self._stuck_timer += dt
        if self._stuck_timer < 1.2:
            return
        here = SimVec3(self.x, self.y, self.z)
        moved = (here - self._stuck_from).length()
        wanted = (self._destination() - here).length()
        if moved < 1.5 and wanted > 8.0:
            self._unstuck_until = self.game.elapsed + 1.0
        self._stuck_from = here
        self._stuck_timer = 0.0

    def _deform_cape(self) -> None:
        self._cape_timer += 1.0 / 60.0
        if self._cape_step <= 0.0 or (not self.visual.is_near and self._cape_timer < .1):
            return
        steps = self._cape_timer
        self._cape_timer = 0.0
        speed = self.flight.speed_mps if self.flight.is_flying else self.ground.velocity.length() * RUNNING_WIND
        if self.uses_skinned_body:
            pace = self.ground.velocity.length()
            airborne = self.flight.is_flying or self.jump_height > 0.0 or self.motion is not None
            turning = (((self.local_yaw - self._body_yaw + 180.0) % 360.0) - 180.0) / max(steps, 1e-3)
            change = (pace - self._body_pace) / max(steps, 1e-3)
            self._body_yaw, self._body_pace = self.local_yaw, pace
            self.visual.set_breathing(steps, pace, airborne, turning, change)
            self._react_to_ground(airborne)
            if self.controlled and self.flight.is_flying:
                self._flight_effects(steps)
        if self.uses_skinned_body:
            velocity = self.velocity
            if self.motion is not None:  # not every motion that moves a body keeps a velocity of its own
                velocity = getattr(self.motion, "velocity", velocity)
            self.visual.step_cape(steps, (velocity.x, velocity.y, velocity.z))
            return
        self.visual.set_cape_wind(self._animation_time, min(1.0, speed / 150.0),
                                  self._airflow_forward, self._airflow_right)


class _OriginalVisual:
    """What a clone's visual offers, for Yellow's own hand-built model."""

    is_near = True
    lock_joints = ()

    def __init__(self, owner) -> None:
        self.lock_joints = owner.hair_locks

    def set_detail(self, _near: bool) -> None:
        return None

    def set_helmet(self, _visible: bool) -> None:
        return None

    def set_shield(self, _visible: bool) -> None:
        return None

    def set_cape_wind(self, *_args) -> None:
        return None


class YellowSentry(RosterCharacter):
    """The original full model, which the other four are also built from."""

    _kit = KITS[BASE_BODY]

    def __init__(self, game, position) -> None:
        SentryCharacter.__init__(self, game, position=position)
        self.controlled = True
        self.reentry_glow.hide()
        if self.uses_skinned_body:
            self._cape_timer = 0.0
            return
        self.visual = _OriginalVisual(self)
        # A large black S on the chest, from the same geometry as the old waist mark.
        emblem = self.parts["waist_s"]
        emblem.position = (0, 1.70, .425)
        emblem.scale = (-2.3, 2.3, 2.3)  # the mark is authored for the opposite facing
        emblem.color = _black()

    def attach_team(self, team, personality: Personality, seed: int) -> None:
        context = CharacterContext(team, self.kit, None)
        self._attach(team, context, personality, seed, tuple(self.position))

    def _visual_name(self) -> str:
        return BASE_BODY

    def _build_body(self) -> None:
        if skinned_bodies_ready():
            RosterCharacter._build_body(self)
        else:
            SentryCharacter._build_body(self)

    def _deform_cape(self) -> None:
        if self.uses_skinned_body:
            RosterCharacter._deform_cape(self)
        else:
            SentryCharacter._deform_cape(self)


def _black():
    from ursina import color
    return color.rgb32(12, 12, 14)
