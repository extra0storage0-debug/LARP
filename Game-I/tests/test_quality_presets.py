import json
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from config import (
    GraphicsSettings,
    QUALITY_PRESETS,
    QUALITY_RESOLUTIONS,
    load_settings,
    save_settings,
)


class QualityPresetTests(unittest.TestCase):
    def test_low_quality_is_default_and_targets_1600_by_900(self):
        settings = GraphicsSettings()
        self.assertEqual(settings.quality, "low")
        self.assertEqual(QUALITY_RESOLUTIONS[settings.quality], (1600, 900))

    def test_all_quality_levels_have_requested_resolutions(self):
        self.assertEqual(QUALITY_RESOLUTIONS["medium"], (1600, 900))
        self.assertEqual(QUALITY_RESOLUTIONS["high"], (1600, 900))
        self.assertEqual(QUALITY_RESOLUTIONS["ultra"], (1920, 1080))
        self.assertEqual(set(QUALITY_PRESETS), set(QUALITY_RESOLUTIONS))

    def test_invalid_document_and_individual_values_use_safe_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            with patch("config.CONFIG_PATH", settings_path):
                settings_path.write_text("[]", encoding="utf-8")
                self.assertEqual(load_settings(), GraphicsSettings())

                settings_path.write_text(json.dumps({
                    "quality": "HIGH",
                    "render_distance": "bad",
                    "civilian_count": 500,
                    "debris_lifetime": float("nan"),
                    "day_length_seconds": 3600,
                }), encoding="utf-8")
                loaded = load_settings()

            self.assertEqual(loaded.quality, "high")
            self.assertEqual(loaded.render_distance, QUALITY_PRESETS["high"].render_distance)
            self.assertEqual(loaded.civilian_count, 30)
            self.assertEqual(loaded.debris_lifetime, QUALITY_PRESETS["high"].debris_lifetime)
            self.assertEqual(loaded.day_length_seconds, 3600)

    def test_settings_save_replaces_file_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            with patch("config.CONFIG_PATH", settings_path):
                save_settings(GraphicsSettings(quality="medium"))
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["quality"], "medium")
            self.assertFalse(settings_path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
