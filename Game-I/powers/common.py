"""Abilities every character has: physical combat, dash, grab and throw, plus rams."""

from __future__ import annotations

from math import atan2, cos, degrees, exp, pi, sin

from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, objects_in_radius, trace
from powers.base import Ability, Motion, land
from powers.vitals import EXPLOSION, PHYSICAL

FINISHER_HEALTH = .12
HOLD_DISTANCE = 3.6
ARM_REACH = 5.0
SWING_SECONDS = .25
KICK_FORCE_SCALE = 1.5
GROUND_PUNCH_PITCH = -.35  # how far down the camera must look for a punch to hit the ground
LUNGE_MAX_SECONDS = 3.0
DASH_SPEED = 120.0
DASH_SECONDS = .28
LAUNCH_GRAVITY = 30.0
LAUNCH_TERMINAL = 95.0       # a thrown body falls no faster than this once the air has it
STRIKE_TWIST = 26.0
MOMENTUM_SHARE, MOMENTUM_FORCE_LIMIT = .35, 90.0
LYING_PITCH_RATE = 14.0
MAX_DOWN_SECONDS, DOWN_PER_SPEED = .55, .022
LAUNCH_DRAG = 1.7
LAUNCH_MAX_SECONDS = 12.0
LAUNCH_TUMBLE = 540.0        # degrees per second while airborne
HARD_LANDING_SPEED = 25.0
BOUNCE_SPEED = 10.0
SKID_DRAG = 6.0
SETTLED_SPEED = 5.0
OBSTACLE_DAMAGE_PER_SPEED = .5
RING_PUFFS = 10
IMPACT_DUST = (190, 170, 140, 220)
NUCLEAR_SMOKE = (70, 62, 58, 210)
NUCLEAR_CRATER = 40.0
NUCLEAR_DEPTH = 8.0


class LungeMotion(Motion):
    """Melee at range: rush the target at Speed, and land one blow on arrival."""

    def __init__(self, ability, target, kick: bool) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.target = target
        self.kick = kick
        owner = self.owner
        if owner.flight_allowed and target.y > owner.y + 3.0 and not owner.flight.is_flying:
            owner.flight.phase = FlightPhase.CRUISE
            owner.flight.phase_time = 0.0

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        target = self.target
        if target.vitals.downed or target.parked or self.elapsed > LUNGE_MAX_SECONDS:
            return False
        offset = center_of(target) - center_of(self.owner)
        distance = offset.length()
        if distance <= ARM_REACH:
            self.ability.land_blow(target, self.kick)
            return False
        speed = self.ability.p("speed")
        self.owner.ground.velocity = SimVec3()
        self._move(offset.normalized() * min(speed, (distance - ARM_REACH * .5) / max(dt, 1e-4)), dt)
        return True


