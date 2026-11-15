"""Taking over bodies, graphics keys, saves and environmental destruction."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from characters.roster import ROSTER_IDS
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM, RosterState
from config.sentry_profiles import PLAYER, ProfileStore, SETTINGS
from game import controls
from game_fixture import FRAME, reset_game, run_frames
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import PowerCase, fresh_tree, object_of
from powers.vitals import HEAT, IMPACT, PHYSICAL

FORWARD = (SimVec3(0.0, 0.0, 1.0), 0.0)


class TakeOverTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.teams = self.game.teams

    def test_any_character_from_any_roster_at_any_time(self):
        self.teams.assign("GREEN", AVAILABLE)
        for character_id in ("WHITE", "GREEN", "RED", "BLACK", "YELLOW"):
            self.teams.swap(character_id)
            self.assertEqual(self.game.sentry.kit.character_id, character_id)
            self.assertEqual(self.teams.state.player, character_id)
            self.assertEqual(self.teams.state.team_of(character_id), MY_TEAM)
            self.assertFalse(self.game.sentry.parked)

    def test_every_order_of_switching_keeps_exactly_one_player_and_no_duplicates(self):
        order = ["WHITE", "RED", "YELLOW", "BLACK", "GREEN", "RED", "WHITE", "GREEN", "YELLOW"]
        characters = dict(self.teams.characters)
        for character_id in order:
            self.teams.swap(character_id)
            run_frames(self.game, 2)
            self.assertEqual(sum(c.controlled for c in self.teams.characters.values()), 1)
            self.assertNotIn(self.game.sentry, self.teams.others)
            self.assertEqual(self.teams.characters, characters, "the same five objects")
            flat = [member for team in (MY_TEAM, ENEMY_TEAM, AVAILABLE)
                    for member in self.teams.state.members(team)]
            self.assertEqual(sorted(flat), sorted(ROSTER_IDS))

    def test_rapid_switching_is_stable(self):
        for index in range(60):
            self.teams.swap(ROSTER_IDS[index % 5], save=False)
            self.game.update(FRAME)
        self.assertEqual(self.game.sentry.kit.character_id, ROSTER_IDS[59 % 5])

    def test_the_body_itself_changes_input_camera_and_hud(self):
        white = self.teams.characters["WHITE"]
        here = (white.x, white.z)
        self.teams.swap("WHITE")
        self.assertIs(white.game, self.game)
        with mock.patch.object(self.game.input_manager, "movement", return_value=FORWARD):
            run_frames(self.game, 60)
        self.assertNotEqual((white.x, white.z), here)
        self.assertLess(abs(self.game.camera.pivot.x - white.x) + abs(self.game.camera.pivot.z - white.z), 8.0)
        self.game.hud._text_timer = 0.0
        self.game.hud.update()
        self.assertIn("SUPERMAN", self.game.hud.status.text)
        self.assertEqual(self.game.hud.slots["1"].name.text, "Heat Vision")

    def test_the_previous_character_stays_in_the_world_as_an_ally_and_stops_taking_input(self):
        yellow = self.game.sentry
        at = (yellow.x, yellow.z)
        self.teams.swap("WHITE")
        self.assertEqual((yellow.x, yellow.z), at)
        self.assertFalse(yellow.controlled)
        self.assertFalse(yellow.parked)
        self.assertIn(yellow, self.teams.allies)
        self.assertIsNot(yellow.game, self.game)
        self.game.input("1")
        self.assertFalse(any(a.active for a in yellow.powers.abilities.values()))
        self.game.input("1 up")

    def test_each_body_gets_only_its_own_powers(self):
        expected = {"WHITE": "heat_vision", "BLACK": "laser_vision", "YELLOW": "void_unleashed",
                    "GREEN": "flight_charge", "RED": "radioactive_discharge"}
        for character_id, ability in expected.items():
            self.teams.swap(character_id)
            powers = self.game.sentry.powers
            self.assertIn(ability, powers.abilities)
            for other, name in expected.items():
                if other != character_id:
                    self.assertNotIn(name, powers.abilities)

    def test_taking_an_available_character_brings_them_into_the_world(self):
        white = self.teams.characters["WHITE"]
        self.teams.assign("WHITE", AVAILABLE)
        self.assertTrue(white.parked)
        self.teams.swap("WHITE")
        self.assertFalse(white.parked)
        self.assertTrue(white.enabled)

    def test_switching_mid_ability_clears_temporary_states_and_keeps_health(self):
        yellow = self.game.sentry
        abilities = yellow.powers.abilities
        for name in ("golden_shield", "void_tendrils", "void_unleashed", "chest_beam"):
            abilities[name].press()
        self.assertTrue(abilities["golden_shield"].active)
        self.assertTrue(abilities["void_unleashed"].active)
        yellow.vitals.health = 300.0
        self.teams.swap("WHITE")
        self.assertFalse(abilities["golden_shield"].active)
        self.assertFalse(abilities["void_tendrils"].active)
        self.assertFalse(abilities["chest_beam"].active)
        self.assertFalse(abilities["void_unleashed"].active)
        self.assertFalse(yellow.pose_root.hasColorScale())
        self.assertEqual(yellow.vitals.health, 300.0)
        self.assertEqual(yellow.powers.held, set())

    def test_switching_while_holding_keys_leaves_none_stuck(self):
        from ursina import held_keys
        held_keys["w"] = 1
        self.teams.swap("WHITE")
        self.assertEqual(held_keys["w"], 0)

    def test_soldier_boy_taken_mid_air_is_on_the_ground_and_a_flyer_keeps_flying(self):
        white = self.teams.characters["WHITE"]
        self.teams.swap("WHITE")
        self.game.input("f")
        white.y += 60.0
        self.assertTrue(white.flight.is_flying)
        red = self.teams.characters["RED"]
        red.flight.phase = FlightPhase.CRUISE  # a stray state, as if from an old save
        self.teams.swap("RED")
        run_frames(self.game, 1)
        self.assertIs(red.flight.phase, FlightPhase.GROUNDED)
        self.assertLess(red.y, self.game.world.height_at(red.x, red.z) + 1.0)
        self.assertTrue(white.flight.is_flying, "his own state, under AI")
        self.game.input("f")
        run_frames(self.game, 2)
        self.assertFalse(red.flight.is_flying)
        self.teams.swap("WHITE")
        self.assertTrue(white.flight_allowed)

    def test_soldier_boy_never_flies_by_any_route(self):
        red = self.teams.characters["RED"]
        self.teams.state.settings("RED")["flight_enabled"] = True
        self.teams.swap("RED")
        self.game.input("f")
        red.flight.toggle_flight()
        self.game.apply_sentry_config()
        run_frames(self.game, 2)
        self.assertFalse(red.flight.is_flying)
        self.assertFalse(red.flight_allowed)
        with self.assertRaises(ValueError):
            self.teams.state.set_flight("RED", True)
        self.teams.state.session = {"RED": {"position": [0.0, 300.0, 0.0], "flying": True}}
        self.teams.restore_session()
        self.assertFalse(red.flight.is_flying)
        self.assertLess(red.y, 200.0)

    def test_soldier_boy_walks_jumps_and_ai_stays_grounded(self):
        red = self.teams.characters["RED"]
        self.teams.swap("RED")
        at = red.z
        with mock.patch.object(self.game.input_manager, "movement", return_value=FORWARD):
            run_frames(self.game, 20)
        self.assertNotEqual(red.z, at)
        red.ground.velocity = SimVec3()
        self.game.input("space")
        run_frames(self.game, 10)
        self.assertGreater(red.jump_height, .3)
        run_frames(self.game, 70)
        self.teams.swap("YELLOW")
        self.teams.assign("RED", ENEMY_TEAM)
        self.game.input("f")
        self.game.sentry.y += 80.0
        for _ in range(120):
            self.game.sentry.flight.velocity = SimVec3()
            self.game.update(FRAME)
            self.assertFalse(red.flight.is_flying)

    def test_panel_play_button_and_enter_work_on_enemies(self):
        panel = self.game.team_panel
        self.game.input("m")
        panel.refresh()
        self.assertEqual(panel.rows["WHITE"][2].text, "PLAY")
        panel.swap("WHITE")
        self.assertEqual(self.game.sentry.kit.character_id, "WHITE")
        self.assertEqual(panel.rows["WHITE"][2].text, "YOU")
        panel.select("GREEN")
        self.game.input("enter")
        self.assertEqual(self.game.sentry.kit.character_id, "GREEN")
        self.game.input("m")
        self.assertFalse(panel.visible)


class GraphicsKeyTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.teams = self.game.teams

    def test_one_two_three_activate_abilities_and_never_change_quality(self):
        with mock.patch.object(self.game, "set_quality") as quality:
            for character_id in ROSTER_IDS:
                self.teams.swap(character_id)
                for key in ("1", "2", "3"):
                    self.game.input(key)
                    self.game.update(FRAME)
                    self.game.input(f"{key} up")
                self.game.sentry.powers.cancel_all()
                self.game.sentry.release_motion()
        quality.assert_not_called()

    def test_no_binding_or_help_text_mentions_quality_keys(self):
        for action in ("quality_low", "quality_medium", "quality_high"):
            self.assertNotIn(action, controls.CONTROL_BINDINGS)
        self.assertNotIn("1", controls.KEY_ACTIONS)
        self.assertNotIn("quality", self.game.hud.help.text.lower())

    def test_old_settings_cannot_bring_the_bindings_back(self):
        controls.apply_bindings({"quality_low": "1", "quality_medium": "2"})
        self.assertNotIn("1", controls.KEY_ACTIONS)
        controls.apply_bindings({})

    def test_old_saves_with_a_binding_on_an_ability_key_are_cleaned(self):
        path = Path(tempfile.mkdtemp()) / "profiles.json"
        path.write_text(json.dumps({"profiles": {PLAYER: {
            "key_camera_reset": "q", "key_team_manager": "1", "key_team_status": "tab"}}}),
            encoding="utf-8")
        from config.sentry_config import SentrySettings
        settings = SentrySettings()
        with self.assertLogs("config.sentry_profiles", level="WARNING"):
            store = ProfileStore(settings, path)
        self.assertEqual(store.get(PLAYER, "key_camera_reset"), "c")
        self.assertEqual(store.get(PLAYER, "key_team_manager"), "m")

    def test_ability_keys_cannot_be_rebound_onto_other_actions(self):
        for key in ("1", "2", "3", "4", "r", "e", "q"):
            self.assertEqual(controls.binding_conflict("team_manager", key), "reserved")

    def test_quality_changes_through_graphics_settings(self):
        menu = self.game.hud.pause_menu
        self.game.input("escape")
        self.assertTrue(self.game.paused)
        menu.show_graphics()
        with mock.patch.object(self.game, "set_quality") as quality:
            menu.quality_buttons["medium"].on_click()
        quality.assert_called_once_with("medium")
        self.game.input("escape")
        self.assertFalse(self.game.paused)

    def test_c_resets_the_camera_and_q_locks_a_target(self):
        rig = self.game.camera
        rig.zoom = 5.0
        self.game.input("c")
        self.assertEqual(rig.zoom, 0.0)
        rig.zoom = 5.0
        self.game.input("q")
        self.assertEqual(rig.zoom, 5.0, "Q no longer touches the camera")
        self.assertIsNone(self.game.sentry.motion, "Q no longer dashes")
        self.game.input("q")

    def test_settings_pages_stay_reachable_from_the_pause_menu(self):
        self.game.input("escape")
        self.game.hud.pause_menu._open_settings()
        self.assertTrue(self.game.settings_page.enabled)
        categories = {setting.category for setting in SETTINGS[PLAYER].values()}
        self.assertLessEqual({"camera", "visual", "input"}, categories)
        self.game.input("escape")
        self.assertFalse(self.game.settings_page.enabled)
        self.assertTrue(self.game.paused)
        self.game.input("escape")


class SaveLoadTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.teams = self.game.teams

    def test_the_active_character_and_teams_load_for_each_character(self):
        for character_id in ROSTER_IDS:
            self.teams.swap(character_id)
            loaded = RosterState(self.teams.state.path)
            self.assertEqual(loaded.player, character_id)
            self.assertEqual(loaded.team_of(character_id), MY_TEAM)

    def test_health_and_nullification_save_and_restore(self):
        black = self.teams.characters["BLACK"]
        black.vitals.health = 321.0
        black.vitals.add_status("nullified", 30.0)
        self.assertTrue(self.teams.save_session())
        saved = RosterState(self.teams.state.path).session["BLACK"]
        black.powers.hard_reset()
        black.powers.restore(saved)
        self.assertEqual(black.vitals.health, 321.0)
        self.assertTrue(black.vitals.nullified)

    def test_old_session_data_with_energy_cooldowns_and_forever_is_harmless(self):
        black = self.teams.characters["BLACK"]
        black.powers.restore({"vitals": {"health": 500.0, "energy": 3.0, "meter": 5.0,
                                         "nullified": 0.0, "nullified_forever": True},
                              "cooldowns": {"aerial_charge": 500.0}})
        self.assertEqual(black.vitals.health, 500.0)
        self.assertFalse(black.vitals.nullified)
        self.assertFalse(hasattr(black.powers.abilities["aerial_charge"], "cooldown_left"))
        black.powers.hard_reset()

    def test_broken_session_data_is_ignored(self):
        path = Path(tempfile.mkdtemp()) / "roster.json"
        path.write_text(json.dumps({"session": {"PURPLE": {"health": 1}, "WHITE": "nope", "RED": {
            "vitals": {"health": "lots", "energy": float("nan"), "meter": 9e9}, "cooldowns": {
                "chest_blast": "x", "nothing": 5, "shield_throw": 2}, "position": ["a", 1, 2]}}}),
            encoding="utf-8")
        state = RosterState(path)
        self.assertEqual(set(state.session), {"RED"})
        red = self.teams.characters["RED"]
        health = red.vitals.health
        red.powers.restore(state.session["RED"])
        self.assertEqual(red.vitals.health, health)
        red.powers.hard_reset()

    def test_saving_a_session_does_not_touch_world_damage(self):
        world = self.game.world
        path = world.damage_save_path
        world.save_damage_state()
        before = path.read_bytes() if path.exists() else None
        self.teams.save_session()
        self.assertEqual(path.read_bytes() if path.exists() else None, before)


class DestructionTests(PowerCase, unittest.TestCase):
    PLAYER = "YELLOW"

    def test_a_building_shows_progressive_damage_and_then_collapses_for_good(self):
        building = object_of(self.game, "Building")
        health = building.health.maximum_health
        building.take_damage(health * .55)
        self.assertGreaterEqual(building.damage_stage, 2)
        self.assertTrue(building.crack_overlay.visible)
        self.assertFalse(building.health.broken)
        building.take_damage(health)
        self.assertTrue(building.health.broken)
        self.assertIsNotNone(building.rubble_remains)
        self.assertTrue(self.game.world.object_states[building.persistent_id]["destroyed"])

    def test_blast_damages_buildings_trees_and_ground_together(self):
        building = object_of(self.game, "Building")
        origin = SimVec3(building.x, building.y, building.z)
        craters = len(self.game.world.terrain_impacts)
        self.combat.blast(self.player, origin, 30.0, 60.0, 10.0, crater=(6.0, 1.0, "test"))
        self.assertLess(building.health.health, building.health.maximum_health)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)

    def test_tree_damage_stages_fall_and_persistence(self):
        world = self.game.world
        tree = fresh_tree(self.game, minimum=1.0)
        tree_id = tree.tree_id
        world.damage_tree(tree, 40.0, SimVec3(1.0, 0.0, 0.0))
        self.assertLess(tree.tree_health, world.TREE_MAX_HEALTH)
        world.damage_tree(tree, 500.0, SimVec3(1.0, 0.0, 0.0))
        self.assertTrue(world.tree_states[tree_id]["destroyed"])
        self.assertTrue(any(type(effect).__name__ == "FallingTree" for effect in world.effects))

    def test_burning_tree_burns_down_and_can_be_put_out(self):
        elements = self.combat.elements
        tree = fresh_tree(self.game, minimum=1.0)
        elements.ignite_tree(tree)
        health = tree.tree_health
        elements.step(1.0)
        self.assertLess(tree.tree_health, health)
        elements.extinguish(SimVec3(tree.x, tree.y, tree.z), 3.0)
        self.assertNotIn(tree, elements.burning)
        health = tree.tree_health
        elements.step(1.0)
        self.assertEqual(tree.tree_health, health)

    def test_frozen_trees_shatter_more_easily_and_heat_melts_them(self):
        elements = self.combat.elements
        tree = fresh_tree(self.game, minimum=1.0)
        elements.freeze_tree(tree, 10.0)
        self.assertEqual(elements.damage_scale_for(tree, PHYSICAL), 2.0)
        self.assertEqual(elements.damage_scale_for(tree, HEAT), 1.0)
        self.assertFalse(elements.ignite_tree(tree))
        self.assertNotIn(tree, elements.frozen, "heat melted the ice first")

    def test_molecular_reconstruction_restores_a_tree(self):
        tree = fresh_tree(self.game, minimum=1.0)
        self.game.world.damage_tree(tree, 30.0, SimVec3(1.0, 0.0, 0.0))
        self.game.world.restore_tree(tree)
        self.assertEqual(tree.tree_health, self.game.world.TREE_MAX_HEALTH)

    def test_vehicles_explode_when_broken_and_hurt_those_nearby(self):
        vehicle = object_of(self.game, "Vehicle")
        self.stand(self.enemy, vehicle.x + 3.0, vehicle.z)
        self.enemy.vitals.regen = 0.0
        vehicle.take_damage(1000.0, impact_position=SimVec3(vehicle.x, vehicle.y, vehicle.z))
        self.frames(1)
        self.assertTrue(vehicle.health.broken)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "the chain blast reaches him")

    def test_a_thrown_object_damages_where_it_lands(self):
        boulder = object_of(self.game, "Boulder")
        self.stand(self.enemy, boulder.x, boulder.z + 8.0)
        self.enemy.vitals.regen = 0.0
        self.combat.track_thrown_object(self.player, boulder, 200.0)
        boulder.release(SimVec3(0.0, 2.0, 30.0))
        boulder.dynamic = True
        self.seconds(.6)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)

    def test_craters_change_collision_height_and_are_capped(self):
        world = self.game.world
        x, z = 1200.0, 1200.0
        before = world.height_at(x, z)
        world.terrain_impact(SimVec3(x, before, z), radius=8.0, depth=2.0, surface="test")
        self.assertLess(world.height_at(x, z), before)
        original = world.MAX_TERRAIN_IMPACTS
        world.MAX_TERRAIN_IMPACTS = len(world.terrain_impacts)
        try:
            count = len(world.terrain_impacts)
            for index in range(5):
                world.terrain_impact(SimVec3(1500.0 + index * 40.0, 0.0, 1500.0), radius=3.0,
                                     depth=.2, surface="test")
            self.assertEqual(len(world.terrain_impacts), count)
        finally:
            world.MAX_TERRAIN_IMPACTS = original

    def test_pools_keep_effects_bounded_under_repeated_use(self):
        from ursina import scene
        elements = self.combat.elements
        before = len(scene.entities)
        for index in range(60):
            point = SimVec3(index * 8.0, 0.0, 300.0)
            elements.start_fire(point, self.player)
            elements.add_ice(point, on_water=False, source=self.player)
            elements.add_scorch(point)
            self.combat.puffs.emit(point, SimVec3(), (255, 255, 255, 100))
            self.combat.cracks.place(self.game.world, point, 5.0)
            self.combat.markers.show([point], (255, 255, 255, 255), lambda _p: 1.0)
        self.assertEqual(len(scene.entities), before)
        self.assertLessEqual(len(elements.fires), 8)
        self.assertLessEqual(len(elements.ice), 10)
        self.assertLessEqual(len(elements.scorches), 16)
        self.frames(1)

    def test_debris_budget_holds_under_heavy_destruction(self):
        world = self.game.world
        for index in range(30):
            self.combat.blast(self.player, SimVec3(800.0 + index, 30.0, 800.0), 20.0, 300.0, 30.0,
                              crater=(4.0, .8, "test"), play_sound=False)
        self.assertLessEqual(len(world.debris), world.debris_budget.maximum_live_pieces)

    def test_impact_kinds_respect_resistance(self):
        vitals = self.player.vitals
        vitals.resistance = 0.0
        vitals.impact_resistance = 50.0
        self.assertEqual(vitals.take(100.0, IMPACT), 50.0)
        self.assertEqual(vitals.take(100.0, PHYSICAL), 100.0)


class CombatAITests(unittest.TestCase):
    def test_a_grounded_character_can_only_be_launched_so_far(self):
        game = reset_game()
        body = game.sentry
        for _ in range(40):
            body.apply_knockback(SimVec3(0.0, 500.0, 0.0))
        peak = body.y
        for _ in range(240):
            game.update(FRAME)
            peak = max(peak, body.y)
        self.assertLess(peak - game.world.height_at(body.x, body.z), 80.0)
        self.assertFalse(body.flight.is_flying)

    def test_ai_uses_its_real_powers_and_hurts_the_player(self):
        game = reset_game(ai_powers=True)
        body = game.sentry
        game.teams.state.assignment["BLACK"] = "enemy_team"
        game.teams._apply_roster()
        body.vitals.regen = 0.0
        game.elapsed = 100.0  # past the grace period at the start of a session
        for _ in range(60 * 14):
            game.update(FRAME)
            if body.vitals.damage_taken > 0.0:
                break
        self.assertGreater(body.vitals.damage_taken, 0.0)

    def test_ai_can_be_told_not_to_use_powers(self):
        game = reset_game(ai_powers=False)
        body = game.sentry
        for _ in range(240):
            game.update(FRAME)
        self.assertEqual(body.vitals.damage_taken, 0.0)

    def test_soldier_boy_ai_blasts_without_ever_leaving_the_ground(self):
        game = reset_game(ai_powers=True)
        red = game.teams.characters["RED"]
        for _ in range(60 * 8):
            game.update(FRAME)
            self.assertFalse(red.flight.is_flying)

    def test_attack_tokens_limit_simultaneous_attackers(self):
        from ai.combat_ai import AttackTokens
        tokens = AttackTokens(2)
        self.assertTrue(tokens.take("a"))
        self.assertTrue(tokens.take("b"))
        self.assertFalse(tokens.take("c"))
        tokens.give_back("a")
        self.assertTrue(tokens.take("c"))

    def test_move_choice_respects_range_and_readiness(self):
        from random import Random
        from ai.combat_ai import choose_move
        rng = Random(1)
        move = choose_move("RED", 7.0, lambda name: name == "flying_punch", rng)
        self.assertEqual(move.ability_id, "flying_punch")
        self.assertIsNone(choose_move("RED", 900.0, lambda _name: True, rng))
        for _ in range(30):
            chosen = choose_move("GREEN", 200.0, lambda _name: True, rng)
            self.assertIn(chosen.ability_id, ("squad_summon", "high_speed_attack", "time_stop", "speed_execution"))


if __name__ == "__main__":
    unittest.main()
