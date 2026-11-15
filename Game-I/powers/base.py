"""What every ability shares: its three values, automatic aim, and the beam and cone shapes.

There are no cooldowns, charge times or costs. A press acts at full output straight away, and
a sustained ability stays on until its key is pressed again or something genuinely stops it.
"""

from __future__ import annotations

from functools import wraps
from math import radians, sin, cos

from ursina import color

from config.power_schema import ABILITIES, PLAYER_ONLY_ABILITIES, ability_of
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import MAX_TRACE, center_of, in_cone, objects_in_radius, trace, trees_in_radius
from powers.vitals import HEAT

BEAM_TRACE_INTERVAL = 1.0 / 15.0
CONE_TICK = .1
CONE_HALF_ANGLE = 15.0
EYE_HEIGHT = 2.5
# Trees and objects are only searched this far around a breath or tendril; characters are not limited.
AREA_EFFECT_REACH = 150.0
PUFF_MAX_SPEED = 400.0
BEAM_WIDTH = (.12, .45)


def _only_if_permitted(method):
    @wraps(method)
    def activate(self, *args, **kwargs):
        if self.permitted:
            return method(self, *args, **kwargs)
        return None
    return activate


class Ability:
    ability_id = ""
    # Abilities a nullified Compound V character keeps, such as plain punches.
    survives_nullification = False

    def __init_subclass__(cls, **kwargs) -> None:
        """Every way of setting an ability off goes through the permission, including in abilities not written yet."""
        super().__init_subclass__(**kwargs)
        for name in ("press", "kick"):
            if name in cls.__dict__:
                setattr(cls, name, _only_if_permitted(cls.__dict__[name]))

    def __init__(self, owner) -> None:
        self.owner = owner
        self.character_id = owner.character_id
        self.active = False

    @property
    def permitted(self) -> bool:
        """AI never sets off what is on a character's keys 3 and 4. Which those are comes from the character's own file."""
        return self.owner.controlled or self.ability_id not in PLAYER_ONLY_ABILITIES.get(self.character_id, ())

    # -- shared reads ----------------------------------------------------
    @property
    def game(self):
        return self.owner.team.game

    @property
    def combat(self):
        return self.game.combat

    @property
    def vitals(self):
        return self.owner.vitals

    def p(self, key: str) -> float:
        return self.combat.settings.get(self.character_id, self.ability_id, key)

    @property
    def is_card(self) -> bool:
        return self.ability_id in ABILITIES[self.character_id]

    def reach(self) -> float:
        """Range in metres, as far as anything in the world can actually be."""
        return min(self.p("range"), MAX_TRACE)

    def area(self, fraction: float, cap: float) -> float:
        """A radius from Range: it grows with Range up to what the engine can handle at once."""
        return max(1.0, min(cap, self.p("range") * fraction))

    def _fraction(self, key: str) -> float:
        param = ability_of(self.character_id, self.ability_id).param(key)
        return param.fraction(self.p(key))

    def force(self, low: float, high: float) -> float:
        """Knockback, force and the like all follow Damage."""
        return low + (high - low) * self._fraction("damage")

    def boost(self, low: float, high: float) -> float:
        """A multiplier that also follows Damage."""
        return self.force(low, high)

    def say(self, message: str) -> None:
        if self.owner.controlled:
            self.game.notify(message)

    # -- aim -------------------------------------------------------------
    def target(self, reach: float | None = None, exclude=None):
        return self.combat.targets.for_ability(self.owner, self.reach() if reach is None else reach,
                                               exclude)

    def aim(self, origin: SimVec3 | None = None, reach: float | None = None):
        """(origin, direction, target): at the nearest enemy, or along the camera if there is none."""
        owner = self.owner
        reach = self.reach() if reach is None else reach
        target = self.target(reach)
        if target is not None:
            start = origin if origin is not None else SimVec3(owner.x, owner.y + EYE_HEIGHT, owner.z)
            return start, (center_of(target) - start).normalized(), target
        if origin is not None:
            return origin, owner.aim_direction_from(origin, reach), None
        start, direction = owner.aim_ray()
        return start, direction, None

    def aim_hit(self, limit: float, *, radius: float = 0.0, ignore=()):
        """What the camera is pointing at, for abilities that work on the world."""
        origin, direction = self.owner.aim_ray()
        return trace(self.game, origin, direction, limit, ignore=(self.owner, *ignore),
                     radius=radius, characters=self.combat.others_of(self.owner))

    def facing(self) -> SimVec3:
        owner = self.owner
        return self.game.planet.heading(SimVec3(owner.x, owner.y, owner.z), owner.local_yaw)

    # -- activation ------------------------------------------------------
    def usable(self, *, quiet: bool = False) -> bool:
        vitals = self.vitals
        if vitals.immobile:
            return False
        if vitals.nullified and not self.survives_nullification:
            if not quiet:
                self.say("POWERS NULLIFIED")
            return False
        return True

    @property
    def name(self) -> str:
        return ability_of(self.character_id, self.ability_id).name

    def press(self) -> None:
        return None

    def release(self) -> None:
        return None

    def update(self, dt: float) -> None:
        return None

    def cancel(self) -> None:
        """Stop safely, for a swap or being downed."""
        self.active = False

    def on_input_lost(self) -> None:
        """A menu opened or focus was lost: sustained effects carry on, armed ones disarm."""
        return None

    def reset(self) -> None:
        """Back to its starting state."""
        self.cancel()

    def hud_state(self) -> str:
        if self.vitals.nullified and not self.survives_nullification:
            return "NULL"
        return "ON" if self.active else ""


