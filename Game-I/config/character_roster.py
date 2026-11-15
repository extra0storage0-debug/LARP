"""Who is on which team, who the player controls, and each character's flight choices.

Every character is in exactly one of three places. Old or hand-edited saves are checked
on load: unknown characters such as Purple or Blue, and any old powers, are dropped.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from characters.registry import default_player, definitions
from characters.roster import KITS, ROSTER_IDS

logger = logging.getLogger(__name__)

ROSTER_FILE = Path(__file__).resolve().parent / "character_roster.json"
MY_TEAM, ENEMY_TEAM, AVAILABLE = "my_team", "enemy_team", "available"
TEAMS = (MY_TEAM, ENEMY_TEAM, AVAILABLE)
TEAM_LABELS = {MY_TEAM: "MY TEAM", ENEMY_TEAM: "ENEMY TEAM", AVAILABLE: "AVAILABLE"}

FLIGHT_SPEEDS = {"SLOW": .6, "NORMAL": 1.0, "FAST": 1.6}
FLIGHT_BOOSTS = {"LOW": .7, "NORMAL": 1.0, "HIGH": 1.4}
_DEFAULT_CHARACTER = {"flight_enabled": True, "flight_speed": "NORMAL",
                      "flight_boost": "NORMAL", "helmet": False}


class RosterError(ValueError):
    """A team change that would break a roster rule; the message is shown to the player."""


class RosterState:
    def __init__(self, path: Path | str | None = None) -> None:
        override = os.environ.get("SENTRY_ROSTER_FILE")
        self.path = Path(path) if path else (Path(override) if override else ROSTER_FILE)
        self.reset_all()
        self.load()

    def reset_all(self) -> None:
        self.player = default_player()
        self.assignment = {item.character_id: item.default_team for item in definitions()}
        self.characters = {character_id: dict(_DEFAULT_CHARACTER) for character_id in ROSTER_IDS}
        self.session: dict = {}  # health, energy, cooldowns and positions from the last save
        self.auto_target_lock = False  # key 8

    def members(self, team: str) -> list[str]:
        return [character_id for character_id in ROSTER_IDS
                if self.assignment[character_id] == team]

    def team_of(self, character_id: str) -> str:
        return self.assignment[character_id]

    def settings(self, character_id: str) -> dict:
        return self.characters[character_id]

    # -- rules -----------------------------------------------------------
    def move(self, character_id: str, team: str) -> None:
        if team not in TEAMS:
            raise RosterError(f"Unknown team {team}")
        if character_id == self.player and team != MY_TEAM:
            others = [other for other in self.members(MY_TEAM) if other != character_id]
            if others:
                raise RosterError(f"You control {KITS[character_id].display}: swap to "
                                  f"{KITS[others[0]].display} first")
            raise RosterError(f"You control {KITS[character_id].display}: add another "
                              "character to My Team and swap first")
        self.assignment[character_id] = team

    def select_player(self, character_id: str) -> None:
        if self.assignment[character_id] != MY_TEAM:
            raise RosterError(f"{KITS[character_id].display} must be on My Team first")
        self.player = character_id

    def set_flight(self, character_id: str, enabled: bool) -> None:
        self._require_flyer(character_id)
        self.characters[character_id]["flight_enabled"] = bool(enabled)

    def cycle_flight_speed(self, character_id: str) -> str:
        return self._cycle(character_id, "flight_speed", FLIGHT_SPEEDS)

    def cycle_flight_boost(self, character_id: str) -> str:
        return self._cycle(character_id, "flight_boost", FLIGHT_BOOSTS)

    def _cycle(self, character_id: str, key: str, options: dict) -> str:
        self._require_flyer(character_id)
        names = tuple(options)
        current = self.characters[character_id][key]
        self.characters[character_id][key] = names[(names.index(current) + 1) % len(names)]
        return self.characters[character_id][key]

    @staticmethod
    def _require_flyer(character_id: str) -> None:
        if not KITS[character_id].can_fly:
            raise RosterError(f"{KITS[character_id].display} is ground-bound")

    def reset_character(self, character_id: str) -> None:
        self.characters[character_id] = dict(_DEFAULT_CHARACTER)

    def flight_allowed(self, character_id: str) -> bool:
        return KITS[character_id].can_fly and self.characters[character_id]["flight_enabled"]

    # -- persistence -----------------------------------------------------
    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as error:
            logger.warning("Ignoring unreadable roster %s (%s)", self.path, error)
            return False
        assignment = raw.get("assignment", {})
        if isinstance(assignment, dict):
            for character_id in ROSTER_IDS:
                if assignment.get(character_id) in TEAMS:
                    self.assignment[character_id] = assignment[character_id]
        characters = raw.get("characters", {})
        if isinstance(characters, dict):
            for character_id in ROSTER_IDS:
                stored = characters.get(character_id)
                if isinstance(stored, dict):
                    self._load_character(character_id, stored)
        session = raw.get("session", {})
        if isinstance(session, dict):
            self.session = {character_id: session[character_id] for character_id in ROSTER_IDS
                            if isinstance(session.get(character_id), dict)}
        self.auto_target_lock = raw.get("auto_target_lock") is True
        player = raw.get("player")
        if player in ROSTER_IDS:
            self.player = player
        # The player must always be a real My Team member.
        if self.assignment[self.player] != MY_TEAM:
            mine = self.members(MY_TEAM)
            self.player = mine[0] if mine else self.player
            self.assignment[self.player] = MY_TEAM
        return True

    def _load_character(self, character_id: str, stored: dict) -> None:
        settings = self.characters[character_id]
        if isinstance(stored.get("flight_enabled"), bool):
            settings["flight_enabled"] = stored["flight_enabled"]
        if stored.get("flight_speed") in FLIGHT_SPEEDS:
            settings["flight_speed"] = stored["flight_speed"]
        if stored.get("flight_boost") in FLIGHT_BOOSTS:
            settings["flight_boost"] = stored["flight_boost"]
        if isinstance(stored.get("helmet"), bool):
            settings["helmet"] = stored["helmet"]

    def save(self) -> bool:
        data = {"version": 1, "player": self.player, "assignment": self.assignment,
                "characters": self.characters, "session": self.session, "auto_target_lock": self.auto_target_lock}
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
            logger.exception("Failed to save the roster to %s", self.path)
            return False
        finally:
            temporary.unlink(missing_ok=True)
