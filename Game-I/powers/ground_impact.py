"""F in the air, for all five: straight down at speed, and a blast where they hit."""

from __future__ import annotations

from ursina import Audio

from characters.registry import definition, definitions

from math import cos, pi, sin

from movement.flight_physics import Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.base import Ability, Motion, land
from powers.common import LaunchedMotion
from powers.vitals import EXPLOSION, PHYSICAL

DIVING, IMPACT_RECOVERY = "DIVING", "IMPACT_RECOVERY"
MIN_HEIGHT = 1.5             # any lower and there is nothing to dive through: a second tap of F does nothing
START_SPEED = 120.0
ACCELERATION = 900.0
RECOVERY_SECONDS = .35
OBSTACLE_SHARE = .1
MAX_SECONDS = 30.0
RADIUS_SHARE, MAX_RADIUS = .0006, 60.0     # of Range
MAX_CRATER = 18.0
CRATER_DEPTH = 3.0
RING_PUFFS = 8
OUT_OF_THE_WAY = .8
ARMS_DOWN = -165.0


class Style:
    """What one character's impact looks like. What it does is the same for all five."""

    def __init__(self, tint, ring, dust_puffs: int = 4, burst: float = 2.5) -> None:
        self.tint, self.ring, self.dust_puffs, self.burst = tint, ring, dust_puffs, burst


DUST = (190, 170, 140, 220)
STYLES = {item.character_id: Style(*item.impact) for item in definitions()}


class ImpactDiveMotion(Motion):
    """Down, picking up speed, through whatever is in the way; then the blast, and a moment to recover."""

    def __init__(self, ability, forced: bool = False) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.ballistic = forced  # out of a throw: like the throw, it runs on through an enemy's time stop
        owner = self.owner
        self.movement_state = DIVING
        self.speed = max(START_SPEED, -float(owner.moving_velocity.y))
        self.facing = float(owner.local_yaw)
        self.impacted = False
        self.recovery = 0.0
        self.roof = None
        owner.jump_velocity = owner.jump_hold_left = 0.0
        owner.ground.velocity = SimVec3()
        owner.flight.velocity = SimVec3()
        owner.knock = SimVec3()
        owner.left_arm.rotation_x = owner.right_arm.rotation_x = ARMS_DOWN

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        if self.impacted:
            self.recovery += dt
            return self.recovery < RECOVERY_SECONDS
        ability, owner = self.ability, self.owner
        if owner.parked or owner.vitals.has("held"):
            return False  # caught on the way down: whoever has hold of them moves them now
        self.speed = min(ability.p("speed"), self.speed + ACCELERATION * dt)
        length = self.speed * dt
        down = SimVec3(0.0, -1.0, 0.0)
        hit = trace(ability.game, center_of(owner), down, length + 1.0, ignore=(owner, *self._through()),
                    radius=.5, characters=(), terrain=False)
        floor = ability.game.world.height_at(float(owner.x), float(owner.z)) + .25
        y = float(owner.y) - length
        if hit.kind in ("object", "tree"):
            ability.combat.damage_hit(owner, hit, self._damage() * OBSTACLE_SHARE, down, kind=PHYSICAL, force=40.0)
            self.passed = (*self._through(), hit.target)
            if hit.kind == "object" and not hit.target.health.broken:
                self.roof = hit.target  # it held: this is where the blow lands, and he goes down beside it
                self._impact(hit.point)
                return True
        if y <= floor or self.elapsed > MAX_SECONDS:
            owner.y = floor
            self._impact(SimVec3(float(owner.x), floor, float(owner.z)))
            return True
        owner.y = y
        if owner.flight.is_flying:
            owner.flight.velocity = down * self.speed
        return True

    def add_impulse(self, _impulse: SimVec3) -> None:
        """A blow on the way down does not slow this."""

    def _through(self) -> tuple:
        return getattr(self, "passed", ())

    def _damage(self) -> float:
        powers = self.owner.powers
        return self.ability.p("damage") * powers.strength * powers.attack_scale

    def _impact(self, point: SimVec3) -> None:
        ability, owner = self.ability, self.owner
        game, combat = ability.game, ability.combat
        style = STYLES[owner.character_id]
        self.impacted = True
        self.movement_state = IMPACT_RECOVERY
        radius = ability.area(RADIUS_SHARE, MAX_RADIUS)
        combat.blast(owner, point, radius, self._damage(), ability.force(60.0, 180.0), kind=EXPLOSION,
                     crater=(min(MAX_CRATER, radius * .35), CRATER_DEPTH, "ground-slam"), cracks=True,
                     burst_scale=style.burst, tint=style.tint)
        game.world._terrain_rebuild_wait = 0.0
        for index in range(RING_PUFFS):
            angle = 2.0 * pi * index / RING_PUFFS
            combat.puffs.emit(point + SimVec3(0.0, 1.0, 0.0), SimVec3(sin(angle) * radius * 1.8, 2.0, cos(angle) * radius * 1.8),
                              style.ring, size=2.0, grow=radius * .22, life=.55)
        for index in range(style.dust_puffs):
            angle = 2.0 * pi * index / style.dust_puffs + .4
            combat.puffs.emit(point + SimVec3(sin(angle) * 2.0, .5, cos(angle) * 2.0),
                              SimVec3(sin(angle) * 14.0, 9.0 + index % 3 * 4.0, cos(angle) * 14.0), DUST, size=2.2,
                              grow=radius * .15, life=.8)
        if owner.controlled:
            game.camera_impulse = max(game.camera_impulse, 2.5)
        game.world.play_power_sound(.8)
        sound = definition(owner.character_id).impact_sound
        if sound:
            Audio(sound, auto_destroy=True)
        self._stand_clear()
        land(owner)  # into the crater just made; flight is over, whatever it was before
        owner.jump_height = owner.jump_velocity = owner.jump_hold_left = 0.0

    def _stand_clear(self) -> None:
        """Something still standing where he came down: to the ground beside it, never inside it."""
        obj, owner = self.roof, self.owner
        if obj is None or not obj.enabled or obj.health.broken:
            return
        half_x, half_z = abs(obj.scale_x) * .5 + OUT_OF_THE_WAY, abs(obj.scale_z) * .5 + OUT_OF_THE_WAY
        dx, dz = float(owner.x) - float(obj.x), float(owner.z) - float(obj.z)
        if half_x - abs(dx) < half_z - abs(dz):
            owner.x = float(obj.x) + (half_x if dx >= 0.0 else -half_x)
        else:
            owner.z = float(obj.z) + (half_z if dz >= 0.0 else -half_z)

    def finish(self) -> None:
        """However it ends, on his feet: nothing is left hanging in the air or holding a pose."""
        owner = self.owner
        owner.left_arm.rotation_x = owner.right_arm.rotation_x = 0.0
        if self.ballistic and not self.impacted:  # caught or thrown again in mid-air: no jump to the ground
            floor = self.ability.game.world.height_at(owner.x, owner.z) + .25
            owner.jump_height = max(0.0, float(owner.y) - floor)
        elif not self.impacted:
            land(owner)
            owner.jump_height = owner.jump_velocity = owner.jump_hold_left = 0.0


