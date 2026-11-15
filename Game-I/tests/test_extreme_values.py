"""Every ability at every slider's limits: whatever a player sets must not break the game."""

from __future__ import annotations

import unittest

from characters.roster import ROSTER_IDS
from config.power_schema import SCHEMA
from game_fixture import FRAME, reset_game
from movement.flight_physics import FlightPhase

KEYS = ("1", "2", "3", "4", "e", "q", "r", "=", "-", "left mouse down", "right mouse down")
RELEASES = {"left mouse down": "left mouse up", "right mouse down": "right mouse up"}


class ExtremeValueTests(unittest.TestCase):
    def _exercise(self, pick) -> None:
        game = reset_game(ai_powers=True)
        settings = game.combat.settings
        for character_id in ROSTER_IDS:
            for ability in SCHEMA[character_id]:
                for param in ability.params:
                    settings.set(character_id, ability.ability_id, param.key, pick(param))
        game.apply_sentry_config()
        game.elapsed = 100.0  # AI past its opening grace period, so it uses these values too
        for character_id in ROSTER_IDS:
            game.teams.swap(character_id, save=False)
            body = game.sentry
            for airborne in (False, True):
                if airborne and body.flight_allowed:
                    body.flight.phase = FlightPhase.CRUISE
                    body.y += 30.0
                for key in KEYS:
                    game.input(key)
                    for _ in range(8):
                        game.update(FRAME)
                    game.input(RELEASES.get(key, f"{key} up"))
                    game.input(key)  # a second press: off, throw, recall, cycle
                    game.input(RELEASES.get(key, f"{key} up"))
                    for _ in range(4):
                        game.update(FRAME)
            for _ in range(30):
                game.update(FRAME)
            for value in (body.x, body.y, body.z, body.vitals.health):
                self.assertEqual(value, value, f"{character_id} produced NaN")
            self.assertLessEqual(body.y, 500.0 + 60.0, character_id)
            self.assertLessEqual(body.vitals.health, body.vitals.max_health)
            self.assertLessEqual(len(game.combat.projectiles), 40, character_id)
            if character_id == "RED":
                self.assertFalse(body.flight.is_flying, "no setting may lift Soldier Boy")

    def test_every_slider_at_its_maximum(self):
        self._exercise(lambda param: param.maximum)

    def test_every_slider_at_its_minimum(self):
        self._exercise(lambda param: param.minimum)


if __name__ == "__main__":
    unittest.main()