class Melee(Ability):
    """A punch on +, a kick on -: one blow per press, turning to face the target."""

    ability_id = "melee"
    survives_nullification = True

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.swing = 0.0
        self.attacks = 0
        self.kicks = 0
        self.facing_target = None
        self.facing_kick = False

    def strength_scale(self) -> float:
        powers = self.owner.powers
        scale = powers.strength * powers.attack_scale
        return scale * .5 if self.vitals.nullified else scale

    def press(self) -> None:
        self._strike(False)

    def kick(self) -> None:
        self._strike(True)

    def reset(self) -> None:
        super().reset()
        self.swing = 0.0
        self.attacks = 0
        self.kicks = 0
        self.facing_target = None

    def update(self, dt: float) -> None:
        if self.swing <= 0.0:
            return
        self.swing = max(0.0, self.swing - dt)
        self._face_target()
        visual = self.owner.visual
        if self.facing_kick:
            self.owner.left_leg.rotation_x = -80.0 * self.swing / SWING_SECONDS
        else:
            self.owner.right_arm.rotation_x = -110.0 * self.swing / SWING_SECONDS
        if hasattr(visual, "strike_twist"):
            visual.strike_twist(STRIKE_TWIST * self.swing / SWING_SECONDS * (-1.0 if self.facing_kick else 1.0))

    def _face_target(self) -> None:
        target = self.facing_target
        if target is None:
            return
        owner = self.owner
        dx, dz = target.x - owner.x, target.z - owner.z
        if dx * dx + dz * dz > .01:
            owner.local_yaw = degrees(atan2(dx, dz))
            self.game.planet.orient_entity(owner, SimVec3(owner.x, owner.y, owner.z), owner.local_yaw)

    def _strike(self, kick: bool) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None:
            return
        self.swing = SWING_SECONDS
        self.facing_kick = kick
        target = self.target()
        self.facing_target = target
        if target is None:
            self._strike_world(kick)
            return
        self._face_target()
        if (center_of(target) - center_of(owner)).length() <= ARM_REACH:
            self.land_blow(target, kick)
        else:
            owner.motion = LungeMotion(self, target, kick)

    def land_blow(self, target, kick: bool = False) -> None:
        owner = self.owner
        damage = self.p("damage") * self.strength_scale()
        force = self.force(20.0, 110.0) * (KICK_FORCE_SCALE if kick else 1.0)
        if target.vitals.health <= target.vitals.max_health * FINISHER_HEALTH:
            damage *= 3.0
            force *= 1.5
            self.say("FINISHING BLOW")
        self.swing = SWING_SECONDS
        self.attacks += 1
        self.kicks += kick
        direction = (center_of(target) - center_of(owner)).normalized()
        # The blow carries what the attacker was already moving at, in the direction it lands.
        velocity = owner.velocity
        closing = velocity.x * direction.x + velocity.y * direction.y + velocity.z * direction.z
        force += min(MOMENTUM_FORCE_LIMIT, max(0.0, closing) * MOMENTUM_SHARE)
        self.combat.hit_character(owner, target, damage, PHYSICAL, direction, force)
        self.combat.puffs.emit(center_of(target), SimVec3(0.0, 2.0, 0.0), (255, 235, 200, 200),
                               size=.6, grow=2.0, life=.25)
        self.game.world.play_power_sound(.35)

    def _strike_world(self, kick: bool) -> None:
        """Nobody in range: hit the object or tree ahead, or the ground if looking down."""
        owner = self.owner
        self.attacks += 1
        self.kicks += kick
        damage = self.p("damage") * self.strength_scale()
        force = self.force(20.0, 110.0) * (KICK_FORCE_SCALE if kick else 1.0)
        origin = center_of(owner)
        forward = self.facing()
        hit = trace(self.game, origin, forward, ARM_REACH + 3.0, ignore=(owner,), characters=(),
                    terrain=False)
        if hit.kind in ("object", "tree"):
            self.combat.damage_hit(owner, hit, damage, forward, kind=PHYSICAL, force=force)
            self.game.world.play_power_sound(.35)
        elif not owner.flight.is_flying and owner.aim_ray()[1].y < GROUND_PUNCH_PITCH:
            self.combat.blast(owner, SimVec3(owner.x, owner.y, owner.z), self.area(.1, 18.0),
                              damage * .5, force, kind=PHYSICAL,
                              crater=(self.area(.03, 6.0), .5, "ground-punch"), cracks=True)


class DashMotion(Motion):
    def __init__(self, owner, direction: SimVec3, speed: float, duration: float) -> None:
        super().__init__(owner)
        self.velocity = direction * speed
        self.duration = duration

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        self._move(self.velocity, dt)
        return self.elapsed < self.duration

    def finish(self) -> None:
        flight = self.owner.flight
        if flight.is_flying:
            flight.velocity = self.velocity * .35


class Dash(Ability):
    """The universal Q control, with no card and nothing to edit."""

    ability_id = "dash"

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None:
            return
        direction = owner.wanted_direction() or self.facing()
        owner.motion = DashMotion(owner, direction.normalized(), DASH_SPEED, DASH_SECONDS)
        self.combat.puffs.emit(center_of(owner), SimVec3(0, 2, 0), (230, 230, 240, 120),
                               size=1.2, grow=3.0, life=.35)

    def hud_state(self) -> str:
        return "ON" if isinstance(self.owner.motion, DashMotion) else super().hud_state()


