"""Every character's six ability cards and the three values each card can edit.

Range, Damage and Speed are the only power edits per ability, and Health and Healing Speed the
only ones per character. The ability code maps them onto everything else it needs (blast radius, force, beam
width and so on), so a slider can only exist if something uses it. A card shows N/A for a value
that means nothing to that ability.

Range and Speed start at their maximum, Damage and Healing Speed at 20% of their maximum, and
Health at the character's own figure. Every value can still be raised to its maximum.

Cooldown, charge time, effect duration and resource costs are not values at all: abilities are
always ready, always at full output, and sustained ones run until they are switched off.
Passives are fixed character traits, kept here as plain numbers.

Stable IDs: characters use the roster IDs, abilities and parameters the names below.
Nothing here can grant flight.
"""

from __future__ import annotations

import json
import logging
from math import isfinite
import os
from pathlib import Path
from uuid import uuid4

from characters.registry import definition, definitions
from config.ability_cards import *  # noqa: F403

logger = logging.getLogger(__name__)

POWER_FILE = Path(__file__).resolve().parent / "character_powers.json"
SETTINGS_FILE_VERSION = 3
# -- the roster's abilities, each from its character's own file ------------
# What the keys reach. T and Q are universal and have no values.
SCHEMA: dict[str, tuple[Ability, ...]] = {item.character_id: item.abilities for item in definitions()}
SLOT_ABILITIES: dict[str, dict[str, str]] = {item.character_id: dict(item.slots) for item in definitions()}
# Abilities with no key. Neither the player nor AI reaches these, except the squad, who use Omni-Man's
# Flight Charge. Any can be given a key later. They are not on the Power Configuration menu.
KEYLESS: dict[str, tuple[Ability, ...]] = {item.character_id: item.keyless for item in definitions()}
PASSIVES = {item.character_id: item.passives for item in definitions()}
# Only a player may set these off, whoever the character is, and however the attempt is made: see Ability.permitted.
PLAYER_ONLY_KEYS = ("3", "4")
PLAYER_ONLY_ABILITIES: dict[str, frozenset[str]] = {
    character_id: frozenset(ability_id for key, ability_id in slots.items() if key in PLAYER_ONLY_KEYS)
    for character_id, slots in SLOT_ABILITIES.items()}
# A power that has been replaced: what the player set for it carries over to its successor.
RENAMED_ABILITIES = {("RED", "high_jump_punch"): "flying_punch"}





# Abilities with no key. Neither the player nor AI reaches these, except the squad, who use Omni-Man's
# Flight Charge. Any can be given a key later. They are not on the Power Configuration menu.

ABILITIES = {character_id: {ability.ability_id: ability for ability in abilities}
             for character_id, abilities in SCHEMA.items()}
# T stops time for all five. Dash lost Q to the target lock, and Grab has no key while E is
# disabled. None of these is editable.
UNIVERSAL = {
    "dash": Ability("dash", "Quick Dash", ACTIVE, "Q", "A short burst; attacks miss you meanwhile."),
    "world_stop": Ability("world_stop", "Time Stop", ACTIVE, "T",
                          "Freezes the world for exactly 30 seconds while you keep moving and fighting."),
    "grab": card("grab", "Grab and Throw", "", "", reach=300, damage=800, speed=300),
    "impact_dive": card("impact_dive", "Ground Slam", "F", "In the air, F dives at the ground and hits it with a "
                         "blast of real damage.", damage=5000, speed=1500),
}


def character_settings(character_id: str) -> Ability:
    """A character's own settings, in the same form as an ability's."""
    return CHARACTER_SETTINGS[character_id]


def ability_of(character_id: str, ability_id: str) -> Ability:
    if ability_id == CHARACTER:
        return CHARACTER_SETTINGS[character_id]
    table = ABILITIES[character_id]
    if ability_id in table:
        return table[ability_id]
    for ability in KEYLESS[character_id]:
        if ability.ability_id == ability_id:
            return ability
    return UNIVERSAL[ability_id]


def params_of(character_id: str, ability_id: str) -> dict[str, Param]:
    return {param.key: param for param in ability_of(character_id, ability_id).params}






# Running and Flying Speed have no value of their own until someone chooses one: while unset, a character
# moves as its profile and passives say, so a save from before these existed plays exactly as it did.
# Soldier Boy cannot fly, so he has no Flying or Flight Boost Speed to set.
CHARACTER_SETTINGS = {
    character_id: Ability(CHARACTER, "Character", ACTIVE, "", "",
                          (Param(HEALTH, "hp", MAX_HEALTH, start=traits.max_health),
                           Param(HEALING_SPEED, "%", MAX_HEALING_SPEED, start=DEFAULT_HEALING_SPEED),
                           Param(RUN_SPEED, "m/s", MAX_MOVEMENT_SPEED, start=definition(character_id).run_speed or 100.0),
                           *(() if not definition(character_id).kit.can_fly else (
                               Param(FLY_SPEED, "m/s", MAX_MOVEMENT_SPEED, start=definition(character_id).fly_speed or 100.0),
                               Param(BOOST_SPEED, "m/s", MAX_MOVEMENT_SPEED, start=definition(character_id).boost_speed or 200.0)))))
    for character_id, traits in PASSIVES.items()}