class BeamAbility(Ability):
    """A sustained twin eye beam: traced at a fixed rate, with damage for the time in between."""

    CORE = color.rgb32(255, 236, 200)
    GLOW = color.rgba32(255, 50, 18, 110)
    FLARE = None  # the impact's colour, if not the usual fire
    KIND = HEAT

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.visual = None
        self._trace_timer = 0.0
        self._stored = 0.0
        self._last_hit = None

    def beam_values(self) -> tuple[float, float, float]:
        """Damage per second, range and width at this moment."""
        raise NotImplementedError

    def beam_width(self) -> float:
        low, high = BEAM_WIDTH
        return low + (high - low) * self._fraction("range")

    def aim_offset(self, direction: SimVec3) -> SimVec3:
        return direction

    def beam_origin(self) -> SimVec3 | None:
        """Where the beam leaves the body, or None for the eyes' height."""
        return None

    def beam_starts(self) -> tuple:
        return self.owner.eye_points()

    def keep_firing(self, target) -> bool:
        return True

    def beam_limit(self, limit: float) -> float:
        return limit

    def press(self) -> None:
        if self.active:
            self._stop()
        elif self.usable():
            self.active = True
            self._trace_timer = 0.0
            self._stored = 0.0
            self._last_hit = None

    def cancel(self) -> None:
        self._stop()

    def _stop(self) -> None:
        self.active = False
        if self.visual is not None:
            self.combat.release_beam(self.visual)
            self.visual = None
        self._last_hit = None

    def update(self, dt: float) -> None:
        if not self.active:
            return
        if self.vitals.immobile or self.vitals.nullified:
            self._stop()
            return
        damage, reach, width = self.beam_values()
        self._stored += damage * dt
        self._trace_timer -= dt
        if self._trace_timer <= 0.0 or self._last_hit is None:
            self._trace_timer = BEAM_TRACE_INTERVAL
            origin, direction, target = self.aim(self.beam_origin(), reach=reach)
            if not self.keep_firing(target):
                self._stop()
                return
            direction = self.aim_offset(direction)
            limit = reach
            if target is not None:  # no need to search the far side of the island
                limit = min(reach, (center_of(target) - origin).length() + 10.0)
            self._last_hit = trace(self.game, origin, direction, self.beam_limit(limit), ignore=(self.owner,),
                                   radius=width * .5,
                                   characters=self.combat.others_of(self.owner))
            self.on_beam_hit(self._last_hit, self._stored, direction)
            self._stored = 0.0
        if self.visual is None:
            self.visual = self.combat.acquire_beam()
        if self.visual is not None:
            self.visual.show(self.beam_starts(), self._last_hit.point, width,
                             self.CORE, self.GLOW, self.FLARE)

    def on_beam_hit(self, hit, damage: float, direction: SimVec3) -> None:
        self.combat.damage_hit(self.owner, hit, damage * self.owner.powers.energy_scale,
                               direction, kind=self.KIND, force=1.0)


