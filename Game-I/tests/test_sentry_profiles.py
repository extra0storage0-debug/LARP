"""The two general settings profiles: validation, storage and old saves."""

import json
from pathlib import Path
import re
import tempfile
import unittest

from config.sentry_config import SentrySettings
from config.sentry_profiles import (CATEGORIES, ENEMY, ENEMY_SETTINGS, MAX_INPUT_DIGITS, PLAYER,
                                    PLAYER_SETTINGS, SETTINGS, ProfileStore, coerce)

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FOLDERS = ("ai", "characters", "game", "movement", "ui", "world")


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.simple = SentrySettings(folder / "sentry_settings.json")
        self.path = folder / "sentry_profiles.json"
        self.store = ProfileStore(self.simple, self.path)


class RegistryTests(unittest.TestCase):
    def test_exactly_two_profiles(self):
        self.assertEqual(set(SETTINGS), {PLAYER, ENEMY})

    def test_every_setting_has_a_known_category_and_kind(self):
        known = {category for category, _label in CATEGORIES}
        for table in SETTINGS.values():
            for setting in table.values():
                self.assertIn(setting.category, known, setting.key)
                self.assertIn(setting.kind, ("int", "toggle", "key"), setting.key)

    def test_camera_and_input_belong_to_the_player(self):
        self.assertFalse([s.key for s in ENEMY_SETTINGS.values() if s.category in ("camera", "input")])

    def test_original_camera_defaults(self):
        expected = {"mouse_sensitivity_pct": 100, "camera_smoothing": 12,
                    "camera_follow_distance_cm": 950, "camera_follow_height_cm": 355,
                    "camera_fov": 82}
        for key, value in expected.items():
            self.assertEqual(PLAYER_SETTINGS[key].default, value, key)

    def test_only_field_of_view_has_a_ceiling(self):
        limited = {s.key for table in SETTINGS.values() for s in table.values()
                   if s.maximum is not None}
        self.assertEqual(limited, {"camera_fov"})

    def test_every_default_passes_its_own_validation(self):
        for table in SETTINGS.values():
            for setting in table.values():
                self.assertEqual(coerce(setting, setting.default), setting.default, setting.key)

    def test_every_setting_is_read_by_game_code(self):
        """A setting nothing consumes would be a fake control, so it fails here."""
        code = "\n".join(path.read_text(encoding="utf-8") for folder in SOURCE_FOLDERS
                         for path in (ROOT / folder).rglob("*.py"))
        unread = []
        for table in SETTINGS.values():
            for setting in table.values():
                readers = [setting.key, *(legacy for legacy, _scale in setting.derives)]
                if setting.kind == "key":
                    readers = [setting.key.removeprefix("key_")]
                if setting.simple:
                    continue
                if not any(re.search(rf'["\']{re.escape(name)}["\']', code) for name in readers):
                    unread.append(setting.key)
        self.assertEqual(unread, [])


class CoerceTests(unittest.TestCase):
    def test_large_strings_keep_every_digit(self):
        setting = PLAYER_SETTINGS["mouse_sensitivity_pct"]
        self.assertEqual(coerce(setting, "987654321012345678"), 987654321012345678)

    def test_out_of_range_is_refused_not_clamped(self):
        for setting, value in ((PLAYER_SETTINGS["camera_fov"], "-5"),
                               (PLAYER_SETTINGS["camera_fov"], "180"),
                               (ENEMY_SETTINGS["boost_multiplier_pct"], 0)):
            with self.assertRaises(ValueError, msg=setting.key):
                coerce(setting, value)
        self.assertEqual(coerce(PLAYER_SETTINGS["camera_pitch_min"], "-200"), -200)

    def test_non_integers_are_refused(self):
        setting = PLAYER_SETTINGS["camera_fov"]
        for value in ("90.6", 90.6, "fast", "", "-", None, float("inf"), float("nan")):
            with self.assertRaises(ValueError, msg=repr(value)):
                coerce(setting, value)

    def test_too_many_digits_are_refused(self):
        with self.assertRaises(ValueError):
            coerce(PLAYER_SETTINGS["mouse_sensitivity_pct"], "1" + "0" * MAX_INPUT_DIGITS)


class StoreTests(StoreTestCase):
    def test_loading_alone_writes_nothing(self):
        self.assertEqual(self.store.get(PLAYER, "camera_fov"), 82)
        self.assertFalse(self.path.exists())

    def test_saved_values_survive_a_restart_exactly(self):
        self.store.set(PLAYER, "mouse_sensitivity_pct", "123456789012345")
        self.store.set(ENEMY, "reaction_speed_pct", 73)
        self.store.set(PLAYER, "key_team_manager", "n")
        self.assertTrue(self.store.save())
        reloaded = ProfileStore(SentrySettings(self.simple.config_path), self.path)
        self.assertEqual(reloaded.get(PLAYER, "mouse_sensitivity_pct"), 123456789012345)
        self.assertEqual(reloaded.get(ENEMY, "reaction_speed_pct"), 73)
        self.assertEqual(reloaded.get(PLAYER, "key_team_manager"), "n")

    def test_ai_speeds_never_copy_the_player(self):
        self.simple.set("flight_speed", 9999)
        self.assertEqual(self.store.get(ENEMY, "flight_speed"), 100)

    def test_old_save_with_powers_loads_and_the_powers_are_gone(self):
        self.path.write_text(json.dumps({"version": 1, "profiles": {
            PLAYER: {"heat_vs_sentry": 500, "time_stop_enabled": 1, "camera_fov": 90},
            ENEMY: {"flight_speed": 111, "blast_vs_sentry": 9000, "heat_enabled": 1}}}),
            encoding="utf-8")
        store = ProfileStore(self.simple, self.path)
        self.assertEqual(store.get(PLAYER, "camera_fov"), 90)
        self.assertEqual(store.get(ENEMY, "flight_speed"), 111)
        store.save()
        saved = json.loads(self.path.read_text(encoding="utf-8"))["profiles"]
        self.assertNotIn("heat_vs_sentry", saved[PLAYER])
        self.assertNotIn("blast_vs_sentry", saved[ENEMY])

    def test_old_settings_file_drops_power_values_on_save(self):
        self.simple.config_path.write_text(json.dumps({
            "flight_speed": 321, "heat_vision_damage": 9999, "ground_impact_power": 9999}),
            encoding="utf-8")
        settings = SentrySettings(self.simple.config_path)
        self.assertEqual(settings.get("flight_speed"), 321)
        settings.save()
        saved = json.loads(self.simple.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["flight_speed"], 321)
        self.assertNotIn("heat_vision_damage", saved)
        self.assertNotIn("ground_impact_power", saved)

    def test_corrupt_file_falls_back_to_defaults(self):
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertLogs("config.sentry_profiles", level="WARNING"):
            store = ProfileStore(self.simple, self.path)
        self.assertEqual(store.get(PLAYER, "camera_fov"), 82)

    def test_reset_category_only_touches_that_category(self):
        self.store.set(PLAYER, "camera_fov", 110)
        self.store.set(PLAYER, "show_fps", 1)
        self.store.reset(PLAYER, "camera")
        self.assertEqual(self.store.get(PLAYER, "camera_fov"), 82)
        self.assertEqual(self.store.get(PLAYER, "show_fps"), 1)


if __name__ == "__main__":
    unittest.main()
