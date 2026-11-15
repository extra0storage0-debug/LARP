"""What an ability card and a character's traits are made of. No game imports: a character's file builds its own from these."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log

ACTIVE, ULTIMATE = "active", "ultimate"
TYPE_LABELS = {ACTIVE: "ACTIVE", ULTIMATE: "ULTIMATE"}
RANGE, DAMAGE, SPEED, HEALTH, HEALING_SPEED = "range", "damage", "speed", "health", "healing_speed"
RUN_SPEED, FLY_SPEED, BOOST_SPEED = "run_speed", "fly_speed", "boost_speed"
SQUAD_VILTRUMITES, SQUAD_MARK, SQUAD_ACTIVE, SQUAD_CYCLE = "viltrumites", "mark", "active_seconds", "cycle_seconds"
SQUAD_KEYS = (SQUAD_VILTRUMITES, SQUAD_MARK, SQUAD_ACTIVE, SQUAD_CYCLE)
TOGGLE = "toggle"  # as a unit: this value is a switch, 1 for on
MOVEMENT_KEYS = (RUN_SPEED, FLY_SPEED, BOOST_SPEED)
PARAM_KEYS = (RANGE, DAMAGE, SPEED)
PARAM_LABELS = {RANGE: "Range", DAMAGE: "Damage", SPEED: "Speed", HEALTH: "Health",
                HEALING_SPEED: "Healing Speed", RUN_SPEED: "Running Speed", FLY_SPEED: "Flying Speed", BOOST_SPEED: "Flight Boost Speed",
                SQUAD_VILTRUMITES: "Viltrumites", SQUAD_MARK: "Mark Grayson", SQUAD_ACTIVE: "Active Time",
                SQUAD_CYCLE: "Cycle Time"}
MAX_RANGE = 100000.0
MAX_HEALTH = 100000.0
DEFAULT_DAMAGE_SHARE = .2
MAX_HEALING_SPEED = 100.0
MAX_MOVEMENT_SPEED = 5000.0
DEFAULT_HEALING_SPEED = 20.0
FULL_HEAL_SECONDS = 10.0  # at 100%; a share of health, so it scales with the Health setting
CHARACTER = "character"  # where a character's own settings are stored, beside its abilities
MAX_CARDS = 6


@dataclass(frozen=True, slots=True)
class Param:
    key: str
    unit: str
    maximum: float
    minimum: float = 1.0
    start: float | None = None  # where it begins, if not at its maximum
    linear: bool = False        # small counts and switches, rather than a huge range

    @property
    def label(self) -> str:
        return PARAM_LABELS[self.key]

    @property
    def default(self) -> float:
        return self.maximum if self.start is None else self.start

    def clamp(self, value: float) -> float:
        value = float(value)
        if value != value:  # NaN
            return self.default
        return round(max(self.minimum, min(self.maximum, value)))

    def fraction(self, value: float) -> float:
        """Where a value sits on the slider, which is logarithmic so huge ranges stay usable."""
        if self.linear:
            return (max(self.minimum, value) - self.minimum) / (self.maximum - self.minimum)
        return log(max(self.minimum, value) / self.minimum) / log(self.maximum / self.minimum)

    def value_at(self, fraction: float) -> float:
        fraction = max(0.0, min(1.0, float(fraction)))
        if self.linear:
            return self.clamp(self.minimum + fraction * (self.maximum - self.minimum))
        return self.clamp(self.minimum * exp(fraction * log(self.maximum / self.minimum)))


@dataclass(frozen=True, slots=True)
class Ability:
    ability_id: str
    name: str
    kind: str
    binding: str
    description: str
    params: tuple[Param, ...] = ()

    def param(self, key: str) -> Param | None:
        return next((param for param in self.params if param.key == key), None)


def card(ability_id, name, binding, description, *, kind=ACTIVE, reach=MAX_RANGE, damage=None,
          damage_unit="dmg", speed=None, speed_unit="m/s", damage_start=None, extra=()) -> Ability:
    params = [Param(RANGE, "m", float(reach))]
    if damage is not None:
        start = round(damage * DEFAULT_DAMAGE_SHARE) if damage_start is None else damage_start
        params.append(Param(DAMAGE, damage_unit, float(damage), start=float(start)))
    if speed is not None:
        params.append(Param(SPEED, speed_unit, float(speed)))
    params.extend(extra)
    return Ability(ability_id, name, kind, binding, description, tuple(params))


def physical(name="Superhuman Physical Combat") -> Ability:
    return card("melee", name, "+ and -",
                 "+ punches and - kicks the nearest enemy in range, rushing in and turning to face "
                 "them. A kick knocks them back further. Weak targets take a finishing blow.",
                 reach=300, damage=2500, speed=1000)


def high_speed_attack() -> Ability:
    return card("high_speed_attack", "High-Speed Punch Attack", "2",
                 "Stops the world, charges the nearest enemy at ultra-high speed and lands one huge "
                 "punch that sends them flying, flies on past them, and time resumes.",
                 damage=6000, speed=3000)


def time_stop() -> Ability:
    return card("time_stop", "Time-Stop Nuclear Execution", "3",
                 "Stops the world, drives the nearest enemy into the ground by the neck, and one punch "
                 "sets off a nuclear-level explosion. Range sets its size. Then time resumes.",
                 damage=20000, speed=1500)


def massive_blast() -> Ability:
    return card("massive_blast", "Massive Spherical Bomb Blast", "4",
                 "A huge spherical explosion around you: full damage to every enemy inside it, and "
                 "trees, buildings, objects and terrain are torn up.",
                 damage=20000)


@dataclass(frozen=True, slots=True)
class Passives:
    """A character's fixed traits. Strength, stamina and energy never run out for anyone."""

    names: tuple[str, ...]
    strength: float = 1.0
    max_health: float = 1000.0
    resistance: float = 0.0
    impact_resistance: float = 0.0
    knockback_resistance: float = 0.0
    radiation_resistance: float = 0.0
    absorb: float = 0.0  # health regained per 100 damage taken
    speed: float = 1.0
    collision_damage: float = 60.0
    hearing_radius: float = 0.0