class Grab(Ability):
    ability_id = "grab"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.held = None

    def press(self) -> None:
        if self.held is not None:
            self._throw()
        elif self.usable():
            target = self.find_target()
            if target is None:
                self.say("NOTHING TO GRAB IN RANGE")
                return
            self._hold(target)

    def find_target(self):
        """The nearest enemy, or failing that the nearest loose object."""
        enemy = self.target()
        if enemy is not None:
            return enemy
        origin = center_of(self.owner)
        best, best_distance = None, None
        for obj in objects_in_radius(self.game, origin, min(self.reach(), 150.0)):
            if obj.anchored or obj.held or not getattr(obj, "liftable", False):
                continue
            distance = (SimVec3(obj.x, obj.y, obj.z) - origin).length()
            if best is None or distance < best_distance:
                best, best_distance = obj, distance
        return best

    def _hold(self, target) -> None:
        self.held = target
        self.active = True
        if hasattr(target, "vitals"):
            target.vitals.add_status("held", .2)
            target.release_motion()
        else:
            target.begin_hold()

    def update(self, dt: float) -> None:
        target = self.held
        if target is None:
            return
        if self.vitals.immobile or self.vitals.nullified or not self._still_holdable(target):
            self.cancel()
            return
        forward = self.facing()
        owner = self.owner
        point = SimVec3(owner.x + forward.x * HOLD_DISTANCE, owner.y + 2.2,
                        owner.z + forward.z * HOLD_DISTANCE)
        # Something far away is pulled in at Speed, not teleported.
        offset = point - SimVec3(float(target.x), float(target.y), float(target.z))
        step = self.p("speed") * dt
        if offset.length() > step:
            point = SimVec3(float(target.x), float(target.y), float(target.z)) + offset.normalized() * step
        target.position = (point.x, point.y, point.z)
        owner.right_arm.rotation_x = owner.left_arm.rotation_x = -150.0
        if hasattr(target, "vitals"):
            target.vitals.add_status("held", .2)
        else:
            target.velocity = SimVec3()

    def _still_holdable(self, target) -> bool:
        if hasattr(target, "vitals"):
            return not target.vitals.downed and not target.parked
        return target.enabled and not target.health.broken

    def _throw(self) -> None:
        target, self.held = self.held, None
        self.active = False
        origin = center_of(self.owner)
        next_enemy = self.combat.targets.for_ability(self.owner, self.reach(), exclude=target)
        if next_enemy is not None:
            direction = (center_of(next_enemy) - origin).normalized()
        else:
            direction = self.owner.aim_direction_from(origin, 300.0)
        powers = self.owner.powers
        speed = self.p("speed")
        damage = self.p("damage") * powers.strength * powers.attack_scale
        self.game.world.play_power_sound(.3)
        if hasattr(target, "vitals"):
            target.vitals.clear_status("held")
            self.combat.throw_character(self.owner, target, direction, speed, damage)
        else:
            target.release(direction * speed)
            self.combat.track_thrown_object(self.owner, target, damage)

    def cancel(self) -> None:
        """Drop whatever is held."""
        target, self.held = self.held, None
        self.active = False
        if target is None:
            return
        if hasattr(target, "vitals"):
            target.vitals.clear_status("held")
        elif target.enabled:
            target.release()


class ThrowingGrab(Grab):
    """A grapple that ends in a throw when AI lets go, rather than a plain drop."""

    def release(self) -> None:
        if self.held is not None:
            self._throw()


def press_charge(ability, name: str) -> None:
    """Homelander's and Omni-Man's charges: go now, or pull out of one under way."""
    owner = ability.owner
    if isinstance(owner.motion, RamMotion):
        owner.release_motion()
    elif ability.usable() and owner.motion is None and owner.flight_allowed:
        owner.motion = RamMotion(ability)
        ability.say(name)