class ConeAbility(Ability):
    """A sustained breath: acts on everything in a cone ten times a second."""

    PUFF = (200, 230, 255, 150)

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self._timer = 0.0
        self._since_tick = 0.0

    def press(self) -> None:
        if self.active:
            self.active = False
        elif self.usable():
            self.active = True
            self._timer = 0.0
            self._since_tick = CONE_TICK

    def update(self, dt: float) -> None:
        if not self.active:
            return
        if self.vitals.immobile or self.vitals.nullified:
            self.active = False
            return
        reach = self.reach()
        mouth = self.owner.mouth_point()
        _origin, direction, target = self.aim(reach=reach)
        if target is not None:
            direction = (center_of(target) - mouth).normalized()
        puff_speed = min(PUFF_MAX_SPEED, reach * 1.3)
        self.combat.puffs.emit(mouth, direction * puff_speed, self.PUFF,
                               size=.5, grow=min(12.0, reach * .10), life=.55)
        self._timer -= dt
        self._since_tick += dt
        if self._timer > 0.0:
            return
        self._timer = CONE_TICK
        seconds, self._since_tick = self._since_tick, 0.0
        for enemy in self.combat.hostiles_of(self.owner):
            if in_cone(mouth, direction, center_of(enemy), reach, CONE_HALF_ANGLE):
                self.on_character(enemy, direction, seconds)
        nearby = min(reach, AREA_EFFECT_REACH)
        for obj in objects_in_radius(self.game, mouth, nearby):
            if in_cone(mouth, direction, SimVec3(obj.x, obj.y, obj.z), nearby, CONE_HALF_ANGLE):
                self.on_object(obj, direction, seconds)
        for tree in trees_in_radius(self.game, mouth, nearby):
            if in_cone(mouth, direction, SimVec3(tree.x, tree.y, tree.z), nearby, CONE_HALF_ANGLE):
                self.on_tree(tree, direction, seconds)
        self.on_tick(mouth, direction, nearby, seconds)

    def on_character(self, target, direction, seconds) -> None:
        return None

    def on_object(self, obj, direction, seconds) -> None:
        return None

    def on_tree(self, tree, direction, seconds) -> None:
        return None

    def on_tick(self, origin, direction, reach, seconds) -> None:
        return None


class Motion:
    """Takes over a character's movement for a moment, and owns its path while it runs."""

    facing = None  # the yaw to hold, for a motion that must look at something other than the camera
    movement_state = None  # what it counts as, if it is more than just moving
    ballistic = False  # the body is flying under its own weight: this carries on even if it goes down
    knocked_down = False  # someone else's blow is doing this to the body, and its player can fight out of it

    def __init__(self, owner) -> None:
        self.owner = owner
        self.elapsed = 0.0

    def step(self, dt: float) -> bool:
        """Advance one frame; False ends the motion."""
        raise NotImplementedError

    def finish(self) -> None:
        return None

    def _move(self, velocity: SimVec3, dt: float) -> None:
        from characters.roster_character import clamp_to_world
        owner = self.owner
        owner.x += velocity.x * dt
        owner.y += velocity.y * dt
        owner.z += velocity.z * dt
        clamp_to_world(owner, owner.team.game.world, owner.team.game.planet)


def land(owner) -> None:
    """End a dive standing on the ground, whatever flight phase it began in."""
    owner.flight.phase = FlightPhase.GROUNDED
    owner.flight.phase_time = 0.0
    owner.flight.velocity = SimVec3()
    owner.ground.velocity = SimVec3()
    owner.y = owner.team.game.world.height_at(owner.x, owner.z) + .25


def sweep_angle(direction: SimVec3, degrees: float) -> SimVec3:
    """Rotate a direction about the vertical axis."""
    angle = radians(degrees)
    c, s = cos(angle), sin(angle)
    return SimVec3(direction.x * c + direction.z * s, direction.y,
                   -direction.x * s + direction.z * c).normalized()
