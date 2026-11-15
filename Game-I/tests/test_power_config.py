"""The six-card schema, its saves, and the Character Power Configuration menu."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from characters.roster import KITS, ROSTER_IDS
from config.power_schema import (ABILITIES, CHARACTER, SQUAD_KEYS, KEYLESS, MAX_CARDS, MAX_HEALTH, MAX_RANGE,
                                 PARAM_KEYS, PASSIVES, SCHEMA, character_settings,
                                 SETTINGS_FILE_VERSION, SLOT_ABILITIES, UNIVERSAL, PowerSettings,
                                 params_of)
from game_fixture import FRAME, reset_game, run_frames

ROOT = Path(__file__).resolve().parent.parent
POWER_FILES = {path.stem: path.read_text(encoding="utf-8") for path in (ROOT / "powers").glob("*.py")}
POWER_SOURCE = "\n".join(POWER_FILES.values())
CARDS = {
    "WHITE": ("heat_vision", "high_speed_attack", "time_stop", "ground_execution",
              "melee"),
    "BLACK": ("laser_vision", "high_speed_attack", "time_stop", "neck_laser_execution", "melee"),
    "YELLOW": ("void_form", "high_speed_attack", "time_stop", "void_nuclear_execution", "melee"),
    "GREEN": ("squad_summon", "high_speed_attack", "time_stop", "speed_execution", "melee"),
    "RED": ("radiation_blast", "flying_punch", "aerial_grab_blast", "radioactive_execution"),
}


class SchemaTests(unittest.TestCase):
    def test_cards_are_exactly_the_abilities_a_key_reaches(self):
        self.assertEqual(set(SCHEMA), set(ROSTER_IDS))
        for character_id, names in CARDS.items():
            abilities = SCHEMA[character_id]
            self.assertLessEqual(len(abilities), MAX_CARDS, character_id)
            self.assertEqual(tuple(ability.ability_id for ability in abilities), names)
            for ability in abilities:
                self.assertTrue(ability.name)
                self.assertTrue(ability.description)
                self.assertTrue(ability.binding)

    def test_only_range_damage_and_speed_can_be_edited(self):
        for character_id, abilities in SCHEMA.items():
            for ability in abilities:
                keys = [param.key for param in ability.params]
                self.assertEqual(len(keys), len(set(keys)))
                self.assertLessEqual(set(keys) - set(SQUAD_KEYS), set(PARAM_KEYS), ability.ability_id)

    def test_defaults_are_full_range_and_speed_and_a_fifth_of_damage(self):
        for abilities in (*SCHEMA.values(), *KEYLESS.values()):
            for ability in abilities:
                for param in ability.params:
                    label = f"{ability.ability_id}.{param.key}"
                    if ability.ability_id == "radiation_blast" and param.key == "damage":
                        self.assertEqual(param.default, 1000.0, "exactly, as specified")
                    elif param.key == "damage":
                        self.assertAlmostEqual(param.default, param.maximum * .2, delta=.5, msg=label)
                    elif param.key in SQUAD_KEYS:
                        continue
                    else:
                        self.assertEqual(param.default, param.maximum, label)
                    self.assertLess(param.minimum, param.maximum)
                    self.assertTrue(param.unit)
                    self.assertEqual(param.clamp(param.maximum), param.maximum, "100% stays reachable")

    def test_health_and_healing_are_the_character_settings_and_nothing_removed_came_back(self):
        for character_id in SCHEMA:
            self.assertEqual([param.key for param in character_settings(character_id).params],
                             ["health", "healing_speed", "run_speed", *(() if character_id == "RED" else ("fly_speed", "boost_speed"))])
            self.assertEqual(character_settings(character_id).param("health").default,
                             PASSIVES[character_id].max_health)
        for abilities in SCHEMA.values():
            for ability in abilities:
                for param in ability.params:
                    self.assertNotIn(param.key, ("cooldown", "charge_time", "duration", "stamina",
                                                 "energy", "health"))

    def test_long_reach_abilities_go_to_100000_metres(self):
        for character_id, ability_id in (("WHITE", "heat_vision"), ("BLACK", "laser_vision"),
                                         ("YELLOW", "chest_beam"), ("YELLOW", "time_stop"),
                                         ("GREEN", "speed_execution"), ("GREEN", "high_speed_attack"),
                                         ("RED", "chest_beam"), ("RED", "radioactive_execution"),
                                         ("BLACK", "high_speed_attack")):
            self.assertEqual(params_of(character_id, ability_id)["range"].maximum, MAX_RANGE)

    def test_defensive_and_utility_cards_show_na(self):
        for character_id, ability_id, missing in (("YELLOW", "void_form", ("speed",)),
                                                  ("WHITE", "heat_vision", ("speed",))):
            for key in missing:
                self.assertIsNone(ABILITIES[character_id][ability_id].param(key))

    def test_no_removed_setting_or_lockout_exists_in_the_power_code(self):
        for banned in ("cooldown_left", "charge_time", ".spend(", ".drain(", "energy_regen",
                       ".meter", "unlock", "mass_limit", "lift_limit", "time_left"):
            self.assertNotIn(banned, POWER_SOURCE, banned)

    def test_nothing_can_grant_soldier_boy_flight(self):
        for ability in SCHEMA["RED"]:
            self.assertNotIn("flight", ability.ability_id)
            for param in ability.params:
                self.assertNotIn("fl", param.key)
        self.assertFalse(KITS["RED"].can_fly)

    def test_omni_man_has_no_ranged_energy(self):
        names = " ".join(ability.ability_id for ability in SCHEMA["GREEN"])
        for banned in ("vision", "laser", "projection", "beam"):
            self.assertNotIn(banned, names)

    def test_slider_scale_round_trips_and_stays_inside_limits(self):
        param = params_of("WHITE", "heat_vision")["range"]
        self.assertEqual(param.value_at(0.0), param.minimum)
        self.assertEqual(param.value_at(1.0), param.maximum)
        self.assertAlmostEqual(param.fraction(param.value_at(.5)), .5, places=2)
        self.assertLess(param.value_at(.5), 1000.0, "logarithmic: low values stay reachable")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "powers.json"

    def test_round_trip_is_independent_per_character_and_ability(self):
        store = PowerSettings(self.path)
        store.set("WHITE", "heat_vision", "damage", 300)
        store.set("WHITE", "ground_execution", "range", 900)
        self.assertTrue(store.save())
        loaded = PowerSettings(self.path)
        self.assertEqual(loaded.get("WHITE", "heat_vision", "damage"), 300)
        self.assertEqual(loaded.get("WHITE", "ground_execution", "range"), 900)
        self.assertEqual(loaded.get("BLACK", "laser_vision", "damage"),
                         params_of("BLACK", "laser_vision")["damage"].default)

    def test_values_are_validated(self):
        store = PowerSettings(self.path)
        table = params_of("WHITE", "heat_vision")
        self.assertEqual(store.set("WHITE", "heat_vision", "damage", 1e12), table["damage"].maximum)
        self.assertEqual(store.set("WHITE", "heat_vision", "damage", -5), table["damage"].minimum)
        self.assertEqual(store.set("WHITE", "heat_vision", "range", float("inf")), MAX_RANGE)
        self.assertEqual(store.set("WHITE", "heat_vision", "range", float("nan")), MAX_RANGE)
        with self.assertRaises(KeyError):
            store.set("WHITE", "heat_vision", "speed", 5)
        with self.assertRaises(KeyError):
            store.set("WHITE", "heat_vision", "cooldown", 5)

    def test_invalid_current_data_is_ignored_safely(self):
        self.path.write_text(json.dumps({
            "version": SETTINGS_FILE_VERSION,
            "values": {"PURPLE": {"heat_vision": {"damage": 9}},
                       "RED": {"flight": {"enabled": 1}, "chest_blast": {
                           "damage": "lots", "range": True, "cooldown": 5, "speed": 3}},
                       "WHITE": {"heat_vision": [1, 2], "ground_execution": {"range": 45}}}}),
            encoding="utf-8")
        store = PowerSettings(self.path)
        blast = params_of("RED", "chest_blast")
        self.assertEqual(store.get("RED", "chest_blast", "damage"), blast["damage"].default)
        self.assertEqual(store.get("RED", "chest_blast", "range"), blast["range"].default)
        self.assertEqual(store.get("WHITE", "ground_execution", "range"), 45)

    def test_old_saves_cannot_lower_the_new_defaults_and_are_kept_aside(self):
        old = {"version": 1, "values": {"WHITE": {"heat_vision": {"damage": 3, "range": 5,
                                                                  "cooldown": 99}}},
               "disabled": [["WHITE", "heat_vision"]]}
        self.path.write_text(json.dumps(old), encoding="utf-8")
        store = PowerSettings(self.path)
        self.assertEqual(store.get("WHITE", "heat_vision", "damage"),
                         params_of("WHITE", "heat_vision")["damage"].default)
        self.assertEqual(store.get("WHITE", "heat_vision", "range"), MAX_RANGE)
        kept = self.path.with_name(f"powers.before_v{SETTINGS_FILE_VERSION}.json")
        self.assertEqual(json.loads(kept.read_text(encoding="utf-8")), old)

    def test_a_saved_maximum_from_the_last_version_does_not_hide_the_new_damage_default(self):
        self.path.write_text(json.dumps({"version": 2, "values": {"WHITE": {"heat_vision": {
            "damage": 3000}}}}), encoding="utf-8")
        self.assertEqual(PowerSettings(self.path).get("WHITE", "heat_vision", "damage"), 600)

    def test_a_second_migration_never_deletes_the_first_copy(self):
        self.path.write_text(json.dumps({"version": 1, "values": {}, "tag": "first"}), encoding="utf-8")
        PowerSettings(self.path)
        self.path.write_text(json.dumps({"version": 2, "values": {}, "tag": "second"}), encoding="utf-8")
        PowerSettings(self.path)
        tags = {json.loads(item.read_text(encoding="utf-8"))["tag"] for item in self.path.parent.iterdir()}
        self.assertEqual(tags, {"first", "second"})

    def test_health_persists_independently_for_each_character(self):
        store = PowerSettings(self.path)
        store.set("WHITE", CHARACTER, "health", 5000)
        store.set("RED", CHARACTER, "health", 200)
        self.assertTrue(store.save())
        loaded = PowerSettings(self.path)
        self.assertEqual(loaded.get("WHITE", CHARACTER, "health"), 5000)
        self.assertEqual(loaded.get("RED", CHARACTER, "health"), 200)
        self.assertEqual(loaded.get("GREEN", CHARACTER, "health"), PASSIVES["GREEN"].max_health)
        loaded.set("WHITE", CHARACTER, "health", 1e12)
        self.assertEqual(loaded.get("WHITE", CHARACTER, "health"), MAX_HEALTH)
        self.assertEqual(loaded.set("WHITE", CHARACTER, "health", -5), 1)

    def test_corrupt_file_uses_defaults(self):
        self.path.write_text("{oops", encoding="utf-8")
        with self.assertLogs("config.power_schema", level="WARNING"):
            store = PowerSettings(self.path)
        self.assertEqual(store.get("WHITE", "heat_vision", "damage"),
                         params_of("WHITE", "heat_vision")["damage"].default)

    def test_saving_leaves_no_temporary_files_and_touches_nothing_else(self):
        other = self.path.parent / "island_destruction.json"
        other.write_text("keep", encoding="utf-8")
        PowerSettings(self.path).save()
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()),
                         ["island_destruction.json", "powers.json"])
        self.assertEqual(other.read_text(encoding="utf-8"), "keep")

    def test_resets_and_max(self):
        store = PowerSettings(self.path)
        store.set("WHITE", "heat_vision", "damage", 300)
        store.set("WHITE", "ground_execution", "range", 60)
        store.set("BLACK", "laser_vision", "damage", 300)
        store.reset_ability("WHITE", "heat_vision")
        self.assertEqual(store.get("WHITE", "ground_execution", "range"), 60)
        self.assertEqual(store.get("WHITE", "heat_vision", "damage"), 600)
        store.max_character("WHITE")
        self.assertEqual(store.get("WHITE", "ground_execution", "range"), MAX_RANGE)
        self.assertEqual(store.get("WHITE", "heat_vision", "damage"), 3000)
        self.assertEqual(store.get("WHITE", CHARACTER, "health"), MAX_HEALTH)
        self.assertEqual(store.get("BLACK", "laser_vision", "damage"), 300, "others untouched")
        store.max_all()
        self.assertEqual(store.get("BLACK", "laser_vision", "damage"), 3000)
        store.set("BLACK", "laser_vision", "damage", 300)
        store.reset_all()
        self.assertEqual(store.get("BLACK", "laser_vision", "damage"), 600)
        self.assertEqual(store.get("WHITE", CHARACTER, "health"), PASSIVES["WHITE"].max_health)


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.panel = self.game.power_panel
        self.game.input("p")

    def tearDown(self):
        if self.panel.visible:
            self.game.toggle_power_panel()

    def _row(self, ability_id: str, key: str):
        return self.panel.card_of(ability_id).rows[key]

    def test_the_old_config_menu_is_gone(self):
        self.assertFalse((ROOT / "ui" / "config_panel.py").exists())
        self.assertFalse(hasattr(self.game, "config_panel"))
        self.assertTrue(self.panel.visible)

    def test_opens_on_the_controlled_character(self):
        self.assertEqual(self.panel.character_id, self.game.sentry.kit.character_id)

    def test_five_tabs_and_each_shows_only_its_own_cards(self):
        self.assertEqual(set(self.panel.tabs), set(ROSTER_IDS))
        self.assertEqual(len(self.panel.cards), MAX_CARDS)
        for character_id in ROSTER_IDS:
            self.panel.select_character(character_id)
            shown = [card for card in self.panel.cards if card.ability is not None]
            self.assertEqual(tuple(card.ability.ability_id for card in shown), CARDS[character_id])
            for card in self.panel.cards[len(shown):]:
                self.assertFalse(card.background.enabled, "no blank cards")
                self.assertFalse(card.reset_button.enabled)
            for card in shown:
                self.assertTrue(card.name.text)
                self.assertIn("Key:", card.meta.text)
                self.assertTrue(card.description.text)
                self.assertIn(card.state.text, ("READY", "ACTIVE", "NULLIFIED"))

    def test_each_card_has_exactly_three_rows_with_slider_box_or_na(self):
        for character_id in ROSTER_IDS:
            self.panel.select_character(character_id)
            for card in self.panel.cards:
                if card.ability is None:
                    continue
                self.assertEqual(tuple(card.rows), PARAM_KEYS)
                for key, row in card.rows.items():
                    offered = card.ability.param(key) is not None
                    self.assertEqual(row.track.enabled, offered)
                    self.assertEqual(row.value.enabled, offered)
                    self.assertEqual(row.not_applicable.enabled, not offered)

    def test_status_shows_a_running_ability(self):
        self.game.input("p")
        self.game.input("1")
        self.game.input("1 up")
        self.game.input("p")
        self.assertEqual(self.panel.card_of("void_form").state.text, "ACTIVE")
        self.assertEqual(self.panel.card_of("void_nuclear_execution").state.text, "READY")
        self.game.sentry.powers.abilities["chest_beam"].cancel()

    def test_slider_and_value_box_stay_in_sync(self):
        self.panel.select_character("WHITE")
        row = self._row("heat_vision", "damage")
        self.panel.dragging = row
        self.panel.drag_to(row.track_left + row.fraction_at(row.track_left) + .25 * .5)
        expected = row.param.value_at(.5)
        self.assertEqual(self.panel.current("WHITE", "heat_vision", "damage"), expected)
        self.assertEqual(row.value.text, f"{expected:.0f}")
        knob_before = row.knob.x
        self.panel.dragging = None
        self.panel.begin_edit(row)
        for key in "20":
            self.game.input(key)
        self.game.input("enter")
        self.assertEqual(self.panel.current("WHITE", "heat_vision", "damage"), 20)
        self.assertEqual(row.value.text, "20")
        self.assertLess(row.knob.x, knob_before, "the slider follows the typed value")

    def test_typed_values_are_clamped_with_a_message(self):
        self.panel.select_character("WHITE")
        row = self._row("heat_vision", "range")
        self.panel.begin_edit(row)
        for key in "9999999":
            self.game.input(key)
        self.game.input("enter")
        self.assertEqual(self.panel.current("WHITE", "heat_vision", "range"), MAX_RANGE)
        self.assertIn("adjusted", self.panel.status.text)

    def test_pending_edits_survive_tab_changes_and_are_counted(self):
        self.panel.select_character("WHITE")
        self.panel.set_pending(self._row("heat_vision", "damage"), 500)
        self.assertIn("1 unsaved", self.panel.pending_text.text)
        self.panel.select_character("RED")
        self.panel.select_character("WHITE")
        self.assertEqual(self.panel.current("WHITE", "heat_vision", "damage"), 500)
        self.assertEqual(self.game.combat.settings.get("WHITE", "heat_vision", "damage"), 600,
                         "not live until applied")
        self.panel.pending.clear()

    def test_apply_saves_and_closing_applies_too(self):
        self.panel.select_character("WHITE")
        self.panel.set_pending(self._row("heat_vision", "damage"), 500)
        self.panel.apply()
        self.assertFalse(self.panel.has_pending)
        self.assertEqual(PowerSettings(self.game.combat.settings.path).get(
            "WHITE", "heat_vision", "damage"), 500)
        self.panel.set_pending(self._row("heat_vision", "damage"), 600)
        self.game.input("p")
        self.assertFalse(self.panel.visible)
        self.assertEqual(self.game.combat.settings.get("WHITE", "heat_vision", "damage"), 600)

    def test_reset_ability_is_immediate_and_others_need_confirming(self):
        settings = self.game.combat.settings
        settings.set("WHITE", "heat_vision", "damage", 500)
        settings.set("WHITE", "ground_execution", "range", 60)
        settings.set("BLACK", "laser_vision", "damage", 500)
        self.panel.select_character("WHITE")
        self.panel.card_of("heat_vision").reset()
        self.assertEqual(settings.get("WHITE", "heat_vision", "damage"), 600)
        self.panel.reset_character()
        self.assertEqual(settings.get("WHITE", "ground_execution", "range"), 60, "asked first")
        self.assertIn("again", self.panel.status.text)
        self.panel.reset_character()
        self.assertEqual(settings.get("WHITE", "ground_execution", "range"), MAX_RANGE)
        self.panel.reset_all()
        self.assertEqual(settings.get("BLACK", "laser_vision", "damage"), 500, "asked first")
        self.panel.reset_all()
        self.assertEqual(settings.get("BLACK", "laser_vision", "damage"), 600)

    def _health_row(self):
        return self.panel.character_card.rows["health"]

    def test_health_row_slider_and_box_agree_and_follow_the_tab(self):
        for character_id in ROSTER_IDS:
            self.panel.select_character(character_id)
            row = self._health_row()
            self.assertEqual(row.value.text, f"{PASSIVES[character_id].max_health:.0f}")
            self.assertEqual(row.unit.text, "hp")
        self.panel.select_character("WHITE")
        row = self._health_row()
        self.panel.dragging = row
        self.panel.drag_to(row.track_left + .25 * .5)
        self.panel.dragging = None
        expected = row.param.value_at(.5)
        self.assertEqual(self.panel.current("WHITE", CHARACTER, "health"), expected)
        self.assertEqual(row.value.text, f"{expected:.0f}")
        before = row.knob.x
        self.panel.begin_edit(row)
        for key in "50":
            self.game.input(key)
        self.game.input("enter")
        self.assertEqual(self.panel.current("WHITE", CHARACTER, "health"), 50)
        self.assertLess(row.knob.x, before)
        self.panel.pending.clear()

    def _set_health(self, character_id: str, typed: str) -> None:
        self.panel.select_character(character_id)
        self.panel.begin_edit(self._health_row())
        for key in typed:
            self.game.input(key)
        self.game.input("enter")
        self.panel.apply()

    def test_health_changes_real_gameplay_up_and_down_and_only_for_that_character(self):
        teams = self.game.teams
        white, green = teams.characters["WHITE"], teams.characters["GREEN"]
        untouched = green.vitals.max_health
        self._set_health("WHITE", "9000")
        self.assertEqual(white.vitals.max_health, 9000)
        self.assertEqual(white.vitals.health, 9000, "a full bar stays full")
        self.assertEqual(green.vitals.max_health, untouched)
        white.vitals.resistance = 0.0
        self.game.combat.hit_character(None, white, 4500.0)
        self.assertEqual(white.vitals.health, 4500.0, "survives what would have downed him")
        self._set_health("WHITE", "100")
        self.assertEqual(white.vitals.max_health, 100)
        self.assertLessEqual(white.vitals.health, 100)
        self.assertAlmostEqual(white.vitals.health, 50.0, msg="the same share of the new maximum")
        white.vitals.resistance = 0.0
        self.game.combat.hit_character(None, white, 80.0)
        self.assertTrue(white.vitals.downed, "a low maximum really is fragile")
        white.powers.hard_reset()

    def test_a_health_change_reaches_the_overhead_bar_while_still_in_the_menu(self):
        white = self.game.teams.characters["WHITE"]
        tag = self.game.teams.tags["WHITE"]
        white.vitals.health = white.vitals.max_health * .5
        tag.update(10.0, white.vitals)
        settings = self.game.combat.settings
        settings.set("WHITE", CHARACTER, "health", 4000)
        white.vitals.health = 500.0
        self.panel.select_character("WHITE")
        self.panel.apply()
        self.assertEqual(white.vitals.max_health, 4000)
        self.assertAlmostEqual(tag.fraction, white.vitals.fraction)
        self.assertFalse(self.game.team_panel.visible)
        white.powers.hard_reset()

    def test_health_is_saved_and_survives_a_restart_of_the_settings(self):
        self._set_health("RED", "321")
        self.assertEqual(PowerSettings(self.game.combat.settings.path).get("RED", CHARACTER, "health"), 321)

    def test_reset_character_restores_health_and_reset_ability_does_not(self):
        settings = self.game.combat.settings
        self._set_health("WHITE", "777")
        self.panel.card_of("heat_vision").reset()
        self.assertEqual(settings.get("WHITE", CHARACTER, "health"), 777)
        self.panel.reset_character()
        self.panel.reset_character()
        self.assertEqual(settings.get("WHITE", CHARACTER, "health"), PASSIVES["WHITE"].max_health)
        self.assertEqual(self.game.teams.characters["WHITE"].vitals.max_health, PASSIVES["WHITE"].max_health)

    def test_max_all_and_max_all_characters(self):
        settings = self.game.combat.settings
        settings.set("WHITE", "heat_vision", "damage", 5)
        settings.set("BLACK", "laser_vision", "damage", 5)
        self.panel.select_character("WHITE")
        self.panel.max_character()
        self.assertEqual(settings.get("WHITE", "heat_vision", "damage"), 3000)
        self.assertEqual(settings.get("BLACK", "laser_vision", "damage"), 5)
        self.panel.max_all()
        self.assertEqual(settings.get("BLACK", "laser_vision", "damage"), 3000)
        self.assertEqual(PowerSettings(settings.path).get("BLACK", "laser_vision", "damage"), 3000)

    def test_opening_blocks_gameplay_input(self):
        sentry = self.game.sentry
        before = self.game.elapsed
        run_frames(self.game, 3)
        self.assertEqual(self.game.elapsed, before)
        for key in ("1", "2", "3", "4", "r", "e", "q", "=", "-", "left mouse down"):
            self.game.input(key)
        self.assertEqual(sentry.powers.held, set())
        self.assertFalse(any(ability.active for ability in sentry.powers.abilities.values()))

    def test_a_sustained_power_carries_on_through_a_menu(self):
        self.game.input("p")
        sentry = self.game.sentry
        self.game.input("1")
        self.game.input("1 up")
        self.game.input("p")
        self.assertTrue(sentry.powers.abilities["void_form"].active)
        self.game.input("p")
        sentry.powers.abilities["chest_beam"].cancel()

    def test_keyless_abilities_use_their_defaults_and_stay_off_the_menu(self):
        settings = self.game.combat.settings
        for character_id, abilities in KEYLESS.items():
            shown = {card.ability_id for card in SCHEMA[character_id]}
            for ability in abilities:
                self.assertNotIn(ability.ability_id, shown)
                for param in ability.params:
                    self.assertEqual(settings.get(character_id, ability.ability_id, param.key),
                                     param.default)

    def test_a_panel_edit_in_the_game_changes_real_damage(self):
        """From the menu to the damage number, with the AI stopped and nothing else faked."""
        self.game.toggle_power_panel()
        from unittest import mock
        game = reset_game()
        teams = game.teams
        teams.swap("WHITE", save=False)
        body = game.sentry
        body.position = (0.0, game.world.height_at(0.0, 0.0) + .25, 0.0)
        enemy = teams.characters["BLACK"]
        teams.state.assignment["BLACK"] = "enemy_team"
        teams._apply_roster()
        enemy.vitals.max_health = 1e9
        enemy.vitals.health = 1e9
        enemy.vitals.regen = 0.0
        game.combat.settings.set("WHITE", "heat_vision", "damage", 100)
        with mock.patch.object(teams, "update"):
            enemy.position = (0.0, game.world.height_at(0.0, 15.0) + .25, 15.0)

            def fire():
                enemy.vitals.damage_taken = 0.0
                game.input("1")
                game.input("1 up")
                for _ in range(40):
                    game.update(FRAME)
                game.input("1")
                game.input("1 up")
                return enemy.vitals.damage_taken

            base = fire()
            game.input("p")
            panel = game.power_panel
            panel.select_character("WHITE")
            panel.begin_edit(panel.card_of("heat_vision").rows["damage"])
            for key in "360":
                game.input(key)
            game.input("enter")
            game.input("p")
            self.assertGreater(fire(), base * 3.0)
        enemy.powers.apply_passives()


class KitDisplayTests(unittest.TestCase):
    def test_every_roster_id_has_a_schema_and_universal_controls_are_not_cards(self):
        self.assertEqual(set(SCHEMA), set(KITS))
        self.assertEqual(set(UNIVERSAL), {"dash", "grab", "world_stop", "impact_dive"})
        for character_id in SCHEMA:
            self.assertNotIn("dash", ABILITIES[character_id])
        self.assertEqual(set(SLOT_ABILITIES), set(SCHEMA))


if __name__ == "__main__":
    unittest.main()
