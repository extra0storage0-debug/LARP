"""Copy this file, rename it without the underscore, and the character is in the game the next time it starts.

Documentation/ADDING_A_CHARACTER.md explains each field. This one borrows Superman's body and beam so that it runs as it stands.
"""

from __future__ import annotations

from characters.costume_parts import CharacterKit
from characters.definition import CharacterDefinition
from config.ability_cards import Passives, card, physical

KIT = CharacterKit("NEW_SUPE", "NEW SUPE", True, "One line about who they are, for the character screens.")

ABILITIES = (
    card("heat_vision", "Their Beam", "1", "What it does, for the Powers & Abilities screen.", damage=3000, damage_unit="dmg/s"),
    physical(),
)

DEFINITION = CharacterDefinition(
    character_id="NEW_SUPE",  # stable: saves are keyed on it
    kit=KIT,
    abilities=ABILITIES,
    slots={"1": "heat_vision"},
    passives=Passives(("Flight", "Enhanced Strength"), strength=1.2, max_health=1000),
    powers=("powers.superman:HeatVision", "powers.common:Melee", "powers.common:Dash", "powers.common:Grab", "powers.universal:WorldTimeStop"),
    model="WHITE",            # their own folder under assets/characters once they have one
    order=6,
    default_team="available",
    card_tint=(40, 200, 200),
)
