"""A new character is one file: it plays, fights, saves and loads, and nothing else had to change or breaks. Each case is a real start, in its own process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
NEW_CHARACTER = '''
from characters.costume_parts import CharacterKit
from characters.definition import CharacterDefinition
from config.ability_cards import Passives, card, physical

DEFINITION = CharacterDefinition(
    character_id="TEST_SUPE",
    kit=CharacterKit("TEST_SUPE", "TEST SUPE", True, "Someone from another universe altogether."),
    abilities=(card("heat_vision", "Borrowed Beams", "1", "Superman's code, on somebody else.", damage=3000, damage_unit="dmg/s"), physical()),
    slots={"1": "heat_vision"},
    passives=Passives(("Flight",), strength=1.2, max_health=4321),
    powers=("powers.superman:HeatVision", "powers.common:Melee", "powers.common:Dash", "powers.common:Grab", "powers.universal:WorldTimeStop"),
    model="WHITE",
    order=6,
    default_team="enemy_team",
    run_speed=77.0,
    impact_sound="assets/audio/impact.wav",
    card_tint=(10, 200, 200),
)
'''
BROKEN = {
    "syntax": "this is not python",
    "no_definition": "VALUE = 1\n",
    "missing_power": NEW_CHARACTER.replace('"powers.superman:HeatVision"', '"powers.superman:NoSuchThing"').replace("TEST_SUPE", "BROKEN_A"),
    "bad_slot": NEW_CHARACTER.replace('slots={"1": "heat_vision"}', 'slots={"1": "no_such_ability"}').replace("TEST_SUPE", "BROKEN_B"),
    "taken_id": NEW_CHARACTER.replace("TEST_SUPE", "WHITE"),
}
PROBE = r"""
import sys, json
sys.path.insert(0, r'{root}')
import main
from characters.roster import ROSTER_IDS
app, game = main.build_game("none")
teams, combat = game.teams, game.combat
def run(frames):
    for _ in range(frames):
        game.update(1.0 / 60.0)
        app.step()
result = dict(roster=list(ROSTER_IDS), bodies=list(teams.characters), player=teams.state.player, ai_only=[])
{body}
print("RESULT " + json.dumps(result))
"""
PLAY = r"""
body = teams.characters["TEST_SUPE"]
result["team_default"] = teams.state.team_of("TEST_SUPE")
result["max_health"] = body.vitals.max_health
result["uses_model"] = body.visual.rig is not None
run(30)
result["ai_ran"] = True
game.team_panel.open()
assert "TEST_SUPE" in game.team_panel.rows
game.team_panel.close()
game.power_panel.open()
game.power_panel.select_character("TEST_SUPE")
run(1)
game.power_panel.close()
teams.state.assignment["TEST_SUPE"] = "my_team"
teams.swap("TEST_SUPE", save=False)
result["controlled"] = game.sentry is body and body.controlled
run(2)
result["hud"] = game.hud.status.text
enemy = next(c for c in teams.characters.values() if c is not body and combat.hostile(body, c))
enemy.position = (body.x, body.y, body.z + 20.0)
before = enemy.vitals.damage_taken
game.input("q")
game.input("1")
run(60)
game.input("1")
result["beam_hit"] = enemy.vitals.damage_taken > before
game.input("q")
game.input("f")
run(10)
result["flew"] = body.flight.is_flying
game.input("f")
for _ in range(600):
    run(1)
    if not body.flight.is_flying and body.motion is None:
        break
result["landed"] = not body.flight.is_flying
result["run_speed"] = game.combat.settings.chosen("TEST_SUPE", "character", "run_speed")
teams.save_session()
"""
RELOAD = r"""
result["player_after_reload"] = teams.state.player
result["session_kept"] = "TEST_SUPE" in teams.state.session
"""


class NewCharacterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.saves = Path(self.folder.name)
        self.addons = self.saves / "supes"
        self.addons.mkdir()

    def tearDown(self):
        self.folder.cleanup()

    def start(self, body: str = "", addons: bool = True) -> tuple[dict, str]:
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SENTRY_ROSTER_FILE=str(self.saves / "roster.json"),
                           SENTRY_POWER_FILE=str(self.saves / "powers.json"), SENTRY_PROFILE_FILE=str(self.saves / "profiles.json"),
                           SENTRY_DESTRUCTION_SAVE=str(self.saves / "damage.json"), NLTL_EXTRA_SUPES=str(self.addons) if addons else "")
        done = subprocess.run([sys.executable, "-c", PROBE.format(root=ROOT, body=body)], cwd=ROOT, env=environment, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        line = next(line for line in done.stdout.splitlines() if line.startswith("RESULT "))
        return json.loads(line[7:]), done.stderr

    def add(self, name: str, source: str) -> None:
        (self.addons / f"{name}.py").write_text(source, encoding="utf-8")

    def test_one_file_makes_a_character_who_plays_saves_and_loads(self):
        self.add("test_supe", NEW_CHARACTER)
        played, _ = self.start(PLAY)
        self.assertEqual(played["roster"], ["WHITE", "BLACK", "YELLOW", "GREEN", "RED", "TEST_SUPE"])
        self.assertIn("TEST_SUPE", played["bodies"])
        self.assertEqual(played["team_default"], "enemy_team")
        self.assertEqual(played["max_health"], 4321)
        self.assertTrue(played["uses_model"])
        self.assertTrue(played["controlled"])
        self.assertIn("TEST SUPE", played["hud"])
        self.assertTrue(played["beam_hit"])
        self.assertTrue(played["flew"])
        self.assertTrue(played["landed"])
        self.assertEqual(played["run_speed"], 77.0)
        reloaded, _ = self.start(RELOAD)
        self.assertEqual(reloaded["player_after_reload"], "TEST_SUPE")
        self.assertTrue(reloaded["session_kept"])

    def test_a_save_still_loads_after_the_character_is_taken_out_again(self):
        self.add("test_supe", NEW_CHARACTER)
        self.start(PLAY)
        for path in self.addons.glob("*.py"):
            path.unlink()
        result, _ = self.start()
        self.assertEqual(result["roster"], ["WHITE", "BLACK", "YELLOW", "GREEN", "RED"])
        self.assertIn(result["player"], result["roster"])

    def test_an_old_save_gets_the_new_character_without_changing_anyone_else(self):
        old = {"version": 1, "player": "GREEN", "assignment": {"YELLOW": "enemy_team", "WHITE": "enemy_team", "GREEN": "my_team", "BLACK": "my_team", "RED": "enemy_team"}}
        (self.saves / "roster.json").write_text(json.dumps(old), encoding="utf-8")
        self.add("test_supe", NEW_CHARACTER.replace('default_team="enemy_team",', ""))
        result, _ = self.start('result["assignment"] = teams.state.assignment')
        self.assertEqual(result["player"], "GREEN")
        self.assertEqual({key: value for key, value in result["assignment"].items() if key != "TEST_SUPE"}, old["assignment"])
        self.assertEqual(result["assignment"]["TEST_SUPE"], "available")

    def test_a_broken_character_file_is_left_out_and_the_game_still_starts(self):
        for name, source in BROKEN.items():
            self.add(name, source)
        result, errors = self.start()
        self.assertEqual(result["roster"], ["WHITE", "BLACK", "YELLOW", "GREEN", "RED"])
        for name in ("syntax", "missing_power", "bad_slot", "taken_id"):
            self.assertIn(f"{name}.py left out", errors)


if __name__ == "__main__":
    unittest.main()