class LaunchedMotion(Motion):
    """A body thrown through the world: gravity, air, whatever it hits, and then the ground.

    It is never teleported, and it still falls if the blow that sent it flying also downed it.
    """

    ballistic = True
    knocked_down = True

    def __init__(self, source, body, velocity: SimVec3, damage: float = 0.0) -> None:
        super().__init__(body)
        self.source = source
        self.velocity = velocity
        self.damage = damage
        self.landed = False
        self.struck = {source, body}
        self.max_seconds = LAUNCH_MAX_SECONDS
        self.hard_landing_speed = HARD_LANDING_SPEED
        self.facing = float(body.local_yaw)
        self.spin = 0.0
        self.down_for = 0.0
        self._leave_flight()
        body.knock = SimVec3()
        body.jump_height = body.jump_velocity = 0.0

    def _leave_flight(self) -> None:
        """No longer flying or walking, without moving the body from where it is in the air."""
        body = self.owner
        body.flight.phase = FlightPhase.GROUNDED
        body.flight.phase_time = 0.0
        body.flight.velocity = SimVec3()
        body.ground.velocity = SimVec3()

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        body = self.owner
        if body.parked or self.elapsed > self.max_seconds:
            return False
        game = body.team.game
        drag = exp(-LAUNCH_DRAG * dt)
        velocity = self.velocity
        # Drag across the air as before; falling, the square of the speed, so that a body has a true terminal velocity
        # and not the crawl that plain linear drag gives it.
        vertical = velocity.y * (drag if velocity.y > 0.0 else 1.0) - LAUNCH_GRAVITY * dt
        if vertical < 0.0:
            vertical += LAUNCH_GRAVITY * (vertical / LAUNCH_TERMINAL) ** 2 * dt
        self.velocity = velocity = SimVec3(velocity.x * drag, vertical, velocity.z * drag)
        here = SimVec3(float(body.x), float(body.y), float(body.z))
        speed = velocity.length()
        if speed > 1.0:
            self._hit_obstacles(game, here, speed, dt)
            velocity = self.velocity
        x, z = game.planet.clamp_to_land(here.x + velocity.x * dt, here.z + velocity.z * dt)
        floor = game.world.height_at(x, z) + .25
        # A super jump can already be above the ceiling; being hit up there must not snap it back down to it.
        y = min(here.y + velocity.y * dt, max(game.planet.MAX_FLIGHT_ALTITUDE, here.y))
        if y > floor:
            body.position = (x, y, z)
            # Spin comes from the blow and dies away with the speed that it came from.
            self.spin += min(LAUNCH_TUMBLE, 90.0 + speed * 9.0) * dt
            body.pose_root.setP(self.spin % 360.0)
            self._flail(speed)
            return True
        body.position = (x, floor, z)
        # On the ground it stops turning over and lies flat, whichever side it came down on.
        pitch = ((self.spin + 180.0) % 360.0) - 180.0
        flat = -90.0 if pitch < 0.0 else 90.0
        self.spin = pitch + (flat - pitch) * min(1.0, dt * LYING_PITCH_RATE)
        body.pose_root.setP(self.spin)
        self._flail(speed * .3)
        return self._on_ground(game, SimVec3(x, floor, z), dt)

    def _flail(self, speed: float) -> None:
        """Limbs thrown about by the air, harder the faster the body goes: not a physics solve, but no two moments alike."""
        body, t = self.owner, self.elapsed
        force = min(1.0, speed / 40.0)
        body.left_arm.rotation_x = -70.0 * force + sin(t * 11.0) * 55.0 * force
        body.right_arm.rotation_x = -95.0 * force + sin(t * 9.0 + 1.3) * 60.0 * force
        body.left_arm.rotation_z = 35.0 * force + sin(t * 7.0) * 20.0
        body.right_arm.rotation_z = -35.0 * force + sin(t * 8.0 + .7) * 20.0
        body.left_leg.rotation_x = sin(t * 8.5) * 42.0 * force
        body.right_leg.rotation_x = sin(t * 10.0 + 2.1) * 42.0 * force

    def _hit_obstacles(self, game, here: SimVec3, speed: float, dt: float) -> None:
        direction = self.velocity * (1.0 / speed)
        hit = trace(game, here + SimVec3(0.0, 1.4, 0.0), direction, speed * dt + 1.0,
                    ignore=tuple(item for item in self.struck if item is not None), characters=(),
                    terrain=False)
        if hit.kind not in ("object", "tree"):
            return
        self.struck.add(hit.target)
        game.combat.damage_hit(self.source, hit, speed * OBSTACLE_DAMAGE_PER_SPEED, direction,
                               kind=PHYSICAL, force=speed * .4)
        game.combat.burst(hit.point, 5.0, .9)
        if hit.kind == "object" and not hit.target.health.broken:  # it held: he stops against it
            self.velocity = SimVec3(-self.velocity.x * .15, self.velocity.y * .3, -self.velocity.z * .15)

    def _on_ground(self, game, point: SimVec3, dt: float) -> bool:
        combat = game.combat
        velocity = self.velocity
        fall = -velocity.y
        if not self.landed and velocity.length() >= self.hard_landing_speed:
            if self.damage > 0.0:
                combat.hit_character(self.source, self.owner, self.damage, PHYSICAL)
            combat.burst(point, 7.0, 1.0)
            game.world.terrain_impact(point, radius=3.0, depth=.6, intensity=.8, surface="thrown")
            combat.puffs.emit(point, SimVec3(0.0, 6.0, 0.0), (190, 170, 140, 210), size=1.5, grow=7.0,
                              life=.6)
            game.camera_impulse = max(game.camera_impulse, .8)
        if not self.landed:
            self.down_for = min(MAX_DOWN_SECONDS, velocity.length() * DOWN_PER_SPEED)
        self.landed = True
        self.down_for -= dt
        skid = exp(-SKID_DRAG * dt)
        rebound = fall * .25 if fall > BOUNCE_SPEED else 0.0
        self.velocity = SimVec3(velocity.x * (.6 if rebound else skid), rebound,
                                velocity.z * (.6 if rebound else skid))
        # A hard enough landing puts a body down for a moment, before it gets up.
        return self.velocity.length() >= SETTLED_SPEED or self.down_for > 0.0

    def add_impulse(self, impulse: SimVec3) -> None:
        self.velocity = self.velocity + impulse

    def finish(self) -> None:
        """Back to normal movement, including if this ends in mid-air: gravity simply takes over."""
        body = self.owner
        floor = body.team.game.world.height_at(body.x, body.z) + .25
        self._leave_flight()
        body.jump_height = max(0.0, float(body.y) - floor)
        body.jump_velocity = self.velocity.y if body.jump_height > 0.0 else 0.0
        body.falling_from_blow = body.jump_height > 0.0
        body.left_arm.rotation_z = body.right_arm.rotation_z = 0.0
        if not body.vitals.downed:
            body.pose_root.setP(0.0)
            if hasattr(body.visual, "recover_from"):
                body.visual.recover_from(self.spin)


