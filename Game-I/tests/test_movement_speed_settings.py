"""Running and Flying Speed on the configuration menu: all five, live, saved, and Soldier Boy's rule."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ursina import held_keys

from characters.roster import ROSTER_IDS
from config.character_roster import ENEMY_TEAM, MY_TEAM
from config.power_schema import (ABILITIES, CHARACTER, CHARACTER_SETTINGS, FLY_SPEED, RUN_SPEED, SETTINGS_FILE_VERSION,
                                 PASSIVES, PowerSettings)
from game_fixture import FRAME, reset_game
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from test_gameplay_control_update import LiveCase

FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")


class SpeedCase(LiveCase):
    def setUp(self):
        self.game = reset_game()
        self.store = self.game.combat.settings
        self._forget()
        self.addCleanup(self._forget)

    def _forget(self):
        for character_id in ROSTER_IDS:
            self.store.reset_movement(character_id)
        self.game.combat.apply_settings()

    def choose(self, character_id: str, run=None, fly=None) -> None:
        if run is not None:
            self.store.set(character_id, CHARACTER, RUN_SPEED, run)
        if fly is not None:
            self.store.set(character_id, CHARACTER, FLY_SPEED, fly)
        self.game.combat.apply_settings()

    def body(self, character_id: str):
        return self.game.teams.characters[character_id]

    def run_speed(self, player: str, wanted: float, enemy: str = "BLACK") -> float:
        """Measured: metres covered per second, on the real key, in the real loop."""
        self.begin(player, enemy if player != enemy else "WHITE", 3000.0)  # this puts the settings back
        self.choose(player, run=wanted)
        self.stand(self.player, 0.0, -3000.0)
        self.frames(1)
        held_keys["w"] = held_keys["shift"] = 1
        self.seconds(3.5)  # everyone but Soldier Boy takes a moment to get there
        z = float(self.player.z)
        self.seconds(.5)
        held_keys["w"] = held_keys["shift"] = 0
        return (float(self.player.z) - z) / .5

    def fly_speed(self, player: str, wanted: float, boost: bool) -> float:
        self.begin(player, "RED", 3000.0)
        self.choose(player, fly=wanted)
        self.player.position = (0.0, 300.0, -4500.0)
        self.player.flight.phase = FlightPhase.CRUISE
        self.player.flight.velocity = SimVec3()
        self.game.camera.pitch = 0.0
        held_keys["w"] = 1
        held_keys["shift"] = 1 if boost else 0
        self.seconds(3.5)
        speed = self.player.flight.speed_mps
        held_keys["w"] = held_keys["shift"] = 0
        return speed


class SchemaTests(unittest.TestCase):
    def test_every_character_has_them_and_soldier_boy_has_no_flying_speed(self):
        for character_id in FLYERS:
            self.assertIsNotNone(CHARACTER_SETTINGS[character_id].param(RUN_SPEED))
            self.assertIsNotNone(CHARACTER_SETTINGS[character_id].param(FLY_SPEED))
        self.assertIsNotNone(CHARACTER_SETTINGS["RED"].param(RUN_SPEED))
        self.assertIsNone(CHARACTER_SETTINGS["RED"].param(FLY_SPEED))

    def test_a_save_with_flying_speed_for_soldier_boy_is_just_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "powers.json"
            path.write_text(json.dumps({"version": SETTINGS_FILE_VERSION, "values": {
                "RED": {CHARACTER: {FLY_SPEED: 900, RUN_SPEED: 700}}}}), encoding="utf-8")
            store = PowerSettings(path)
            self.assertIsNone(store.chosen("RED", CHARACTER, FLY_SPEED))
            self.assertEqual(store.chosen("RED", CHARACTER, RUN_SPEED), 700)

    def test_an_old_save_loads_and_chooses_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "powers.json"
            path.write_text(json.dumps({"version": SETTINGS_FILE_VERSION, "values": {
                "WHITE": {CHARACTER: {"health": 3000}, "heat_vision": {"damage": 77}}}}), encoding="utf-8")
            store = PowerSettings(path)
            self.assertEqual(store.get("WHITE", CHARACTER, "health"), 3000)
            self.assertEqual(store.get("WHITE", "heat_vision", "damage"), 77)
            for character_id in ROSTER_IDS:
                self.assertIsNone(store.chosen(character_id, CHARACTER, RUN_SPEED))
                self.assertIsNone(store.chosen(character_id, CHARACTER, FLY_SPEED))

    def test_they_save_and_load_for_each_character_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "powers.json"
            store = PowerSettings(path)
            for index, character_id in enumerate(ROSTER_IDS):
                store.set(character_id, CHARACTER, RUN_SPEED, 100 + index)
                if character_id != "RED":
                    store.set(character_id, CHARACTER, FLY_SPEED, 200 + index)
            self.assertTrue(store.save())
            loaded = PowerSettings(path)
            for index, character_id in enumerate(ROSTER_IDS):
                self.assertEqual(loaded.chosen(character_id, CHARACTER, RUN_SPEED), 100 + index)
                if character_id != "RED":
                    self.assertEqual(loaded.chosen(character_id, CHARACTER, FLY_SPEED), 200 + index)
            loaded.reset_movement("WHITE")
            self.assertIsNone(loaded.chosen("WHITE", CHARACTER, RUN_SPEED))
            self.assertEqual(loaded.chosen("BLACK", CHARACTER, RUN_SPEED), 100 + ROSTER_IDS.index("BLACK"))

    def test_max_all_leaves_speeds_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PowerSettings(Path(folder) / "powers.json")
            store.max_all()
            self.assertIsNone(store.chosen("WHITE", CHARACTER, RUN_SPEED))
            self.assertEqual(store.chosen("WHITE", CHARACTER, "health"), CHARACTER_SETTINGS["WHITE"].param("health").maximum)

    def test_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PowerSettings(Path(folder) / "powers.json")
            self.assertEqual(store.set("WHITE", CHARACTER, RUN_SPEED, -5), 1)
            self.assertEqual(store.set("WHITE", CHARACTER, RUN_SPEED, 1e12), 5000)


class EffectTests(SpeedCase):
    def test_unset_changes_nothing(self):
        for character_id in ROSTER_IDS:
            body = self.body(character_id)
            before = (body.ground.walk_speed, body.flight.config.cruise_speed, body.flight.config.boost_speed)
            self.game.combat.apply_settings()
            self.assertEqual((body.ground.walk_speed, body.flight.config.cruise_speed, body.flight.config.boost_speed),
                             before)

    def test_all_five_really_run_at_the_chosen_speed(self):
        for character_id, wanted in zip(ROSTER_IDS, (60.0, 90.0, 120.0, 45.0, 700.0)):
            with self.subTest(character_id):
                self.assertAlmostEqual(self.run_speed(character_id, wanted), wanted, delta=wanted * .06)

    def test_the_four_flyers_really_fly_at_it_and_boost_is_a_multiple(self):
        for character_id, wanted in zip(FLYERS, (80.0, 150.0, 240.0, 110.0)):
            with self.subTest(character_id):
                body = self.body(character_id)
                ratio = body.flight.config.boost_speed / body.flight.config.cruise_speed
                self.assertAlmostEqual(self.fly_speed(character_id, wanted, False), wanted, delta=wanted * .05)
                self.assertEqual(body.flight.config.cruise_speed, wanted)
                self.assertAlmostEqual(body.flight.config.boost_speed, wanted * ratio, places=3)
                self.assertAlmostEqual(self.fly_speed(character_id, wanted, True), wanted * ratio, delta=wanted * ratio * .05)

    def test_running_does_not_touch_flying_or_the_other_way_round(self):
        body = self.body("WHITE")
        fly = body.flight.config.cruise_speed
        self.choose("WHITE", run=333.0)
        self.assertEqual(body.flight.config.cruise_speed, fly)
        run = body.ground.max_running_speed
        self.choose("WHITE", fly=444.0)
        self.assertEqual(body.ground.max_running_speed, run)

    def test_one_character_leaves_the_others_alone(self):
        others = {cid: (self.body(cid).ground.max_running_speed, self.body(cid).flight.config.cruise_speed)
                  for cid in FLYERS if cid != "WHITE"}
        self.choose("WHITE", run=333.0, fly=444.0)
        for cid, values in others.items():
            self.assertEqual((self.body(cid).ground.max_running_speed, self.body(cid).flight.config.cruise_speed), values)

    def test_it_is_the_same_for_the_player_and_for_ai_and_changes_live(self):
        self.begin("YELLOW", "WHITE", 400.0)
        self.choose("WHITE", run=222.0, fly=333.0)
        ai = self.teams.characters["WHITE"]
        self.assertFalse(ai.controlled)
        self.assertEqual(ai.ground.max_running_speed, 222.0)
        self.assertEqual(ai.flight.config.cruise_speed, 333.0)
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams._apply_roster()
        self.teams.swap("WHITE", save=False)
        self.frames(1)
        self.assertTrue(ai.controlled)
        self.assertEqual(ai.ground.max_running_speed, 222.0)
        self.assertEqual(ai.flight.config.cruise_speed, 333.0)
        self.choose("WHITE", run=111.0)
        self.assertEqual(ai.ground.max_running_speed, 111.0)

    def test_ai_chasing_really_flies_faster_when_it_is_set_faster(self):
        def closing(fly: float) -> float:
            self.begin("RED", "WHITE", 3000.0, ai_powers=False)
            self.choose("WHITE", fly=fly)
            self.enemy.position = (0.0, 300.0, 3000.0)
            self.enemy.flight.phase = FlightPhase.CRUISE
            self.enemy.flight.velocity = SimVec3()
            top = 0.0
            for _ in range(round(4.0 / FRAME)):
                self.game.update(FRAME)
                top = max(top, self.enemy.flight.speed_mps)
            return top
        slow, fast = closing(60.0), closing(400.0)
        self.assertGreater(fast, slow * 1.5)

    def test_it_does_not_touch_any_combat_stat(self):
        def stats():
            return {cid: (self.body(cid).vitals.max_health, self.body(cid).vitals.resistance, self.body(cid).powers.strength,
                          self.body(cid).vitals.regen, self.body(cid).powers.collision_damage) for cid in ROSTER_IDS}
        before = stats()
        for cid in FLYERS:
            self.choose(cid, run=999.0, fly=999.0)
        self.assertEqual(stats(), before)
        self.assertEqual(PASSIVES["RED"].speed, 1.0)

    def test_the_squad_keeps_its_own_speeds(self):
        self.begin("GREEN", "WHITE", 300.0)
        self.tap_squad = self.teams.deploy_squad(self.player)
        member = self.tap_squad[0]
        member.apply_sentry_config()
        run = member.ground.max_running_speed
        self.choose("GREEN", run=999.0)
        member.apply_sentry_config()
        self.assertEqual(member.ground.max_running_speed, run)
        self.teams.withdraw_squad(list(self.tap_squad))


class BoostLimitTests(SpeedCase):
    def test_held_boost_stops_at_the_limit_however_long_it_is_held(self):
        for fly in (None, 60.0, 300.0):
            with self.subTest(fly):
                self.begin("WHITE", "RED", 3000.0)
                if fly is not None:
                    self.choose("WHITE", fly=fly)
                limit = self.player.flight.config.boost_speed
                self.player.position = (0.0, 300.0, -4500.0)
                self.player.flight.phase = FlightPhase.CRUISE
                self.player.flight.velocity = SimVec3()
                self.game.camera.pitch = 0.0
                held_keys["w"] = held_keys["shift"] = 1
                top = 0.0
                for _ in range(round(min(8.0, 7000.0 / limit) / FRAME)):
                    self.game.update(FRAME)
                    top = max(top, self.player.flight.speed_mps)
                held_keys["w"] = held_keys["shift"] = 0
                self.assertLessEqual(top, limit * 1.001)
                self.assertGreater(top, limit * .95, "and it does get there")

    def test_letting_go_of_boost_still_eases_down_rather_than_snapping(self):
        self.begin("WHITE", "RED", 3000.0)
        cruise = self.player.flight.config.cruise_speed
        self.player.position = (0.0, 300.0, -4500.0)
        self.player.flight.phase = FlightPhase.CRUISE
        self.player.flight.velocity = SimVec3()
        self.game.camera.pitch = 0.0
        held_keys["w"] = held_keys["shift"] = 1
        self.seconds(3.0)
        fast = self.player.flight.speed_mps
        held_keys["shift"] = 0
        self.frames(2)
        held = self.player.flight.speed_mps
        held_keys["w"] = 0
        self.assertGreater(held, fast * .95, "not in one frame")
        self.assertGreater(held, cruise)

    def test_soldier_boy_on_foot_beats_the_measured_top_of_the_fastest_flyer(self):
        self.begin("RED", "WHITE", 3000.0)
        self.frames(1)
        run = self.player.ground.max_running_speed
        self.begin("YELLOW", "RED", 3000.0)
        self.player.position = (0.0, 300.0, -4500.0)
        self.player.flight.phase = FlightPhase.CRUISE
        self.player.flight.velocity = SimVec3()
        self.game.camera.pitch = 0.0
        held_keys["w"] = held_keys["shift"] = 1
        top = 0.0
        for _ in range(round(8.0 / FRAME)):
            self.game.update(FRAME)
            top = max(top, self.player.flight.speed_mps)
        held_keys["w"] = held_keys["shift"] = 0
        self.assertGreater(run, top)


class SoldierBoyTests(SpeedCase):
    def fastest(self) -> float:
        return max(self.body(cid).flight.config.boost_speed for cid in FLYERS)

    def settle(self, run=None) -> float:
        self.begin("RED", "WHITE", 3000.0)
        if run is not None:
            self.choose("RED", run=run)
        self.frames(1)
        return self.player.ground.max_running_speed

    def test_a_chosen_speed_above_the_flyers_is_his_speed(self):
        self.assertEqual(self.settle(3000.0), 3000.0)

    def test_too_low_a_speed_cannot_break_the_rule(self):
        self.assertGreater(self.settle(5.0), self.fastest())

    def test_raising_a_flyer_raises_him_at_once(self):
        top = self.settle()
        self.choose("YELLOW", fly=2000.0)
        self.frames(1)
        self.assertGreater(self.player.ground.max_running_speed, self.fastest())
        self.assertGreater(self.player.ground.max_running_speed, top)
        self.assertGreaterEqual(self.fastest(), 2000.0)

    def test_it_is_true_for_ai_soldier_boy_as_well(self):
        self.begin("WHITE", "RED", 3000.0)
        self.choose("YELLOW", fly=1500.0)
        self.frames(1)
        self.assertGreater(self.enemy.ground.max_running_speed, self.fastest())

    def test_measured_on_foot_at_a_high_setting_and_he_never_flies(self):
        self.assertAlmostEqual(self.run_speed("RED", 700.0), 700.0, delta=30.0)
        self.assertFalse(self.player.flight.is_flying)
        self.assertFalse(self.player.flight_allowed)
        self.game.input("f")
        self.frames(2)
        self.game.input("f up")
        self.assertFalse(self.player.flight.is_flying)


class PanelTests(SpeedCase):
    def setUp(self):
        super().setUp()
        self.panel = self.game.power_panel
        self.game.input("p")
        self.addCleanup(self._close)

    def _close(self):
        if self.panel.enabled:
            self.game.input("p")

    def row(self, key):
        return self.panel.character_card.rows[key]

    def type_value(self, key: str, typed: str) -> None:
        self.panel.begin_edit(self.row(key))
        for character in typed:
            self.game.input(character)
        self.game.input("enter")

    def test_each_tab_has_the_rows_and_shows_the_speed_they_move_at_now(self):
        for character_id in ROSTER_IDS:
            with self.subTest(character_id):
                self.panel.select_character(character_id)
                body = self.body(character_id)
                self.assertEqual(self.row(RUN_SPEED).label.text, "Running Speed")
                self.assertEqual(self.row(RUN_SPEED).value.text.strip(), f"{body.default_run_speed:.0f}")
                self.assertEqual(self.row(RUN_SPEED).unit.text, "m/s")
                self.assertTrue(self.row(RUN_SPEED).track.enabled)
                if character_id == "RED":
                    self.assertTrue(self.row(FLY_SPEED).not_applicable.enabled, "disabled for him")
                    self.assertFalse(self.row(FLY_SPEED).track.enabled)
                    self.assertFalse(self.row(FLY_SPEED).value.enabled)
                else:
                    self.assertEqual(self.row(FLY_SPEED).value.text.strip(), f"{body.default_fly_speed:.0f}")
                    self.assertTrue(self.row(FLY_SPEED).track.enabled)

    def test_typing_then_apply_is_live_and_on_disk(self):
        self.panel.select_character("BLACK")
        self.type_value(RUN_SPEED, "321")
        self.type_value(FLY_SPEED, "654")
        self.assertEqual(self.row(RUN_SPEED).value.text.strip(), "321")
        self.assertEqual(self.body("BLACK").ground.max_running_speed != 321.0, True, "waits for Apply")
        self.panel.apply()
        self.assertEqual(self.body("BLACK").ground.max_running_speed, 321.0)
        self.assertEqual(self.body("BLACK").flight.config.cruise_speed, 654.0)
        saved = PowerSettings(self.store.path)
        self.assertEqual(saved.chosen("BLACK", CHARACTER, RUN_SPEED), 321)
        self.assertEqual(saved.chosen("BLACK", CHARACTER, FLY_SPEED), 654)

    def test_the_slider_writes_the_same_value_as_the_box(self):
        self.panel.select_character("WHITE")
        row = self.row(RUN_SPEED)
        self.panel.dragging = row  # the mouse itself needs a window; the window check covers that
        self.panel.drag_to(row.track_left + .125)
        self.panel.dragging = None
        value = self.panel.current("WHITE", CHARACTER, RUN_SPEED)
        self.assertEqual(row.value.text.strip(), f"{value:.0f}")
        self.assertAlmostEqual(row.knob.x, row.track_left + .125, delta=.002)
        self.panel.apply()
        self.assertEqual(self.body("WHITE").ground.max_running_speed, value)

    def test_reset_speeds_goes_back_to_what_it_was_for_this_character_only(self):
        for cid in ("WHITE", "BLACK"):
            self.panel.select_character(cid)
        white = self.body("WHITE")
        original = (white.ground.max_running_speed, white.flight.config.cruise_speed, white.flight.config.boost_speed,
                    white.ground.walk_speed)
        self.store.set("WHITE", CHARACTER, "health", 4321)
        self.store.set("WHITE", "heat_vision", "damage", 123)
        self.choose("WHITE", run=999.0, fly=888.0)
        self.choose("BLACK", run=777.0)
        self.panel.select_character("WHITE")
        self.panel.reset_movement()
        self.assertEqual((white.ground.max_running_speed, white.flight.config.cruise_speed,
                          white.flight.config.boost_speed, white.ground.walk_speed), original)
        self.assertEqual(self.store.get("WHITE", CHARACTER, "health"), 4321, "nothing else about them")
        self.assertEqual(self.store.get("WHITE", "heat_vision", "damage"), 123)
        self.assertEqual(self.body("BLACK").ground.max_running_speed, 777.0, "or anyone else")
        self.store.reset_character("WHITE")
        self.game.combat.apply_settings()

    def test_reset_drops_unapplied_edits_of_those_rows_only(self):
        self.panel.select_character("WHITE")
        self.type_value(RUN_SPEED, "500")
        self.type_value("health", "2222")
        self.panel.reset_movement()
        self.assertEqual(self.store.get("WHITE", CHARACTER, "health"), CHARACTER_SETTINGS["WHITE"].param("health").default)
        self.assertEqual(self.panel.pending["WHITE"][CHARACTER], {"health": 2222})
        self.panel.pending.clear()

    def test_a_soldier_boy_setting_cannot_break_the_rule_from_the_menu(self):
        self.game.input("p")
        self.begin("RED", "WHITE", 3000.0)
        self.game.input("p")
        self.panel.select_character("RED")
        self.type_value(RUN_SPEED, "3")
        self.panel.apply()
        self.game.input("p")
        self.frames(1)
        fastest = max(self.body(cid).flight.config.boost_speed for cid in FLYERS)
        self.assertGreater(self.player.ground.max_running_speed, fastest)

    def test_the_ability_cards_are_untouched(self):
        self.panel.select_character("WHITE")
        self.assertEqual([card.ability.ability_id for card in self.panel.cards if card.ability is not None],
                         list(ABILITIES["WHITE"]))


if __name__ == "__main__":
    unittest.main()
