"""One character's abilities, how keys reach them, and what its passives add up to."""

from __future__ import annotations

from importlib import import_module

from characters.registry import definitions
from config.power_schema import (CHARACTER, FULL_HEAL_SECONDS, HEALING_SPEED, HEALTH, PASSIVES,
                                 SLOT_ABILITIES, character_settings)
from powers import omni_man
from powers.common import Dash, Grab, Melee, ThrowingGrab
from powers.fx import Bubble
from powers.ground_impact import ImpactDive
from powers.vitals import Vitals



def _power_class(path: str):
    """"module:Class", as a character's file names it."""
    module, name = path.split(":")
    return getattr(import_module(module), name)


# Each character's own list, and F in the air for everyone: it is not on a key slot, F decides between it and flight or jumping.
_ACTIVE_CLASSES = {item.character_id: (*(_power_class(path) for path in item.powers), ImpactDive) for item in definitions()}
ICE_TINT = (170, 225, 255, 130)
SLOTS = ("1", "2", "3", "4", "t", "+", "-")


class PowerSet:
    CLASSES = _ACTIVE_CLASSES
    SLOTS = SLOT_ABILITIES

    def __init__(self, owner) -> None:
        self.owner = owner
        character_id = owner.character_id
        self.character_id = character_id
        self.abilities = {cls.ability_id: cls(owner) for cls in self.CLASSES[character_id]}
        self.slots = {key: self.abilities[ability_id]
                      for key, ability_id in self.SLOTS[character_id].items()}
        if "melee" in self.abilities:  # Soldier Boy is given no punch or kick key
            self.slots["+"] = self.slots["-"] = self.abilities["melee"]
        if "world_stop" in self.abilities:
            self.slots["t"] = self.abilities["world_stop"]
        self.held: set[str] = set()
        self.aiming = False
        self.strength = 1.0
        self.speed = 1.0
        self.hearing_radius = 0.0
        self.collision_damage = 0.0
        self.absorb_rate = 0.0
        self.cold = 0.0
        self.ice_shell = Bubble(owner, ICE_TINT)
        owner.vitals = Vitals()
        self.apply_passives()

    # -- passives --------------------------------------------------------
    def _character_setting(self, key: str) -> float:
        """A menu value for this character; the combat system does not exist on the very first call."""
        combat = self.owner.team.game.combat
        if combat is None:
            return character_settings(self.character_id).param(key).default
        return combat.settings.get(self.character_id, CHARACTER, key)

    def apply_passives(self) -> None:
        traits = PASSIVES[self.character_id]
        vitals = self.owner.vitals
        fraction = vitals.fraction
        maximum = self._character_setting(HEALTH)
        vitals.max_health = maximum
        vitals.health = maximum * fraction if not vitals.downed else 0.0
        vitals.resistance = traits.resistance
        vitals.impact_resistance = traits.impact_resistance
        vitals.knockback_resistance = traits.knockback_resistance
        vitals.radiation_resistance = traits.radiation_resistance
        vitals.regen = self._character_setting(HEALING_SPEED) * .01 / FULL_HEAL_SECONDS
        self.strength = traits.strength
        self.speed = traits.speed
        self.collision_damage = traits.collision_damage
        self.hearing_radius = traits.hearing_radius
        self.absorb_rate = traits.absorb

    # -- multipliers other abilities read --------------------------------
    @property
    def attack_scale(self) -> float:
        scale = 1.0
        solar = self.abilities.get("solar_overcharge")
        if solar is not None:
            scale *= solar.damage_scale
        void = self.abilities.get("void_unleashed")
        if void is not None and void.engaged:
            scale *= void.attack_scale
        return scale

    @property
    def energy_scale(self) -> float:
        scale = 1.0
        solar = self.abilities.get("solar_overcharge")
        if solar is not None:
            scale *= solar.damage_scale
        void = self.abilities.get("void_unleashed")
        if void is not None and void.engaged:
            scale *= void.energy_attack_scale
        return scale

    @property
    def tendril_scale(self) -> float:
        void = self.abilities.get("void_unleashed")
        return void.tendril_scale if void is not None and void.engaged else 1.0

    @property
    def firing_chest_beam(self) -> bool:
        beam = self.abilities.get("chest_beam")
        return beam is not None and beam.active

    @property
    def braced(self) -> bool:
        """What this character's own power sets off around it must not throw it."""
        blast = self.abilities.get("radiation_blast")
        return self.firing_chest_beam or (blast is not None and blast.active)

    def gain_from_damage(self, amount: float) -> None:
        """Sentry's Energy Absorption: part of the damage he takes comes back as health."""
        if self.absorb_rate > 0.0:
            self.owner.vitals.heal(amount * .01 * self.absorb_rate)

    # -- input -----------------------------------------------------------
    def press(self, slot: str) -> None:
        if slot in self.held:
            return  # a key repeat, or a second press with no release, does nothing
        self.held.add(slot)
        ability = self.slots.get(slot)
        if ability is None:
            return
        if self.owner.controlled and ability.usable(quiet=True):
            self.owner.recover_from_knockdown()  # thrown or flat on the ground, a player can still fight
        if slot == "-":
            ability.kick()
        else:
            ability.press()

    def release(self, slot: str) -> None:
        if slot not in self.held:
            return
        self.held.discard(slot)
        ability = self.slots.get(slot)
        if ability is not None:
            ability.release()

    def release_held(self) -> None:
        """Let go of everything, as if every key had come up."""
        for slot in tuple(self.held):
            self.release(slot)

    def on_input_lost(self) -> None:
        """A menu or lost focus: held keys are forgotten, and sustained effects carry on."""
        self.held.clear()
        self.aiming = False
        for ability in self.abilities.values():
            ability.on_input_lost()

    def cancel_all(self) -> None:
        """A swap, being downed or being nullified: every temporary state ends."""
        self.held.clear()
        self.aiming = False
        for ability in self.abilities.values():
            ability.cancel()

    def update(self, dt: float) -> None:
        for ability in self.abilities.values():
            ability.update(dt)
        vitals = self.owner.vitals
        if vitals.has("frozen"):
            self.ice_shell.show(4.4)
        else:
            self.ice_shell.hide()
        if self.cold > 0.0:
            self.cold = max(0.0, self.cold - dt * .1)

    def hard_reset(self) -> None:
        """Back to full."""
        self.cancel_all()
        for ability in self.abilities.values():
            ability.reset()
        vitals = self.owner.vitals
        vitals.health = vitals.max_health
        vitals.statuses.clear()
        vitals.downed_for = 0.0
        vitals.damage_taken = 0.0
        self.owner.pose_root.setP(0.0)
        self.cold = 0.0

    # -- saves -----------------------------------------------------------
    def snapshot(self) -> dict:
        return {"vitals": self.owner.vitals.snapshot()}

    def restore(self, saved: dict) -> None:
        vitals = saved.get("vitals")
        if isinstance(vitals, dict):
            self.owner.vitals.restore(vitals)


class PuppetPowers(PowerSet):
    """Nothing: an execution moves this body, and the damage is its master's."""

    CLASSES = {character_id: () for character_id in _ACTIVE_CLASSES}
    SLOTS = {character_id: {} for character_id in _ACTIVE_CLASSES}


class SquadPowers(PowerSet):
    """One of Omni-Man's squad: his punches, kicks, grapples and charge, at their share of his strength."""

    CLASSES = {"GREEN": (Melee, omni_man.FlightCharge, ThrowingGrab)}
    SLOTS = {"GREEN": {}}

    def apply_passives(self) -> None:
        """A share of his maximum health, and none of his healing: their health only ever goes down."""
        vitals = self.owner.vitals
        fraction = vitals.fraction
        super().apply_passives()
        vitals.max_health = self._character_setting(HEALTH) * self.owner.health_share
        vitals.health = 0.0 if vitals.downed else vitals.max_health * fraction
        vitals.regen = 0.0
        self.absorb_rate = 0.0
        self.strength *= self.owner.power_share