class ImpactDive(Ability):
    """No key of its own: F reaches it when the character is already in the air. It has no card."""

    ability_id = "impact_dive"
    survives_nullification = True  # strength and gravity; there is nothing here to nullify

    def _in_an_enemy_sequence(self) -> bool:
        """An enemy's attack still has more to do with this body, so it is not free to break away yet."""
        owner = self.owner
        return any(getattr(other.motion, "target", None) is owner and not getattr(other.motion, "thrown", True)
                   for other in self.combat.in_world)

    def _forced_fall(self) -> bool:
        motion = self.owner.motion
        return isinstance(motion, LaunchedMotion) and not motion.landed

    def available(self) -> bool:
        owner = self.owner
        if not self.usable(quiet=True) or self._in_an_enemy_sequence():  # in a grip, frozen, down, or mid-attack
            return False
        if owner.motion is not None and not self._forced_fall():
            return False
        if owner.motion is None and not (owner.flight.is_flying or owner.keeps_own_height
                                         or owner.jump_height >= MIN_HEIGHT):
            return False
        return float(owner.y) - self.game.world.height_at(float(owner.x), float(owner.z)) >= MIN_HEIGHT

    def press(self) -> None:
        if self.available():
            forced = self.owner.motion is not None
            self.owner.release_motion()  # the throw ends here, and the dive keeps the speed of its fall
            self.owner.falling_from_blow = False
            self.owner.motion = ImpactDiveMotion(self, forced)

    def hud_state(self) -> str:
        return "ON" if isinstance(self.owner.motion, ImpactDiveMotion) else super().hud_state()
