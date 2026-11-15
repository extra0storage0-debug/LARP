"""Healing Speed: one per character, on the menu, and really what restores health."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from characters.roster import ROSTER_IDS
from config.character_roster import MY_TEAM
from config.power_schema import (CHARACTER, DEFAULT_HEALING_SPEED, FULL_HEAL_SECONDS, HEALING_SPEED,
                                 MAX_HEALING_SPEED, PASSIVES, SCHEMA, SETTINGS_FILE_VERSION,
                                 PowerSettings, character_settings)
from game_fixture import FRAME, reset_game, run_frames
from power_fixture import PowerCase
from powers.vitals import PHYSICAL, Vitals


class RuleTests(unittest.TestCase):
    def test_each_character_has_exactly_these_two_settings(self):
        for character_id in ROSTER_IDS:
            params = character_settings(character_id).params
            self.assertEqual([param.key for param in params][:2], ["health", "healing_speed"])
            param = character_settings(character_id).param(HEALING_SPEED)
            self.assertEqual(param.default, MAX_HEALING_SPEED * .2, "20% of the maximum")
            self.assertEqual(param.clamp(1e9), MAX_HEALING_SPEED)

    def test_abilities_do_not_gain_a_healing_value(self):
        for abilities in SCHEMA.values():
            for ability in abilities:
                self.assertIsNone(ability.param(HEALING_SPEED), ability.ability_id)

    def test_nothing_heals_apart_from_the_setting(self):
        for traits in PASSIVES.values():
            for removed in ("regen", "regen_delay", "sun_regen"):
                self.assertFalse(hasattr(traits, removed), removed)

    def test_healing_stops_at_the_maximum_and_while_downed(self):
        vitals = Vitals(max_health=1000.0, health=999.0, regen=.1)
        vitals.tick(5.0)
        self.assertEqual(vitals.health, 1000.0)
        vitals.take(1e9)
        self.assertTrue(vitals.downed)
        vitals.tick(1.0)
        self.assertEqual(vitals.health, 0.0)


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "powers.json"

    def test_values_are_independent_and_survive_a_restart(self):
        store = PowerSettings(self.path)
        for rate, character_id in enumerate(ROSTER_IDS, start=1):
            store.set(character_id, CHARACTER, HEALING_SPEED, rate * 10)
        self.assertTrue(store.save())
        loaded = PowerSettings(self.path)
        for rate, character_id in enumerate(ROSTER_IDS, start=1):
            self.assertEqual(loaded.get(character_id, CHARACTER, HEALING_SPEED), rate * 10)

    def test_a_current_save_written_before_this_setting_is_kept_and_gets_the_default(self):
        self.path.write_text(json.dumps({
            "version": SETTINGS_FILE_VERSION,
            "values": {"WHITE": {"ground_execution": {"speed": 104}, "character": {"health": 100000}}},
        }), encoding="utf-8")
        loaded = PowerSettings(self.path)
        self.assertEqual(loaded.get("WHITE", CHARACTER, "health"), 100000)
        self.assertEqual(loaded.get("WHITE", "ground_execution", "speed"), 104)
        self.assertEqual(loaded.get("WHITE", CHARACTER, HEALING_SPEED), DEFAULT_HEALING_SPEED)
        self.assertTrue(self.path.exists(), "the file is not set aside")
        self.assertEqual(list(self.path.parent.glob("*before*")), [])

    def test_invalid_saved_values_fall_back_or_clamp(self):
        self.path.write_text(json.dumps({"version": SETTINGS_FILE_VERSION, "values": {
            "WHITE": {"character": {"healing_speed": "fast"}},
            "BLACK": {"character": {"healing_speed": 1e9}},
            "RED": {"character": {"healing_speed": -5}},
        }}), encoding="utf-8")
        loaded = PowerSettings(self.path)
        self.assertEqual(loaded.get("WHITE", CHARACTER, HEALING_SPEED), DEFAULT_HEALING_SPEED)
        self.assertEqual(loaded.get("BLACK", CHARACTER, HEALING_SPEED), MAX_HEALING_SPEED)
        self.assertEqual(loaded.get("RED", CHARACTER, HEALING_SPEED), 1)


class GameplayTests(PowerCase, unittest.TestCase):
    PLAYER = "WHITE"

    def set_speed(self, character, percent: float) -> None:
        self.combat.settings.set(character.character_id, CHARACTER, HEALING_SPEED, percent)
        self.combat.apply_settings()

    def healed_in(self, character, seconds: float) -> float:
        vitals = character.vitals
        vitals.health = vitals.max_health * .1
        before = vitals.health
        self.frames(round(seconds / FRAME))
        return vitals.health - before

    def test_every_character_heals_at_the_exact_configured_rate(self):
        self.teams.state.assignment.update({character_id: MY_TEAM for character_id in ROSTER_IDS})
        self.teams._apply_roster()
        for character_id in ROSTER_IDS:
            character = self.teams.characters[character_id]
            for percent in (1, DEFAULT_HEALING_SPEED, 100):
                self.set_speed(character, percent)
                expected = character.vitals.max_health * percent * .01 / FULL_HEAL_SECONDS * 1.0
                self.assertAlmostEqual(self.healed_in(character, 1.0), expected,
                                       delta=expected * .05, msg=f"{character_id} at {percent}%")

    def test_a_change_applies_at_once_and_only_to_that_character(self):
        white = self.teams.characters["WHITE"]
        green = self.teams.characters["GREEN"]
        untouched = green.vitals.regen
        slow = self.healed_in(white, .5)
        self.set_speed(white, 100)
        self.assertGreater(self.healed_in(white, .5), slow * 4.5)
        self.assertEqual(green.vitals.regen, untouched)

    def test_healing_continues_straight_after_being_hit(self):
        vitals = self.player.vitals
        vitals.resistance = 0.0
        vitals.health = 500.0
        self.combat.hit_character(None, self.player, 100.0, PHYSICAL)
        self.assertEqual(vitals.health, 400.0)
        self.frames(1)
        self.assertGreater(vitals.health, 400.0, "no pause after damage")

    def test_a_full_bar_at_100_percent_takes_ten_seconds_and_stops_at_the_maximum(self):
        vitals = self.player.vitals
        self.set_speed(self.player, 100)
        vitals.health = 1.0
        self.seconds(9.0)
        self.assertLess(vitals.health, vitals.max_health)
        self.seconds(1.2)
        self.assertEqual(vitals.health, vitals.max_health)
        self.seconds(1.0)
        self.assertEqual(vitals.health, vitals.max_health)

    def test_it_scales_with_the_health_setting_and_respects_a_lower_maximum(self):
        vitals = self.player.vitals
        self.combat.settings.set("WHITE", CHARACTER, "health", 100000)
        self.combat.apply_settings()
        self.assertAlmostEqual(self.healed_in(self.player, 1.0), 2000.0, delta=100.0)
        self.combat.settings.set("WHITE", CHARACTER, "health", 200)
        self.combat.apply_settings()
        self.seconds(50.0)
        self.assertEqual(vitals.max_health, 200)
        self.assertEqual(vitals.health, 200)

    def test_no_healing_while_downed_then_healing_resumes_after_recovery(self):
        vitals = self.player.vitals
        self.combat.hit_character(None, self.player, 1e9, PHYSICAL)
        self.assertTrue(vitals.downed)
        self.seconds(1.0)
        self.assertEqual(vitals.health, 0.0)
        vitals.downed_for = .01
        self.frames(2)
        revived = vitals.health
        self.assertGreater(revived, 0.0)
        self.frames(5)
        self.assertGreater(vitals.health, revived)

    def test_it_survives_switching_character(self):
        settings = self.combat.settings
        self.set_speed(self.teams.characters["GREEN"], 73)
        self.set_speed(self.teams.characters["WHITE"], 11)
        for character_id in ("GREEN", "WHITE", "RED", "WHITE"):
            self.teams.swap(character_id, save=False)
            self.frames(2)
        self.assertEqual(settings.get("GREEN", CHARACTER, HEALING_SPEED), 73)
        self.assertEqual(settings.get("WHITE", CHARACTER, HEALING_SPEED), 11)
        self.assertAlmostEqual(self.teams.characters["GREEN"].vitals.regen, .073)
        self.assertAlmostEqual(self.teams.characters["WHITE"].vitals.regen, .011)

    def test_void_still_strengthens_healing_and_the_cap_still_holds(self):
        self.teams.swap("YELLOW", save=False)
        sentry = self.teams.characters["YELLOW"]
        plain = self.healed_in(sentry, .5)
        sentry.vitals.regen_scale = 3.0
        self.assertAlmostEqual(self.healed_in(sentry, .5), plain * 3.0, delta=plain * .2)
        self.seconds(20.0)
        self.assertEqual(sentry.vitals.health, sentry.vitals.max_health)
        sentry.vitals.regen_scale = 1.0

    def test_a_time_stop_sequence_still_completes(self):
        self.place_enemy("BLACK", 60.0)
        self.tap("3")
        self.assertTrue(self.combat.time_stopped)
        self.seconds(12.0)
        self.assertFalse(self.combat.time_stopped)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)


class OverheadBarTests(unittest.TestCase):
    def test_every_bar_rises_every_frame_in_the_real_game_loop(self):
        game = reset_game()
        for character_id in ROSTER_IDS:
            game.teams.state.assignment[character_id] = MY_TEAM
        game.teams._apply_roster()
        for character_id, character in game.teams.characters.items():
            character.vitals.health = character.vitals.max_health * .5
        run_frames(game, 2)
        shown = {character_id: tag.fraction for character_id, tag in game.teams.tags.items()}
        for _ in range(5):
            run_frames(game, 1)
            for character_id, tag in game.teams.tags.items():
                self.assertGreater(tag.fraction, shown[character_id], character_id)
                self.assertAlmostEqual(tag.fill.scale_x, 1.9 * tag.fraction, delta=.001)
                shown[character_id] = tag.fraction


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.panel = self.game.power_panel
        self.game.input("p")

    def tearDown(self):
        if self.panel.enabled:
            self.game.input("p")
        run_frames(self.game, 1)

    def row(self):
        return self.panel.character_card.rows[HEALING_SPEED]

    def type_value(self, typed: str) -> None:
        self.panel.begin_edit(self.row())
        for key in typed:
            self.game.input(key)
        self.game.input("enter")

    def test_row_shows_the_default_on_every_tab(self):
        for character_id in ROSTER_IDS:
            self.panel.select_character(character_id)
            self.assertEqual(self.row().value.text, "20")
            self.assertEqual(self.row().unit.text, "%")
            self.assertEqual(self.row().label.text, "Healing Speed")
            self.assertTrue(self.row().track.enabled)

    def test_typed_value_reaches_the_character_and_disk(self):
        self.panel.select_character("RED")
        self.type_value("64")
        self.assertEqual(self.row().value.text, "64")
        self.panel.apply()
        red = self.game.teams.characters["RED"]
        self.assertAlmostEqual(red.vitals.regen, .064)
        path = self.game.combat.settings.path
        self.assertEqual(PowerSettings(path).get("RED", CHARACTER, HEALING_SPEED), 64)

    def test_typed_value_is_clamped_to_100(self):
        self.panel.select_character("WHITE")
        self.type_value("999")
        self.assertEqual(self.row().value.text, "100")
        self.panel.pending.clear()

    def test_slider_and_box_agree(self):
        self.panel.select_character("GREEN")
        row = self.row()
        self.panel.dragging = row
        self.panel.drag_to(row.track_left + .25 * .5)
        self.panel.dragging = None
        expected = row.param.value_at(.5)
        self.assertEqual(self.panel.current("GREEN", CHARACTER, HEALING_SPEED), expected)
        self.assertEqual(row.value.text, f"{expected:.0f}")
        self.panel.pending.clear()

    def test_max_all_raises_it_and_reset_character_restores_it(self):
        settings = self.game.combat.settings
        self.panel.select_character("WHITE")
        self.panel.max_character()
        self.assertEqual(settings.get("WHITE", CHARACTER, HEALING_SPEED), 100)
        self.assertAlmostEqual(self.game.teams.characters["WHITE"].vitals.regen, .1)
        self.panel.reset_character()
        self.panel.reset_character()
        self.assertEqual(settings.get("WHITE", CHARACTER, HEALING_SPEED), 20)
        self.assertAlmostEqual(self.game.teams.characters["WHITE"].vitals.regen, .02)


if __name__ == "__main__":
    unittest.main()
