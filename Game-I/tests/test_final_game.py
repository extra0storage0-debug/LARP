"""The five-character sandbox: roster, flight rules, teams, swapping and saves."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from characters.roster import KITS, ROSTER_IDS, can_fly
from characters.sentry_clone import CLONE_PALETTES
from config.character_roster import (AVAILABLE, ENEMY_TEAM, MY_TEAM, RosterError, RosterState)
from config.sentry_profiles import PLAYER
from game import controls
from game_fixture import FRAME, reset_game, run_frames
from movement.flight_physics import FlightPhase, Vec3 as SimVec3

ROOT = Path(__file__).resolve().parent.parent
FORWARD = (SimVec3(0.0, 0.0, 1.0), 0.0)


def _state(path=None) -> RosterState:
    return RosterState(path or Path(tempfile.mkdtemp()) / "roster.json")


class RosterRuleTests(unittest.TestCase):
    def test_exactly_the_five_named_characters(self):
        self.assertEqual(set(ROSTER_IDS), {"YELLOW", "WHITE", "GREEN", "BLACK", "RED"})
        self.assertEqual({kit.display for kit in KITS.values()},
                         {"SENTRY", "SUPERMAN", "OMNI-MAN", "HOMELANDER", "SOLDIER BOY"})

    def test_only_soldier_boy_cannot_fly(self):
        self.assertEqual([c for c in ROSTER_IDS if not can_fly(c)], ["RED"])

    def test_defaults(self):
        state = _state()
        self.assertEqual(state.player, "YELLOW")
        self.assertEqual(state.members(MY_TEAM), ["YELLOW"])
        self.assertEqual(sorted(state.members(ENEMY_TEAM)), ["BLACK", "GREEN", "RED", "WHITE"])
        self.assertEqual(state.members(AVAILABLE), [])

    def test_every_character_is_in_exactly_one_place(self):
        state = _state()
        state.move("WHITE", MY_TEAM)
        state.move("GREEN", AVAILABLE)
        groups = [state.members(team) for team in (MY_TEAM, ENEMY_TEAM, AVAILABLE)]
        flat = [member for group in groups for member in group]
        self.assertEqual(sorted(flat), sorted(ROSTER_IDS))

    def test_controlled_character_cannot_leave_my_team(self):
        state = _state()
        with self.assertRaises(RosterError):
            state.move("YELLOW", ENEMY_TEAM)
        self.assertEqual(state.team_of("YELLOW"), MY_TEAM)

    def test_cannot_control_someone_outside_my_team(self):
        state = _state()
        with self.assertRaises(RosterError):
            state.select_player("WHITE")
        self.assertEqual(state.player, "YELLOW")

    def test_soldier_boy_flight_settings_are_refused(self):
        state = _state()
        for action in (lambda: state.set_flight("RED", True),
                       lambda: state.cycle_flight_speed("RED"),
                       lambda: state.cycle_flight_boost("RED")):
            with self.assertRaises(RosterError):
                action()
        self.assertFalse(state.flight_allowed("RED"))

    def test_settings_are_independent_per_character(self):
        state = _state()
        state.cycle_flight_speed("WHITE")
        state.set_flight("BLACK", False)
        self.assertEqual(state.settings("GREEN")["flight_speed"], "NORMAL")
        self.assertTrue(state.settings("GREEN")["flight_enabled"])
        self.assertNotEqual(state.settings("WHITE")["flight_speed"], "NORMAL")
        state.reset_character("WHITE")
        self.assertEqual(state.settings("WHITE")["flight_speed"], "NORMAL")
        self.assertFalse(state.settings("BLACK")["flight_enabled"])


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "roster.json"

    def test_round_trip(self):
        state = _state(self.path)
        state.move("WHITE", MY_TEAM)
        state.move("GREEN", AVAILABLE)
        state.select_player("WHITE")
        state.cycle_flight_speed("BLACK")
        state.settings("RED")["helmet"] = True
        self.assertTrue(state.save())
        loaded = _state(self.path)
        self.assertEqual(loaded.player, "WHITE")
        self.assertEqual(loaded.team_of("GREEN"), AVAILABLE)
        self.assertEqual(loaded.settings("BLACK")["flight_speed"],
                         state.settings("BLACK")["flight_speed"])
        self.assertTrue(loaded.settings("RED")["helmet"])

    def test_legacy_data_cannot_add_characters_or_powers_or_soldier_boy_flight(self):
        self.path.write_text(json.dumps({
            "player": "PURPLE",
            "assignment": {"PURPLE": MY_TEAM, "BLUE": ENEMY_TEAM, "WHITE": "nowhere"},
            "characters": {"PURPLE": {"flight_enabled": True},
                           "RED": {"flight_enabled": True, "can_fly": True,
                                   "heat_vision_damage": 999},
                           "WHITE": {"flight_speed": "WARP", "time_stop": True}}}),
            encoding="utf-8")
        state = _state(self.path)
        self.assertEqual(set(state.assignment), set(ROSTER_IDS))
        self.assertEqual(state.player, "YELLOW")
        self.assertFalse(state.flight_allowed("RED"))
        self.assertEqual(state.settings("WHITE")["flight_speed"], "NORMAL")
        self.assertNotIn("time_stop", state.settings("WHITE"))
        self.assertNotIn("heat_vision_damage", state.settings("RED"))

    def test_invalid_player_falls_back_to_a_real_my_team_member(self):
        self.path.write_text(json.dumps({"player": "WHITE", "assignment": {
            "WHITE": ENEMY_TEAM, "YELLOW": MY_TEAM}}), encoding="utf-8")
        state = _state(self.path)
        self.assertEqual(state.player, "YELLOW")

    def test_empty_my_team_is_repaired(self):
        self.path.write_text(json.dumps({"player": "WHITE", "assignment": dict.fromkeys(
            ROSTER_IDS, ENEMY_TEAM)}), encoding="utf-8")
        state = _state(self.path)
        self.assertEqual(state.team_of(state.player), MY_TEAM)

    def test_corrupt_file_uses_defaults(self):
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertLogs("config.character_roster", level="WARNING"):
            state = _state(self.path)
        self.assertEqual(state.player, "YELLOW")

    def test_no_temporary_files_remain(self):
        _state(self.path).save()
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])


class FlightAndMovementTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.teams = self.game.teams

    def play(self, character_id):
        self.teams.state.assignment[character_id] = MY_TEAM
        self.teams._apply_roster()
        self.teams.swap(character_id, save=False)
        character = self.game.sentry
        character.flight.phase = FlightPhase.GROUNDED
        character.position = (0.0, self.game.world.height_at(0.0, 0.0) + .25, 0.0)
        return character

    def test_all_five_walk_run_and_jump(self):
        for character_id in ROSTER_IDS:
            character = self.play(character_id)
            start = (character.x, character.z)
            with mock.patch.object(self.game.input_manager, "movement", return_value=FORWARD):
                run_frames(self.game, 20)
            self.assertNotEqual((character.x, character.z), start, character_id)
            character.ground.velocity = SimVec3()
            floor = self.game.world.height_at(character.x, character.z) + .25
            self.game.input("space")
            run_frames(self.game, 15)
            self.assertGreater(character.y, floor + .5, character_id)
            self.assertFalse(character.flight.is_flying, "a jump is not flight")
            run_frames(self.game, 80)
            self.assertAlmostEqual(character.y, self.game.world.height_at(
                character.x, character.z) + .25, places=3, msg=character_id)

    def test_the_four_flyers_take_off_rise_steer_and_land(self):
        for character_id in ("YELLOW", "WHITE", "GREEN", "BLACK"):
            character = self.play(character_id)
            self.game.input("f")
            self.assertTrue(character.flight.is_flying, character_id)
            with mock.patch.object(self.game.input_manager, "movement",
                                   return_value=(SimVec3(), 1.0)):
                run_frames(self.game, 40)
            floor = self.game.world.height_at(character.x, character.z) + .25
            self.assertGreater(character.y, floor + 3.0, character_id)
            start = character.z
            with mock.patch.object(self.game.input_manager, "movement", return_value=FORWARD):
                run_frames(self.game, 30)
            self.assertNotEqual(character.z, start, character_id)
            self.game.input("f")
            self.assertEqual(character.movement_state, "DIVING", character_id)
            character.release_motion()

    def test_500_metre_ceiling_for_flyers(self):
        character = self.play("WHITE")
        self.game.input("f")
        character.y = 495.0
        with mock.patch.object(self.game.input_manager, "movement", return_value=(SimVec3(), 1.0)):
            run_frames(self.game, 90)
        self.assertLessEqual(character.y, 500.0)

    def test_soldier_boy_f_does_nothing(self):
        character = self.play("RED")
        self.game.input("f")
        run_frames(self.game, 3)
        self.assertIs(character.flight.phase, FlightPhase.GROUNDED)

    def test_soldier_boy_is_forced_down_whatever_sets_flight(self):
        character = self.play("RED")
        character.flight.toggle_flight()
        self.assertIs(character.flight.phase, FlightPhase.GROUNDED, "the controller refuses")
        character.flight.phase = FlightPhase.CRUISE  # legacy state or a stray code path
        character.flight.velocity = SimVec3(0.0, 40.0, 0.0)
        run_frames(self.game, 1)
        self.assertIs(character.flight.phase, FlightPhase.GROUNDED)
        self.assertEqual(character.flight.velocity.y, 0.0)

    def test_soldier_boy_space_only_jumps(self):
        character = self.play("RED")
        with mock.patch.object(self.game.input_manager, "movement", return_value=(SimVec3(), 1.0)):
            run_frames(self.game, 30)
        self.assertAlmostEqual(character.y, self.game.world.height_at(
            character.x, character.z) + .25, places=3)

    def test_soldier_boy_ai_stays_on_the_ground_chasing_a_flyer(self):
        game = self.game
        player = game.sentry
        game.input("f")
        player.y = game.world.height_at(player.x, player.z) + 100.0
        for _ in range(240):
            player.flight.velocity = SimVec3()
            game.update(FRAME)
            self.assertFalse(self.teams.characters["RED"].flight.is_flying)
        self.assertTrue(any(self.teams.characters[c].flight.is_flying
                            for c in ("WHITE", "GREEN", "BLACK")), "flyers follow")

    def test_flight_inheritance_is_impossible_on_swap(self):
        flyer = self.play("WHITE")
        self.game.input("f")
        self.assertTrue(flyer.flight.is_flying)
        character = self.play("RED")
        self.assertFalse(character.flight.is_flying)
        self.game.input("f")
        self.assertFalse(character.flight.is_flying)
        self.assertTrue(flyer.flight.is_flying, "Superman keeps his own state")

    def test_flight_disabled_setting(self):
        self.teams.state.set_flight("YELLOW", False)
        self.game.apply_sentry_config()
        self.game.input("f")
        self.assertFalse(self.game.sentry.flight.is_flying)

    def test_disabling_flight_in_the_air_brings_a_character_down(self):
        character = self.game.sentry
        self.game.input("f")
        character.flight.phase = FlightPhase.CRUISE
        character.y += 100.0
        self.teams.state.set_flight("YELLOW", False)
        run_frames(self.game, 1)
        self.assertIs(character.flight.phase, FlightPhase.LANDING)

    def test_speed_presets_change_only_that_character(self):
        white, black = self.teams.characters["WHITE"], self.teams.characters["BLACK"]
        white_speed, black_speed = white.flight.config.cruise_speed, black.flight.config.cruise_speed
        self.teams.state.settings("WHITE")["flight_speed"] = "FAST"
        self.game.apply_sentry_config()
        self.assertAlmostEqual(white.flight.config.cruise_speed, white_speed * 1.6)
        self.assertEqual(black.flight.config.cruise_speed, black_speed)

    def test_boost_preset(self):
        white = self.teams.characters["WHITE"]
        boost = white.flight.config.boost_speed
        self.teams.state.settings("WHITE")["flight_boost"] = "HIGH"
        self.game.apply_sentry_config()
        self.assertAlmostEqual(white.flight.config.boost_speed, boost * 1.4)


class TeamAndSwapTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.teams = self.game.teams

    def test_one_world_instance_each(self):
        self.assertEqual(set(self.teams.characters), set(ROSTER_IDS))
        self.assertEqual(len({id(c) for c in self.teams.characters.values()}), 5)
        self.assertEqual(len(CLONE_PALETTES), 4)
        self.assertNotIn("PURPLE", self.teams.characters)
        self.assertNotIn("BLUE", self.teams.characters)

    def test_moving_keeps_the_same_object_and_position(self):
        white = self.teams.characters["WHITE"]
        here = (white.x, white.z)
        self.teams.assign("WHITE", MY_TEAM)
        self.assertIs(self.teams.characters["WHITE"], white)
        self.assertEqual((white.x, white.z), here)
        self.assertIn(white, self.teams.allies)
        self.assertNotIn(white, self.teams.enemies)

    def test_available_leaves_the_world_and_returns(self):
        white = self.teams.characters["WHITE"]
        self.teams.assign("WHITE", AVAILABLE)
        self.assertTrue(white.parked)
        self.assertNotIn(white, self.teams.others)
        run_frames(self.game, 3)
        self.teams.assign("WHITE", ENEMY_TEAM)
        self.assertFalse(white.parked)
        self.assertIn(white, self.teams.others)

    def test_cannot_remove_the_controlled_character_without_a_replacement(self):
        with self.assertRaises(RosterError):
            self.teams.assign("YELLOW", ENEMY_TEAM)
        self.assertIs(self.game.sentry, self.teams.characters["YELLOW"])

    def test_swap_moves_input_and_camera_and_keeps_positions(self):
        white = self.teams.characters["WHITE"]
        yellow = self.game.sentry
        white_at, yellow_at = (white.x, white.z), (yellow.x, yellow.z)
        self.teams.assign("WHITE", MY_TEAM)
        self.teams.swap("WHITE")
        self.assertIs(self.game.sentry, white)
        self.assertTrue(white.controlled)
        self.assertFalse(yellow.controlled)
        self.assertIs(white.game, self.game)
        self.assertIsNot(yellow.game, self.game)
        self.assertIn(yellow, self.teams.allies)
        self.assertEqual((white.x, white.z), white_at)
        self.assertEqual((yellow.x, yellow.z), yellow_at)
        with mock.patch.object(self.game.input_manager, "movement", return_value=FORWARD):
            run_frames(self.game, 90)
        self.assertNotEqual((white.x, white.z), white_at, "input drives the new character")
        pivot = self.game.camera.pivot.position
        self.assertLess(abs(pivot.x - white.x) + abs(pivot.z - white.z), 5.0, "camera followed")

    def test_swap_through_every_character_and_back(self):
        for character_id in ROSTER_IDS:
            self.teams.assign(character_id, MY_TEAM)
        for character_id in (*ROSTER_IDS, "YELLOW"):
            self.teams.swap(character_id)
            self.assertEqual(self.game.sentry.kit.character_id, character_id)
            run_frames(self.game, 2)
            self.assertEqual(sum(c.controlled for c in self.teams.characters.values()), 1)
            self.assertNotIn(self.game.sentry, self.teams.others)

    def test_swapping_to_an_enemy_brings_them_onto_my_team(self):
        self.teams.swap("WHITE")
        self.assertEqual(self.game.sentry.kit.character_id, "WHITE")
        self.assertEqual(self.teams.state.team_of("WHITE"), MY_TEAM)

    def test_allies_follow_the_player(self):
        white = self.teams.characters["WHITE"]
        self.teams.assign("WHITE", MY_TEAM)
        before = ((white.x - self.game.sentry.x) ** 2 + (white.z - self.game.sentry.z) ** 2) ** .5
        run_frames(self.game, 180)
        after = ((white.x - self.game.sentry.x) ** 2 + (white.z - self.game.sentry.z) ** 2) ** .5
        self.assertLess(after, max(before, 30.0))

    def test_enemies_are_never_player_controlled(self):
        run_frames(self.game, 10)
        for enemy in self.teams.enemies:
            self.assertFalse(enemy.controlled)
            self.assertIsNot(enemy.game, self.game)

    def test_changes_save_and_load(self):
        self.teams.assign("WHITE", MY_TEAM)
        self.teams.swap("WHITE")
        loaded = RosterState(self.teams.state.path)
        self.assertEqual(loaded.player, "WHITE")
        self.assertEqual(loaded.team_of("WHITE"), MY_TEAM)


class ManagerPanelTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.panel = self.game.team_panel

    def test_m_opens_and_closes_and_blocks_gameplay(self):
        self.game.input("m")
        self.assertTrue(self.panel.visible)
        here = (self.game.sentry.x, self.game.sentry.z, self.game.elapsed)
        with mock.patch.object(self.game.input_manager, "movement", return_value=FORWARD):
            run_frames(self.game, 5)
        self.game.input("f")
        self.assertEqual((self.game.sentry.x, self.game.sentry.z, self.game.elapsed), here)
        self.assertFalse(self.game.sentry.flight.is_flying, "F there means the panel's flight")
        self.game.input("m")
        self.assertFalse(self.panel.visible)
        self.game.teams.state.reset_character("YELLOW")

    def test_soldier_boy_offers_no_flight_controls(self):
        self.panel.open()
        self.panel.select("RED")
        self.assertFalse(self.panel.flight_button.enabled)
        self.assertFalse(self.panel.speed_button.enabled)
        self.assertFalse(self.panel.boost_button.enabled)
        self.assertTrue(self.panel.ground_text.enabled)
        self.assertTrue(self.panel.helmet_button.enabled)
        self.panel.toggle_flight()
        self.panel.cycle_speed()
        self.assertFalse(self.game.teams.state.flight_allowed("RED"))
        self.panel.select("WHITE")
        self.assertTrue(self.panel.flight_button.enabled)
        self.assertFalse(self.panel.ground_text.enabled)
        self.assertFalse(self.panel.helmet_button.enabled)

    def test_clicking_moves_and_swaps(self):
        self.panel.open()
        self.panel.assign("WHITE", MY_TEAM)
        self.assertEqual(self.game.teams.state.team_of("WHITE"), MY_TEAM)
        self.panel.swap("WHITE")
        self.assertEqual(self.game.sentry.kit.character_id, "WHITE")

    def test_refused_moves_say_why(self):
        self.panel.open()
        self.panel.assign("YELLOW", ENEMY_TEAM)
        self.assertEqual(self.game.teams.state.team_of("YELLOW"), MY_TEAM)
        self.assertIn("You control", self.panel.status.text)

    def test_reset_all_needs_confirmation(self):
        self.panel.open()
        self.panel.assign("WHITE", MY_TEAM)
        self.panel.swap("WHITE")
        self.panel.reset_all()
        self.assertEqual(self.game.sentry.kit.character_id, "WHITE")
        self.assertIn("again", self.panel.status.text)
        self.panel.reset_all()
        self.assertEqual(self.game.sentry.kit.character_id, "YELLOW")
        self.assertEqual(self.game.teams.state.team_of("WHITE"), ENEMY_TEAM)

    def test_helmet_toggle_is_cosmetic(self):
        self.panel.open()
        self.panel.select("RED")
        red = self.game.teams.characters["RED"]
        self.panel.toggle_helmet()
        self.assertFalse(red.visual._helmet.isHidden())
        self.panel.toggle_helmet()
        self.assertTrue(red.visual._helmet.isHidden())
        self.assertFalse(red.flight_allowed)

    def test_tab_shows_status_while_held(self):
        self.game.input("tab")
        self.assertTrue(self.game.hud.team_status.enabled)
        self.assertIn("MY TEAM: SENTRY", self.game.hud.team_status.text)
        self.game.input("tab up")
        self.assertFalse(self.game.hud.team_status.enabled)


class AppearanceDataTests(unittest.TestCase):
    def test_required_identities(self):
        self.assertFalse(KITS["RED"].cape)
        self.assertTrue(KITS["BLACK"].flag_cape)
        self.assertTrue(KITS["RED"].helmet_parts)
        for character_id in ("WHITE", "GREEN", "BLACK", "YELLOW"):
            self.assertTrue(KITS[character_id].cape, character_id)

    def _beard(self, character_id):
        return [part for part in KITS[character_id].parts
                if part[0] == "body" and part[1] == "s" and part[2][1] < 2.56 and part[4] in
                {KITS[character_id].parts[0][4], *[p[4] for p in KITS[character_id].parts]}
                and abs(part[2][2]) >= 0.0 and part[3][0] <= .32 and part[3][1] <= .31
                and part[4] not in (self._skin(),)]

    @staticmethod
    def _skin():
        from characters.roster import SKIN
        return SKIN

    def test_only_omni_man_and_soldier_boy_have_full_beards(self):
        from characters.roster import BEARD_BLACK, BEARD_BROWN, BEARD_GREY, BEARD_LIGHT_BROWN
        colours = lambda kit: {part[4] for part in kit.parts}
        self.assertLessEqual({BEARD_BLACK, BEARD_GREY}, colours(KITS["GREEN"]))
        self.assertLessEqual({BEARD_BROWN, BEARD_LIGHT_BROWN}, colours(KITS["RED"]))
        for character_id in ("WHITE", "BLACK", "YELLOW"):
            self.assertFalse(colours(KITS[character_id])
                             & {BEARD_BLACK, BEARD_GREY, BEARD_BROWN, BEARD_LIGHT_BROWN})

    def test_full_beard_is_real_layered_geometry_covering_the_jaw(self):
        from characters.roster import BEARD_BROWN
        parts = [part for part in KITS["RED"].parts if part[4] == BEARD_BROWN]
        self.assertGreaterEqual(len(parts), 20)
        xs = [part[2][0] for part in parts]
        self.assertLess(min(xs), -.15, "left side")
        self.assertGreater(max(xs), .15, "right side")
        self.assertLess(min(part[2][1] for part in parts), 2.25, "under the chin")
        self.assertGreater(max(part[2][1] for part in parts), 2.5, "sideburn connection")


class ControlSchemeTests(unittest.TestCase):
    def test_keys(self):
        controls.apply_bindings({})
        self.assertEqual(controls.KEY_ACTIONS["m"], "team_manager")
        self.assertEqual(controls.KEY_ACTIONS["tab"], "team_status")
        self.assertEqual(controls.KEY_ACTIONS["f"], "flight_action")
        self.assertEqual(controls.KEY_ACTIONS["escape"], "pause")

    def test_mouse_wheel_zooms_within_limits_and_q_resets(self):
        game = reset_game()
        rig = game.camera
        game.input("scroll down")
        game.input("scroll down")
        self.assertGreater(rig.zoom, 0.0)
        far = rig.distance
        run_frames(game, 60)
        self.assertGreater(rig.distance, far)
        for _ in range(100):
            game.input("scroll up")
        self.assertEqual(rig.DEFAULT_DISTANCE + rig.zoom, 4.0)
        for _ in range(100):
            game.input("scroll down")
        self.assertEqual(rig.DEFAULT_DISTANCE + rig.zoom, 30.0)
        game.input("c")
        self.assertEqual(rig.zoom, 0.0)
        self.assertEqual(rig.distance, rig.DEFAULT_DISTANCE)

    def test_focus_loss_releases_held_keys(self):
        from ursina import held_keys
        game = reset_game()
        game._had_focus = True
        held_keys["w"] = 1
        fake = mock.Mock()
        fake.getProperties.return_value.getForeground.return_value = False
        with mock.patch("game.game_manager.application") as application:
            application.base.win = fake
            game._release_keys_on_focus_loss()
        self.assertEqual(held_keys["w"], 0)

    def test_remapping_cannot_give_soldier_boy_flight(self):
        game = reset_game()
        teams = game.teams
        teams.state.assignment["RED"] = MY_TEAM
        teams._apply_roster()
        teams.swap("RED", save=False)
        game.profiles.set(PLAYER, "key_flight_action", "g", notify=False)
        game.apply_sentry_config()
        game.input("g")
        game.input("f")
        run_frames(game, 2)
        self.assertFalse(game.sentry.flight.is_flying)
        reset_game()
        controls.apply_bindings({})


if __name__ == "__main__":
    unittest.main()
