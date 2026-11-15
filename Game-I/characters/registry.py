"""The roster: every file in characters/supes/ that holds a DEFINITION, found when the game starts.

Nothing here imports the engine, so that any table in the game can be built from it at import time. A file that is
broken is reported and left out; the rest of the roster still plays. Names beginning with an underscore are skipped.
"""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec, module_from_spec, spec_from_file_location
import logging
import os
from pathlib import Path
import pkgutil
import re
import sys

from characters.definition import CharacterDefinition

logger = logging.getLogger(__name__)

BASE_BODY = "YELLOW"  # the first body built, before anyone else exists; the game needs this one
_TEAMS = ("my_team", "enemy_team", "available")
_ID = re.compile(r"[A-Z][A-Z0-9_]*$")
_definitions: dict[str, CharacterDefinition] = {}


def _source_of(module: str) -> str:
    loaded = sys.modules.get(module)
    origin = getattr(loaded, "__file__", None) or getattr(find_spec(module), "origin", None)
    if not origin:
        raise ValueError(f"no module {module}")
    return Path(origin).read_text(encoding="utf-8")


def _check(definition: CharacterDefinition) -> None:
    """Refuse what would only fail later, in the middle of somebody's fight. Reads the power code without running it."""
    if not _ID.match(definition.character_id):
        raise ValueError(f"character_id {definition.character_id!r} must be capitals, digits and underscores")
    if definition.character_id in _definitions:
        raise ValueError(f"character_id {definition.character_id} is already taken")
    if definition.default_team not in _TEAMS:
        raise ValueError(f"default_team {definition.default_team!r} is not one of {_TEAMS}")
    sources = {}
    for path in definition.powers:
        module, _, name = path.partition(":")
        sources.setdefault(module, _source_of(module))
        if not re.search(rf"^class {re.escape(name)}\b", sources[module], re.M):
            raise ValueError(f"power {path} does not exist")
    code = "\n".join(sources.values())
    for card in (*definition.abilities, *definition.keyless):
        if f'"{card.ability_id}"' not in code:
            raise ValueError(f"ability {card.ability_id} has no power behind it")
    known = {card.ability_id for card in (*definition.abilities, *definition.keyless)}
    for key, ability_id in definition.slots.items():
        if ability_id not in known:
            raise ValueError(f"key {key} is bound to {ability_id}, which is not one of their abilities")


def register_character(definition: CharacterDefinition) -> None:
    _check(definition)
    if definition.seed is None:
        definition = replace(definition, seed=3000 + sum(map(ord, definition.character_id)) * 37)
    _definitions[definition.character_id] = definition


def _register_module(module, label: str) -> None:
    item = getattr(module, "DEFINITION", None)
    if item is None:
        logger.warning("Character file %s has no DEFINITION; left out", label)
        return
    register_character(item)


def _discover() -> None:
    from characters import supes
    for found in pkgutil.iter_modules(supes.__path__):
        if found.name.startswith("_"):
            continue
        try:
            _register_module(import_module(f"characters.supes.{found.name}"), found.name)
        except Exception as error:  # noqa: BLE001 (one broken character must not stop the game)
            logger.warning("Character file %s left out: %s", found.name, error)
            print(f"Character file {found.name} left out: {error}", file=sys.stderr)
    # Other folders of character files, for trying one out without touching the project.
    for folder in filter(None, os.environ.get("NLTL_EXTRA_SUPES", "").split(os.pathsep)):
        for path in sorted(Path(folder).glob("*.py")):
            if path.name.startswith("_"):
                continue
            name = f"nltl_extra_{path.stem}"
            try:
                spec = spec_from_file_location(name, path)
                module = module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
                _register_module(module, path.name)
            except Exception as error:  # noqa: BLE001
                sys.modules.pop(name, None)
                logger.warning("Character file %s left out: %s", path.name, error)
                print(f"Character file {path.name} left out: {error}", file=sys.stderr)
    if BASE_BODY not in _definitions:
        raise RuntimeError(f"characters/supes/ must define {BASE_BODY}, the first body the game builds")


def definitions() -> tuple[CharacterDefinition, ...]:
    return tuple(sorted(_definitions.values(), key=lambda item: (item.order, item.character_id)))


def definition(character_id: str) -> CharacterDefinition:
    return _definitions[character_id]


def default_player() -> str:
    return next((item.character_id for item in definitions() if item.starts_as_player), BASE_BODY)


def model_of(name: str) -> str:
    """The folder of a body's files. Omni-Man's squad are not on the roster, and have their own."""
    item = _definitions.get(name)
    return (item.model or name) if item is not None else name


_discover()