class PowerSettings:
    """Current values, by character and ability. Unset values follow the table's defaults."""

    def __init__(self, path: Path | str | None = None) -> None:
        override = os.environ.get("SENTRY_POWER_FILE")
        self.path = Path(path) if path else (Path(override) if override else POWER_FILE)
        self._values: dict[str, dict[str, dict[str, float]]] = {}
        self.load()

    def get(self, character_id: str, ability_id: str, key: str) -> float:
        stored = self._values.get(character_id, {}).get(ability_id, {})
        if key in stored:
            return stored[key]
        return params_of(character_id, ability_id)[key].default

    def chosen(self, character_id: str, ability_id: str, key: str) -> float | None:
        """What has been set, or what the character's own file asks for. Otherwise nothing: no falling back on a default."""
        stored = self._values.get(character_id, {}).get(ability_id, {}).get(key)
        if stored is None and ability_id == CHARACTER and key in MOVEMENT_KEYS:
            return getattr(definition(character_id), key, None)
        return stored

    def set(self, character_id: str, ability_id: str, key: str, value: float) -> float:
        """Store a value, clamped to its limits, and return what was stored."""
        param = ability_of(character_id, ability_id).param(key)
        if param is None:
            raise KeyError(key)
        clamped = param.clamp(value)
        self._values.setdefault(character_id, {}).setdefault(ability_id, {})[key] = clamped
        return clamped

    def reset_ability(self, character_id: str, ability_id: str) -> None:
        self._values.get(character_id, {}).pop(ability_id, None)

    def reset_character(self, character_id: str) -> None:
        self._values.pop(character_id, None)

    def reset_squad(self) -> None:
        stored = self._values.get("GREEN", {}).get("squad_summon", {})
        for key in SQUAD_KEYS:
            stored.pop(key, None)

    def fit_squad_times(self) -> bool:
        """The time out can never be longer than the cycle. True if it had to be shortened."""
        cycle = self.get("GREEN", "squad_summon", SQUAD_CYCLE)
        if self.get("GREEN", "squad_summon", SQUAD_ACTIVE) <= cycle:
            return False
        self.set("GREEN", "squad_summon", SQUAD_ACTIVE, cycle)
        return True

    def reset_movement(self, character_id: str) -> None:
        stored = self._values.get(character_id, {}).get(CHARACTER, {})
        for key in MOVEMENT_KEYS:
            stored.pop(key, None)

    def reset_all(self) -> None:
        self._values.clear()

    def max_character(self, character_id: str) -> None:
        for ability in (*SCHEMA[character_id], CHARACTER_SETTINGS[character_id]):
            for param in ability.params:
                if param.key not in (*MOVEMENT_KEYS, *SQUAD_KEYS):  # not a measure of power
                    self.set(character_id, ability.ability_id, param.key, param.maximum)

    def max_all(self) -> None:
        for character_id in SCHEMA:
            self.max_character(character_id)

    # -- persistence -----------------------------------------------------
    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as error:
            logger.warning("Ignoring unreadable power settings %s (%s)", self.path, error)
            return False
        if raw.get("version") != SETTINGS_FILE_VERSION:
            self._retire_old_file()
            return False
        values = raw.get("values", {})
        for character_id, abilities in (values.items() if isinstance(values, dict) else ()):
            if character_id not in ABILITIES or not isinstance(abilities, dict):
                continue
            for ability_id, stored in abilities.items():
                ability_id = RENAMED_ABILITIES.get((character_id, ability_id), ability_id)
                if (ability_id != CHARACTER and ability_id not in ABILITIES[character_id]) \
                        or not isinstance(stored, dict):
                    continue
                table = params_of(character_id, ability_id)
                for key, value in stored.items():
                    if key not in table or isinstance(value, bool) \
                            or not isinstance(value, (int, float)) or not isfinite(value):
                        continue  # unknown or invalid: the default stays in force
                    self.set(character_id, ability_id, key, value)
        return True

    def _retire_old_file(self) -> None:
        """An older save must not override the current defaults; its file is kept aside, never lost."""
        keep = self.path.with_name(f"{self.path.stem}.before_v{SETTINGS_FILE_VERSION}{self.path.suffix}")
        if keep.exists():
            keep = keep.with_name(f"{keep.stem}.{uuid4().hex[:8]}{keep.suffix}")
        try:
            self.path.replace(keep)
        except OSError:
            logger.warning("Could not set aside old power settings %s", self.path)

    def save(self) -> bool:
        data = {"version": SETTINGS_FILE_VERSION, "values": self._values}
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            try:
                temporary.replace(self.path)
            except PermissionError:
                # Cloud-sync providers can briefly deny the replace; see SentrySettings.save.
                self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except OSError:
            logger.exception("Failed to save power settings to %s", self.path)
            return False
        finally:
            temporary.unlink(missing_ok=True)
