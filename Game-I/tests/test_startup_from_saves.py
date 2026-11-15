"""The game has to start from any save, not only a new one: each in its own process, as a real launch is."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
PROBE = """
import sys
sys.path.insert(0, r'{root}')
import main
app, game = main.build_game("none")
assert game.teams.state.player == '{player}', game.teams.state.player
assert game.sentry is game.teams.characters['{player}'], game.sentry.display_name
assert game.sentry.controlled
for _ in range(10):
    game.update(1.0 / 60.0)
    app.step()
print("STARTED", game.sentry.display_name)
"""


class StartupTests(unittest.TestCase):
    def start_as(self, player: str, assignment: dict | None = None) -> None:
        with tempfile.TemporaryDirectory() as folder:
            roster = Path(folder) / "roster.json"
            roster.write_text(json.dumps({"version": 1, "player": player, "assignment": assignment or {player: "my_team"}}), encoding="utf-8")
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SENTRY_ROSTER_FILE=str(roster),
                               SENTRY_POWER_FILE=str(Path(folder) / "powers.json"), SENTRY_PROFILE_FILE=str(Path(folder) / "profiles.json"),
                               SENTRY_DESTRUCTION_SAVE=str(Path(folder) / "damage.json"))
            done = subprocess.run([sys.executable, "-c", PROBE.format(root=ROOT, player=player)], cwd=ROOT, env=environment, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=240)
            self.assertEqual(done.returncode, 0, done.stderr[-1500:])
            self.assertIn("STARTED", done.stdout)

    def test_every_character_can_be_the_one_a_save_starts_as(self):
        for player in ("YELLOW", "WHITE", "GREEN", "BLACK", "RED"):
            with self.subTest(player):
                self.start_as(player)

    def test_an_older_save_with_nobody_named_still_starts(self):
        with tempfile.TemporaryDirectory() as folder:
            roster = Path(folder) / "roster.json"
            roster.write_text("{}", encoding="utf-8")
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SENTRY_ROSTER_FILE=str(roster),
                               SENTRY_POWER_FILE=str(Path(folder) / "powers.json"), SENTRY_PROFILE_FILE=str(Path(folder) / "profiles.json"),
                               SENTRY_DESTRUCTION_SAVE=str(Path(folder) / "damage.json"))
            done = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{ROOT}'); import main; main.build_game('none'); print('STARTED')"],
                                  cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
            self.assertIn("STARTED", done.stdout, done.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