class HurledDown:
    """A body an attack has hold of, thrown at the ground: at speed, through whatever is in the way."""

    def __init__(self, ability, source, target, speed: float, drift: float) -> None:
        self.ability, self.source, self.target, self.speed = ability, source, target, speed
        game = ability.game
        side = SimVec3(float(target.x) - float(source.x), 0.0, float(target.z) - float(source.z))
        side = side.normalized() if side.length() > 1e-3 else ability.facing()
        drop = max(1.0, float(target.y) - game.world.height_at(float(target.x), float(target.z)))
        x, z = game.planet.clamp_to_land(float(target.x) + side.x * drop * drift, float(target.z) + side.z * drop * drift, 40.0)
        self.point = SimVec3(x, game.world.height_at(x, z) + .25, z)
        self.clear = False

    def step(self, dt: float, obstacle_damage: float) -> bool:
        """True when it hits the ground."""
        ability, target = self.ability, self.target
        here = SimVec3(float(target.x), float(target.y), float(target.z))
        offset = self.point - here
        distance = offset.length()
        step = self.speed * dt
        if distance <= step:
            target.position = (self.point.x, self.point.y, self.point.z)
            return True
        direction = offset.normalized()
        if not self.clear:
            hit = trace(ability.game, here, direction, step + 1.0, ignore=(target, self.source), characters=(),
                        terrain=False)
            if hit.kind in ("object", "tree"):
                ability.combat.damage_hit(self.source, hit, obstacle_damage, direction, kind=PHYSICAL, force=30.0)
                if hit.kind == "object" and not hit.target.health.broken:
                    # It held: straight down its side from here, rather than through it.
                    self.clear = True
                    self.point = SimVec3(here.x, ability.game.world.height_at(here.x, here.z) + .25, here.z)
        moved = here + direction * step
        target.position = (moved.x, moved.y, moved.z)
        return False


def _ring(combat, point: SimVec3, speed: float, tint, size: float, grow: float, count: int = RING_PUFFS) -> None:
    for index in range(count):
        angle = 2.0 * pi * index / count
        combat.puffs.emit(point, SimVec3(sin(angle) * speed, 2.0 + index % 3 * 6.0, cos(angle) * speed), tint, size=size,
                          grow=grow, life=.6)


def ground_blast(ability, source, target, point: SimVec3, damage: float, radius: float, force: float, fire, ring,
                 surface: str) -> None:
    """Where a thrown body hits: the blow itself, a blast around it, a crater, cracks and a shockwave."""
    combat = ability.combat
    land(target)
    combat.hit_character(source, target, damage, PHYSICAL)
    combat.blast(source, point, radius, damage, force, kind=EXPLOSION, crater=(min(18.0, radius * .5), 3.0, surface),
                 cracks=True, burst_scale=2.5, tint=fire, ignore=(target,))
    ability.game.world._terrain_rebuild_wait = 0.0
    _ring(combat, point + SimVec3(0.0, 1.0, 0.0), radius * 1.6, ring, 2.0, radius * .2)
    _ring(combat, point + SimVec3(0.0, .5, 0.0), 14.0, IMPACT_DUST, 2.2, radius * .12)
    land(target)  # down into the crater just made
    target.pose_root.setP(-82.0)
    ability.game.camera_impulse = max(ability.game.camera_impulse, 2.5)


