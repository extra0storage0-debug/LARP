"""The roster, as the rest of the game reads it. Each character's own file in characters/supes/ is what defines them."""

from __future__ import annotations

from characters.costume_parts import *  # noqa: F403
from characters.costume_parts import SQUAD_KITS, CharacterKit
from characters.registry import definitions

KITS = {definition.character_id: definition.kit for definition in definitions()}
ROSTER_IDS = tuple(KITS)


def kit_of(name: str) -> CharacterKit:
    """A costume by its palette name: one of the roster, or one of Omni-Man's squad."""
    return KITS[name] if name in KITS else SQUAD_KITS[name]


def can_fly(character_id: str) -> bool:
    return KITS[character_id].can_fly
