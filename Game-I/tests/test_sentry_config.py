"""Regression and validation tests for simple Sentry settings and menu."""

import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config.sentry_config import (
    DEFAULT_SETTINGS,
    SIMPLE_SETTINGS,
    SentrySettings,
)


class SimpleSentryConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config" / "sentry_settings.json"
        self.settings = SentrySettings(self.config_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_simple_settings_exist_with_requested_defaults(self):
        expected_defaults = {
            "flight_speed": 100,
            "flight_boost_speed": 500,
            "ground_speed": 50,
        }
        for key, expected_val in expected_defaults.items():
            self.assertIn(key, DEFAULT_SETTINGS, f"Setting '{key}' missing from DEFAULT_SETTINGS")
            self.assertEqual(
                self.settings.get(key),
                expected_val,
                f"Setting '{key}' default mismatch: expected {expected_val}, got {self.settings.get(key)}"
            )

    def test_integer_conversion_and_bounds(self):
        self.settings.set("flight_speed", "250")
        self.assertEqual(self.settings.get("flight_speed"), 250)

        # Floating string converted to rounded int
        self.settings.set("flight_boost_speed", "749.6")
        self.assertEqual(self.settings.get("flight_boost_speed"), 750)

        # Negative values clamped to at least 1
        self.settings.set("ground_speed", -50)
        self.assertEqual(self.settings.get("ground_speed"), 1)

        # Invalid string defaults safely
        self.settings.set("flight_speed", "not_a_number")
        self.assertEqual(self.settings.get("flight_speed"), 100)

    def test_reset_restores_all_defaults(self):
        self.settings.set("flight_speed", 300)
        self.settings.set("ground_speed", 77)

        self.assertEqual(self.settings.get("flight_speed"), 300)
        self.assertEqual(self.settings.get("ground_speed"), 77)

        self.settings.reset()
        self.assertEqual(self.settings.get("flight_speed"), 100)
        self.assertEqual(self.settings.get("ground_speed"), 50)

    def test_json_persistence(self):
        self.settings.set("flight_speed", 220)
        self.settings.set("flight_boost_speed", 330)
        self.assertTrue(self.settings.save())
        self.assertTrue(self.config_path.exists())

        # Load into separate instance
        loaded = SentrySettings(self.config_path)
        self.assertEqual(loaded.get("flight_speed"), 220)
        self.assertEqual(loaded.get("flight_boost_speed"), 330)
        self.assertEqual(loaded.get("ground_speed"), 50)

    def test_save_falls_back_when_atomic_replace_is_denied(self):
        self.settings.set("flight_speed", 275)
        with patch.object(Path, "replace", side_effect=PermissionError("sync lock")):
            with self.assertLogs("config.sentry_config", level=logging.WARNING):
                self.assertTrue(self.settings.save())

        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["flight_speed"], 275)
        self.assertFalse(list(self.config_path.parent.glob("*.tmp")))

    def test_corrupted_json_handled_gracefully(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text("{broken: json syntax", encoding="utf-8")

        fallback = SentrySettings(self.config_path)
        self.assertEqual(fallback.get("flight_speed"), 100)

    def test_partial_json_preserves_unspecified_defaults(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps({"flight_speed": 180}), encoding="utf-8")

        loaded = SentrySettings(self.config_path)
        self.assertEqual(loaded.get("flight_speed"), 180)
        self.assertEqual(loaded.get("flight_boost_speed"), 500)

    def test_legacy_aliases_mapped(self):
        # Setting via alias updates the simple key
        self.settings.set("normal_flight_speed", 140)
        self.assertEqual(self.settings.get("flight_speed"), 140)
        self.assertEqual(self.settings.get("normal_flight_speed"), 140)

        # Setting simple key updates alias getter
        self.settings.set("flight_speed", 400)
        self.assertEqual(self.settings.get("max_flight_speed"), 400)

    def test_listener_failures_are_logged_and_do_not_block_other_listeners(self):
        called = []

        def broken_listener():
            raise RuntimeError("listener failure")

        self.settings.add_listener(broken_listener)
        self.settings.add_listener(lambda: called.append(True))
        with self.assertLogs("config.sentry_config", level=logging.ERROR):
            self.settings.set("flight_speed", 120)
        self.assertEqual(called, [True])


if __name__ == "__main__":
    unittest.main()