def nuclear_sphere(ability, source, point: SimVec3, radius: float, damage: float, force: float, fire, ring,
                   on_ground: bool = False) -> None:
    """A huge sphere: full damage inside it, fire, smoke and a shockwave, and a crater if it reaches the ground."""
    combat, world = ability.combat, ability.game.world
    near = on_ground or point.y - world.height_at(point.x, point.z) < radius * .25
    crater = (min(NUCLEAR_CRATER, radius * .4), NUCLEAR_DEPTH, "nuclear") if near else None
    combat.blast(source, point, radius, damage, force, kind=EXPLOSION, crater=crater, cracks=near, burst_scale=4.0,
                 tint=fire, even_damage=True)
    world._terrain_rebuild_wait = 0.0
    _ring(combat, point, radius * .9, ring, 3.0, radius * .18)
    _ring(combat, point + SimVec3(0.0, 4.0, 0.0), 30.0, NUCLEAR_SMOKE, 4.0, radius * .12)


def launch_character(source, body, velocity: SimVec3, damage: float = 0.0) -> None:
    """Send someone flying. Whatever they were doing ends, and they carry on from where they land."""
    body.release_motion()
    body.motion = LaunchedMotion(source, body, velocity, damage)


class RamMotion(Motion):
    """Fly at full speed, hitting everything on the way, until the target or the Range is reached."""

    def __init__(self, ability) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        owner = self.owner
        _origin, self.direction, self.target = ability.aim(center_of(owner))
        if self.target is None and not owner.flight.is_flying and self.direction.y < 0.0:
            # From the ground it lifts off rather than ploughing straight in.
            self.direction = SimVec3(self.direction.x, 0.0, self.direction.z).normalized()
        self.speed = ability.p("speed")
        self.travelled = 0.0
        self.already_hit = {owner}
        self.struck = False
        owner.flight.phase = FlightPhase.CRUISE
        owner.flight.phase_time = 0.0

    def impact_damage(self) -> float:
        powers = self.owner.powers
        return self.ability.p("damage") * powers.strength * powers.attack_scale

    def step(self, dt: float) -> bool:
        ability = self.ability
        combat = ability.combat
        owner = self.owner
        target = self.target
        origin = center_of(owner)
        if target is not None:
            if target.vitals.downed or target.parked:
                self.target = target = None
            else:
                self.direction = (center_of(target) - origin).normalized()
        length = self.speed * dt
        force = ability.force(30.0, 150.0)
        hit = trace(ability.game, origin, self.direction, length + 1.0,
                    ignore=tuple(self.already_hit), radius=.9,
                    characters=combat.hostiles_of(owner))
        if hit.kind == "character":
            self.already_hit.add(hit.target)
            combat.hit_character(owner, hit.target, self.impact_damage(), PHYSICAL,
                                 self.direction, force)
            combat.burst(hit.point, 6.0, 1.0)
            if hit.target is target:
                self.struck = True
                return False
        elif hit.kind in ("object", "tree"):
            self.already_hit.add(hit.target)
            combat.damage_hit(owner, hit, self.impact_damage(), self.direction,
                              kind=PHYSICAL, force=force)
            combat.burst(hit.point, 5.0, .9)
            if hit.kind == "object" and not hit.target.health.broken:
                return False  # it held; the character stops against it
        elif hit.kind in ("terrain", "water"):
            self.on_ground(hit)
            return False
        before = (float(owner.x), float(owner.y), float(owner.z))
        self._move(self.direction * self.speed, dt)
        owner.flight.velocity = self.direction * self.speed
        self.travelled += length
        if before == (float(owner.x), float(owner.y), float(owner.z)):
            return False  # stopped by the world's edge or ceiling
        return self.travelled < ability.reach()

    def on_ground(self, hit) -> None:
        ability = self.ability
        radius = ability.area(.02, 22.0)
        ability.combat.blast(self.owner, hit.point, radius, self.impact_damage() * .6,
                             ability.force(30.0, 150.0), kind=EXPLOSION,
                             crater=(radius * .6, 1.2, "ram"))

    def finish(self) -> None:
        flight = self.owner.flight
        flight.velocity = self.direction * min(self.speed, flight.config.cruise_speed)
