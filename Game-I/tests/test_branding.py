"""The game's name, its words, its look, and that a save from before the rename still reads."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = ("ai", "characters", "combat", "config", "game", "movement", "powers", "ui", "world")
BANNED = re.compile(r"\b(super)?hero(es)?\b|\bsaviou?r\b|\bvillains?\b|epstein", re.I)


class WordsTests(unittest.TestCase):
    def _files(self):
        for folder in FOLDERS:
            yield from (ROOT / folder).rglob("*.py")
        yield ROOT / "main.py"
        yield ROOT / "README.md"
        yield from (ROOT / "Documentation").glob("*.md")

    def test_the_old_words_are_gone_everywhere_a_person_reads(self):
        found = []
        for path in self._files():
            for number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
                if BANNED.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:80]}")
        self.assertEqual(found, [])

    def test_the_old_game_name_is_not_in_any_string_the_ui_shows(self):
        pattern = re.compile(r'"[^"]*\bSentry\b[^"]*"|"[^"]*\bSENTRY\b[^"_]*"')
        allowed = {"movement", "powers"}
        found = []
        for path in (ROOT / "ui").glob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                if pattern.search(line):
                    found.append(f"{path.name}:{number}")
        self.assertEqual(found, [], allowed)

    def test_the_name_is_written_in_one_place(self):
        from config.branding import GAME_TITLE, TAGLINE
        self.assertEqual(GAME_TITLE, "NO LIMIT TO LARP")
        self.assertEqual(TAGLINE, "NO RULES. NO LIMITS. JUST SUPES.")
        self.assertIn("GAME_TITLE", (ROOT / "main.py").read_text(encoding="utf-8-sig"))

    def test_the_assets_are_there_and_the_fonts_carry_their_licence(self):
        for name in ("branding/logo.png", "branding/backdrop.jpg", "branding/icon.ico", "fonts/Anton-Regular.ttf", "fonts/Anton-OFL.txt",
                     "fonts/BarlowCondensed-SemiBold.ttf", "fonts/BarlowCondensed-OFL.txt"):
            self.assertTrue((ROOT / "assets" / name).exists(), name)
        self.assertIn("Open Font License", (ROOT / "assets/fonts/Anton-OFL.txt").read_text(encoding="utf-8"))

    def test_the_launcher_points_at_the_game(self):
        self.assertTrue((ROOT / "Play No Limit To Larp.bat").exists())
        self.assertFalse((ROOT / "Play Sentry.bat").exists())
        self.assertIn("main.py", (ROOT / "Play No Limit To Larp.bat").read_text(encoding="utf-8"))


class RosterTests(unittest.TestCase):
    def test_the_five_are_all_on_the_roster_in_order(self):
        from characters.roster import KITS, ROSTER_IDS
        self.assertEqual(ROSTER_IDS, ("WHITE", "BLACK", "YELLOW", "GREEN", "RED"))
        self.assertEqual([KITS[item].display for item in ROSTER_IDS], ["SUPERMAN", "HOMELANDER", "SENTRY", "OMNI-MAN", "SOLDIER BOY"])

    def test_each_defines_everything_itself(self):
        from characters.registry import definitions
        for item in definitions():
            with self.subTest(item.character_id):
                self.assertTrue(item.kit.display and item.kit.description)
                self.assertTrue(item.abilities and item.slots and item.powers)
                self.assertTrue(item.movement and item.stance)
                self.assertGreater(item.passives.max_health, 0)
                self.assertIn(item.default_team, ("my_team", "enemy_team", "available"))
                self.assertTrue((ROOT / "assets" / "characters" / (item.model or item.character_id) / "model.bam").exists())
                self.assertTrue((ROOT / "assets" / "portraits" / f"{item.character_id.lower()}.png").exists())

    def test_every_table_in_the_game_is_built_from_the_definitions(self):
        from ai.enemy_team_ai import PERSONALITIES
        from characters.registry import definitions
        from config.power_schema import CHARACTER_SETTINGS, KEYLESS, PASSIVES, SCHEMA, SLOT_ABILITIES
        from movement.character_styles import STYLES
        from powers.ground_impact import STYLES as IMPACTS
        from powers.loadout import PowerSet
        from powers.universal import PUNCH_STYLES
        for item in definitions():
            for table in (PERSONALITIES, STYLES, SCHEMA, SLOT_ABILITIES, KEYLESS, PASSIVES, CHARACTER_SETTINGS, IMPACTS, PUNCH_STYLES, PowerSet.CLASSES):
                self.assertIn(item.character_id, table)


class SaveCompatibilityTests(unittest.TestCase):
    """Save files, and their names, are the same as they were before the rename."""

    def test_a_save_from_before_the_rename_loads_as_it_was(self):
        with tempfile.TemporaryDirectory() as folder:
            roster = Path(folder) / "roster.json"
            old = {"version": 1, "player": "GREEN",
                   "assignment": {"YELLOW": "enemy_team", "WHITE": "available", "GREEN": "my_team", "BLACK": "my_team", "RED": "enemy_team"},
                   "characters": {"BLACK": {"flight_enabled": True, "flight_speed": "FAST", "flight_boost": "HIGH", "helmet": False}},
                   "session": {"GREEN": {"position": [10.0, 5.0, 12.0], "flying": False}}, "auto_target_lock": True}
            roster.write_text(json.dumps(old), encoding="utf-8")
            code = (f"import sys,json; sys.path.insert(0, r'{ROOT}')\n"
                    "from config.character_roster import RosterState\n"
                    f"state=RosterState(r'{roster}')\n"
                    "print('STATE '+json.dumps([state.player,state.assignment,state.characters['BLACK'],state.auto_target_lock,list(state.session)]))")
            done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            line = next(line for line in done.stdout.splitlines() if line.startswith("STATE "))
            player, assignment, black, auto, session = json.loads(line[6:])
            self.assertEqual(player, "GREEN")
            self.assertEqual(assignment, old["assignment"])
            self.assertEqual(black["flight_speed"], "FAST")
            self.assertTrue(auto)
            self.assertEqual(session, ["GREEN"])

    def test_the_save_files_keep_their_names(self):
        from config.character_roster import ROSTER_FILE
        from config.power_schema import POWER_FILE
        from config.sentry_profiles import PLAYER, PROFILE_FILE
        self.assertEqual(ROSTER_FILE.name, "character_roster.json")
        self.assertEqual(POWER_FILE.name, "character_powers.json")
        self.assertEqual(PROFILE_FILE.name, "sentry_profiles.json")
        self.assertEqual(PLAYER, "my_sentry")  # a key inside that file; the player never sees it


if __name__ == "__main__":
    unittest.main()
