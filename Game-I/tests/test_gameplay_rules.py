"""The fixed rules: no waiting, no resources, automatic targets, and health bars on everyone."""

from __future__ import annotations

import unittest

from characters.roster import ROSTER_IDS
from config.power_schema import MAX_RANGE, SCHEMA
from game_fixture import FRAME, reset_game, run_frames
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import PowerCase, fresh_tree
from powers.base import Ability
from powers.vitals import PHYSICAL, Vitals

HEAD_TOP_METRES = 3.3  # the tallest hair measured on any of the five models is 3.11 m
# Key that starts and stops each sustained ability a player can reach.
SUSTAINED = {"WHITE": {"heat_vision": "1"},
             "BLACK": {"laser_vision": "1"},
             "YELLOW": {"void_form": "1"},
             "RED": {"radiation_blast": "1"}}


class NoWaitingTests(PowerCase, unittest.TestCase):
    def test_no_ability_has_a_cooldown_or_any_resource_at_all(self):
        for character_id in ROSTER_IDS:
            character = self.teams.characters[character_id]
            for ability in character.powers.abilities.values():
                self.assertFalse(hasattr(ability, "cooldown_left"), ability.ability_id)
                self.assertFalse(hasattr(ability, "spend"), ability.ability_id)
        vitals = Vitals()
        for name in ("energy", "meter", "stamina", "spend", "drain"):
            self.assertFalse(hasattr(vitals, name), name)
        self.assertFalse(hasattr(Ability, "tick_cooldown"))

    def test_sustained_abilities_start_at_once_last_and_stop_on_the_same_key(self):
        for character_id, table in SUSTAINED.items():
            self.play(character_id)
            self.place_enemy("GREEN", 25.0)
            self.enemy.vitals.max_health = self.enemy.vitals.health = 1e9  # the chest beams stop at nobody left
            for ability_id, key in table.items():
                ability = self.ability(ability_id)
                self.tap(key)
                self.assertTrue(ability.active, ability_id)
                self.seconds(45.0)
                self.assertTrue(ability.active, f"{ability_id} ran out")
                self.tap(key)
                self.assertFalse(ability.active, ability_id)
                self.enemy.vitals.downed_for = 0.0
                self.enemy.vitals.health = self.enemy.vitals.max_health
                self.tap(key)
                self.assertTrue(ability.active, f"{ability_id} can start again at once")
                self.tap(key)

    def test_one_shots_can_be_used_on_consecutive_frames(self):
        self.play("YELLOW")
        self.place_enemy("BLACK", 3000.0)
        blast = self.ability("massive_blast")
        before = blast.blasts
        for _ in range(5):
            blast.press()  # it has no key of its own now
            self.frames(1)
        self.assertEqual(blast.blasts, before + 5)

    def test_a_one_shot_resolves_once_per_activation(self):
        self.play("GREEN")
        self.place_enemy("BLACK", 5.0)
        self.set("shockwave_punch", "damage", 10)
        self.set("shockwave_punch", "range", 1)
        self.enemy.vitals.max_health = 100000.0
        self.enemy.vitals.health = 100000.0
        self.ability("shockwave_punch").press()  # no key of its own any more
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "out of Range")
        self.set("shockwave_punch", "range", 100)
        self.ability("shockwave_punch").press()
        once = self.enemy.vitals.damage_taken
        self.assertGreater(once, 0.0)
        self.seconds(1.0)
        self.assertEqual(self.enemy.vitals.damage_taken, once, "no repeat damage after the press")
        self.enemy.powers.apply_passives()

    def _use_everything(self) -> None:
        for character_id in ROSTER_IDS:
            self.play(character_id)
            self.place_enemy("WHITE" if character_id != "WHITE" else "BLACK", 25.0)
            for key in ("1", "2", "3", "4", "r", "=", "-", "q"):
                self.tap(key)
                self.seconds(.2)
                self.tap(key)
                self.player.release_motion()
            self.player.powers.cancel_all()
            self.player.release_motion()
            self.seconds(1.0)

    def _live_entities(self) -> int:
        """What Ursina still keeps, once it has swept what was destroyed, as it does every frame."""
        from ursina import scene
        return sum(1 for entity in scene.entities if not entity.is_empty()
                   and entity not in scene._entities_marked_for_removal)

    def test_repeated_use_of_every_ability_leaves_entities_bounded(self):
        world = self.game.world
        self._use_everything()
        settled = self._live_entities()
        self._use_everything()
        self._use_everything()
        self.assertLess(self._live_entities() - settled, world.debris_budget.maximum_live_pieces + 60)
        self.assertEqual(self.combat.projectiles, [])
        self.assertLessEqual(len(world.debris), world.debris_budget.maximum_live_pieces)

    def test_a_felled_tree_leaves_nothing_behind(self):
        from ursina import scene
        world = self.game.world
        tree = fresh_tree(self.game, minimum=1.0)
        before = self._live_entities()
        world.damage_tree(tree, 100000.0, SimVec3(1.0, 0.0, 0.0))
        self.seconds(12.0)
        self.assertFalse(any(type(effect).__name__ == "FallingTree" for effect in world.effects))
        names = [entity.getName() for entity in scene.entities if not entity.is_empty()]
        self.assertEqual([name for name in names if name.startswith("falling-tree")], [])
        self.assertLessEqual(self._live_entities(), before + world.debris_budget.maximum_live_pieces)

    def test_every_value_on_every_card_is_really_read_when_the_ability_is_used(self):
        """No fake sliders: record what the running game asks for while each ability is used."""
        from unittest import mock
        settings = self.combat.settings
        real_get = settings.get
        read = set()

        def recording_get(character_id, ability_id, key):
            read.add((character_id, ability_id, key))
            return real_get(character_id, ability_id, key)

        expected = {(character_id, card.ability_id, param.key)
                    for character_id in ROSTER_IDS for card in SCHEMA[character_id]
                    for param in card.params}
        with mock.patch.object(settings, "get", recording_get):
            for character_id in ROSTER_IDS:
                self.play(character_id)
                enemy_id = "BLACK" if character_id != "BLACK" else "WHITE"
                for key in ("1", "2", "3", "4", "r", "=", "-"):
                    self.place_enemy(enemy_id, 60.0)
                    self.enemy.vitals.max_health = 1e9
                    self.enemy.vitals.health = 1e9
                    self.stand(self.player, 0.0, 0.0)
                    self.player.release_motion()
                    self.game.input(key)
                    self.seconds(.6)
                    self.game.input(key.replace(" down", " up") if " down" in key else f"{key} up")
                    self.seconds(.6)
                    self.player.powers.cancel_all()
                self.enemy.powers.apply_passives()
            # The execution reads Damage at its impact, later than the frames watched above.
            self.play("WHITE")
            self.place_enemy("BLACK", 60.0)
            self.enemy.vitals.max_health = 1e9
            self.enemy.vitals.health = 1e9
            self.tap("4")
            self.seconds(4.0)
            self.enemy.powers.apply_passives()
            # Overdrive's values are only read while a beam is hitting something.
            self.play("BLACK")
            self.place_enemy("WHITE", 20.0)
            self.enemy.vitals.max_health = 1e9
            self.enemy.vitals.health = 1e9
            self.ability("laser_overdrive").press()
            self.tap("1")
            self.seconds(.5)
            self.player.powers.cancel_all()
            self.enemy.powers.apply_passives()
            # Range is read once the squad is out and choosing where to go.
            self.play("GREEN")
            self.place_enemy("WHITE", 60.0)
            self.tap("1")
            member = self.game.teams.summons[0]
            member.refresh_view()
            self.game.teams._squad_intent(member, member.view, self.game.teams._target_view())
            self.tap("1")
            # Soldier Boy's two read Damage on landing the blow, later than the frames watched above.
            self.play("RED")
            for key, wait in (("2", 12.0), ("3", 12.0), ("4", 30.0)):
                self.player.release_motion()
                self.stand(self.player, 0.0, 0.0)
                self.place_enemy("BLACK", 60.0)
                self.enemy.vitals.max_health = 1e9
                self.enemy.vitals.health = 1e9
                self.tap(key)
                self.seconds(wait)
            self.enemy.powers.apply_passives()
            # The Void's damage only starts ten seconds into its cycle.
            self.play("YELLOW")
            self.place_enemy("WHITE", 60.0)
            self.enemy.vitals.max_health = 1e9
            self.enemy.vitals.health = 1e9
            self.tap("1")
            self.seconds(.2)
            self.ability("void_form").cycle = 20.0
            self.seconds(.6)
            self.tap("1")
            self.enemy.powers.apply_passives()
        self.assertEqual(sorted(expected - read), [])


class DefaultsTests(PowerCase, unittest.TestCase):
    def test_every_ability_reads_its_default(self):
        for character_id in ROSTER_IDS:
            character = self.teams.characters[character_id]
            for card in SCHEMA[character_id]:
                ability = character.powers.abilities[card.ability_id]
                for param in card.params:
                    self.assertEqual(ability.p(param.key), param.default)

    def test_max_output_with_100km_range_is_stable_from_end_to_end(self):
        self.play("WHITE")
        self.place_enemy("BLACK", 3000.0)
        self.assertEqual(self.ability("heat_vision").p("range"), MAX_RANGE)
        self.tap("1")
        self.seconds(.5)
        self.tap("1")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "hit at 3 km")
        for value in (self.player.x, self.player.y, self.player.z):
            self.assertEqual(value, value)

    def test_blast_radius_is_bounded_whatever_the_range(self):
        self.play("RED")
        ability = self.ability("radioactive_discharge")
        self.assertLessEqual(ability.area(.15, 150.0), 150.0)
        self.assertEqual(ability.p("range"), MAX_RANGE)


class AutomaticTargetingTests(PowerCase, unittest.TestCase):
    def _enemies(self, *placed):
        """Put several enemies at (id, x, z)."""
        for character_id, x, z in placed:
            self.teams.state.assignment[character_id] = "enemy_team"
            self.stand(self.teams.characters[character_id], x, z)
            vitals = self.teams.characters[character_id].vitals
            vitals.damage_taken = 0.0
            vitals.downed_for = 0.0
            vitals.health = vitals.max_health
        self.teams._apply_roster()
        self.combat.targets.clear()
        self.game.elapsed += 1.0

    def lock(self):
        return self.combat.targets.lock_of(self.player)

    def test_nearest_enemy_is_chosen(self):
        self._enemies(("BLACK", 0.0, 90.0), ("WHITE", 0.0, 40.0), ("GREEN", 30.0, 300.0))
        self.assertIs(self.lock(), self.teams.characters["WHITE"])

    def test_an_enemy_behind_is_still_chosen_when_nobody_is_ahead(self):
        self._enemies(("BLACK", 0.0, -60.0))
        self.assertIs(self.lock(), self.teams.characters["BLACK"])

    def test_forward_enemy_wins_when_similarly_close(self):
        self._enemies(("BLACK", 0.0, -50.0), ("WHITE", 0.0, 54.0))
        self.assertIs(self.lock(), self.teams.characters["WHITE"])

    def test_far_forward_enemy_does_not_beat_a_much_closer_one(self):
        self._enemies(("BLACK", 0.0, -20.0), ("WHITE", 0.0, 200.0))
        self.assertIs(self.lock(), self.teams.characters["BLACK"])

    def test_lock_is_stable_until_something_is_clearly_closer(self):
        self._enemies(("BLACK", 0.0, 50.0), ("WHITE", 5.0, 60.0))
        black = self.teams.characters["BLACK"]
        self.assertIs(self.lock(), black)
        self.stand(self.teams.characters["WHITE"], 5.0, 47.0)
        self.game.elapsed += 1.0
        self.assertIs(self.lock(), black, "a little closer is not enough")
        self.stand(self.teams.characters["WHITE"], 5.0, 20.0)
        self.game.elapsed += 1.0
        self.assertIs(self.lock(), self.teams.characters["WHITE"])

    def test_acquisition_runs_at_a_bounded_rate(self):
        self._enemies(("BLACK", 0.0, 50.0))
        self.lock()
        from unittest import mock
        with mock.patch.object(self.combat.targets, "_acquire", wraps=self.combat.targets._acquire) as spy:
            for _ in range(5):
                self.lock()
        spy.assert_not_called()

    def test_allies_the_player_the_downed_and_the_absent_are_never_targeted(self):
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = "my_team"
        self.stand(ally, 0.0, 3.0)
        self.teams._apply_roster()
        self._enemies(("BLACK", 0.0, 50.0))
        self.assertIs(self.lock(), self.teams.characters["BLACK"])
        self.teams.characters["BLACK"].vitals.downed_for = 5.0
        self.assertIsNone(self.lock(), "a downed enemy clears the lock at once")
        self.teams.characters["BLACK"].vitals.downed_for = 0.0
        self.teams.state.assignment["BLACK"] = "available"
        self.teams._apply_roster()
        self.game.elapsed += 1.0
        self.assertIsNone(self.lock())

    def test_team_changes_and_switches_refresh_the_lock(self):
        self._enemies(("BLACK", 0.0, 50.0), ("WHITE", 0.0, 80.0))
        self.assertIs(self.lock(), self.teams.characters["BLACK"])
        self.teams.assign("BLACK", "my_team")
        self.assertIs(self.lock(), self.teams.characters["WHITE"])
        self.teams.swap("GREEN", save=False)
        self.assertIs(self.combat.targets.lock_of(self.game.sentry), self.teams.characters["WHITE"])

    def test_abilities_respect_their_own_range(self):
        self._enemies(("BLACK", 0.0, 400.0))
        beam = self.ability("chest_beam")
        self.assertIs(beam.target(), self.teams.characters["BLACK"])
        self.set("chest_beam", "range", 100)
        self.assertIsNone(beam.target())

    def test_attacks_reach_an_enemy_behind_the_camera_without_aiming(self):
        self._enemies(("BLACK", 0.0, -60.0))
        black = self.teams.characters["BLACK"]
        self.aim_at = SimVec3(0.0, self.player.y, 500.0)  # the camera is looking the other way
        beam = self.ability("chest_beam")
        beam.press()
        self.seconds(.8)
        beam.press()
        self.assertGreater(black.vitals.damage_taken, 0.0)

    def test_every_character_hits_with_no_manual_aim(self):
        first_key = {"WHITE": "1", "BLACK": "1", "YELLOW": "2", "GREEN": "2", "RED": "1"}  # those two 1s hit nobody at once
        for character_id, key in first_key.items():
            self.play(character_id)
            enemy_id = "GREEN" if character_id != "GREEN" else "WHITE"
            self.place_enemy(enemy_id, -30.0, x=20.0)
            self.aim_at = SimVec3(0.0, 2000.0, 0.0)  # straight up: nowhere useful
            self.tap(key)
            self.seconds(.8)
            self.assertGreater(self.enemy.vitals.damage_taken, 0.0, character_id)
            self.player.powers.cancel_all()
            self.player.release_motion()

    def test_the_camera_is_not_moved_by_targeting(self):
        self._enemies(("BLACK", 300.0, -200.0))
        yaw = self.game.camera.yaw
        self.tap("1")
        self.frames(10)
        self.assertEqual(self.game.camera.yaw, yaw)

    def test_hud_names_the_target_and_its_health(self):
        self._enemies(("BLACK", 0.0, 50.0))
        self.frames(1)
        self.game.hud._text_timer = 0.0
        self.game.hud.update()
        self.assertIn("HOMELANDER", self.game.hud.target_text.text)
        self.assertIn("HP", self.game.hud.target_text.text)


class HealthBarTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.teams = self.game.teams

    def test_every_character_has_one_attached_to_its_own_body(self):
        self.assertEqual(set(self.teams.tags), set(ROSTER_IDS))
        for character_id, tag in self.teams.tags.items():
            self.assertIs(tag.root.parent, self.teams.characters[character_id])
            self.assertEqual(tag.root.isHidden(), self.teams.characters[character_id] is self.game.sentry)
            self.assertEqual(tag.back.isHidden(), self.teams.characters[character_id] is self.game.sentry)

    def test_the_player_has_no_bar_over_their_head_in_any_body(self):
        for character_id in ROSTER_IDS:
            self.teams.swap(character_id, save=False)
            run_frames(self.game, 1)
            tag = self.teams.tags[character_id]
            self.assertTrue(tag.is_player)
            self.assertTrue(tag.root.isHidden())

    def test_it_updates_straight_after_damage_and_healing(self):
        for character_id in ROSTER_IDS:
            character = self.teams.characters[character_id]
            tag = self.teams.tags[character_id]
            character.vitals.regen = 0.0
            character.vitals.health = character.vitals.max_health * .4
            run_frames(self.game, 1)
            self.assertAlmostEqual(tag.fraction, .4, delta=.02, msg=character_id)
            self.assertAlmostEqual(tag.fill.scale_x, 1.9 * tag.fraction, delta=.001)
            character.vitals.heal(character.vitals.max_health * .3)
            run_frames(self.game, 1)
            self.assertAlmostEqual(tag.fraction, .7, delta=.02, msg=character_id)
            character.powers.apply_passives()

    def test_it_empties_when_downed_and_returns_after_recovery(self):
        character = self.teams.characters["GREEN"]
        tag = self.teams.tags["GREEN"]
        self.game.combat.hit_character(None, character, 1e9, PHYSICAL)
        run_frames(self.game, 1)
        self.assertEqual(tag.fraction, 0.0)
        character.vitals.downed_for = .01
        run_frames(self.game, 2)
        self.assertGreater(tag.fraction, 0.0)

    def test_team_colours_differ_and_follow_a_change(self):
        tags = self.teams.tags
        self.teams.state.assignment["GREEN"] = "my_team"
        self.teams.state.assignment["BLACK"] = "enemy_team"
        self.teams._apply_roster()
        ally, enemy = tags["GREEN"].fill.color, tags["BLACK"].fill.color
        self.assertNotEqual(ally, enemy)
        self.assertNotEqual(tags[self.game.sentry.character_id].fill.color, enemy)
        self.teams.state.assignment["GREEN"] = "enemy_team"
        self.teams._apply_roster()
        self.assertEqual(tags["GREEN"].fill.color, enemy)

    def test_the_targeted_enemy_gets_a_more_prominent_bar(self):
        self.teams.state.assignment["BLACK"] = "enemy_team"
        self.teams._apply_roster()
        run_frames(self.game, 2)
        enemy_tags = [tag for tag in self.teams.tags.values() if tag.targeted]
        self.assertEqual(len(enemy_tags), 1)
        self.assertTrue(enemy_tags[0].marker.enabled)
        scale = enemy_tags[0]._scale
        enemy_tags[0].set_targeted(False)
        enemy_tags[0].update(100.0, enemy_tags[0].character.vitals)
        self.assertLess(enemy_tags[0]._scale, scale * 10.0)
        normal = enemy_tags[0]._scale
        enemy_tags[0].set_targeted(True)
        enemy_tags[0].update(100.0, enemy_tags[0].character.vitals)
        self.assertGreater(enemy_tags[0]._scale, normal)

    def test_it_looks_smaller_with_distance_and_fades_far_away(self):
        tag = self.teams.tags["GREEN"]
        vitals = self.teams.characters["GREEN"].vitals
        tag.update(100.0, vitals)
        near = tag._scale
        tag.update(400.0, vitals)
        self.assertLess(tag._scale / near, 4.0)
        tag.update(3000.0, vitals)
        self.assertLess(tag._shown_alpha, 1.0)
        tag.update(100.0, vitals)
        self.assertEqual(tag._shown_alpha, 1.0)

    def test_it_sits_above_hair_and_helmets_on_every_character(self):
        for character_id, character in self.teams.characters.items():
            tops = [np.getTightBounds(character)[1].y
                    for np in character.pose_root.findAllMatches("**/+GeomNode")
                    if not np.isHidden() and np.getTightBounds(character) is not None]
            self.assertLess(max(tops), HEAD_TOP_METRES, character_id)
            self.assertLess(HEAD_TOP_METRES, self.teams.tags[character_id].root.y, character_id)

    def test_parked_characters_do_not_show_a_bar_and_nothing_is_created_per_frame(self):
        from ursina import scene
        white = self.teams.characters["WHITE"]
        self.teams.assign("WHITE", "available")
        self.assertFalse(white.enabled)
        before = len(scene.entities)
        run_frames(self.game, 20)
        self.assertEqual(len(scene.entities), before)
        self.teams.assign("WHITE", "my_team")

    def test_names_setting_hides_only_the_name(self):
        tag = self.teams.tags["GREEN"]
        tag.set_visible(False)
        self.assertFalse(tag.label.enabled)
        self.assertTrue(tag.fill.enabled)
        tag.set_visible(True)


class FlightRuleTests(unittest.TestCase):
    def test_every_other_character_can_fly_and_soldier_boy_never_can(self):
        game = reset_game()
        for character_id in ROSTER_IDS:
            game.teams.swap(character_id, save=False)
            body = game.sentry
            self.assertEqual(body.flight_allowed, character_id != "RED", character_id)
            game.input("f")
            run_frames(game, 2)
            self.assertEqual(body.flight.is_flying, character_id != "RED", character_id)
            if body.flight.is_flying:
                game.input("f")
            run_frames(game, 1)

    def test_maximum_settings_and_every_power_keep_soldier_boy_grounded(self):
        game = reset_game()
        game.combat.settings.max_all()
        game.apply_sentry_config()
        game.teams.swap("RED", save=False)
        red = game.sentry
        for key in ("1", "2", "3", "4", "r", "e", "q", "=", "-", "f"):
            game.input(key)
            for _ in range(10):
                game.update(FRAME)
                self.assertFalse(red.flight.is_flying, key)
                self.assertIs(red.flight.phase, FlightPhase.GROUNDED, key)
            game.input(f"{key} up")

    def test_a_melee_rush_at_a_flyer_keeps_soldier_boy_on_the_ground(self):
        game = reset_game()
        game.teams.swap("RED", save=False)
        red = game.sentry
        enemy = game.teams.characters["BLACK"]
        game.teams.state.assignment["BLACK"] = "enemy_team"
        game.teams._apply_roster()
        enemy.position = (0.0, 200.0, 50.0)
        enemy.flight.phase = FlightPhase.CRUISE
        red.powers.abilities["shield_combat"].press()  # as his AI does; the mouse no longer does
        floor_gap = 0.0
        for _ in range(120):
            game.update(FRAME)
            floor_gap = max(floor_gap, red.y - game.world.height_at(red.x, red.z))
        self.assertLess(floor_gap, 1.0)
        self.assertFalse(red.flight.is_flying)


class AIUnderNewRulesTests(unittest.TestCase):
    def test_ai_damage_is_limited_per_second_however_high_the_values(self):
        game = reset_game()
        combat = game.combat
        target = game.sentry
        source = game.teams.characters["BLACK"]
        game.teams.state.assignment["BLACK"] = "enemy_team"
        game.teams._apply_roster()
        target.vitals.resistance = 0.0
        for _ in range(20):
            combat.hit_character(source, target, 9000.0, PHYSICAL)
        self.assertLessEqual(target.vitals.damage_taken, target.vitals.max_health * .06 + .01)
        target.powers.apply_passives()

    def test_a_players_hits_are_not_limited(self):
        game = reset_game()
        victim = game.teams.characters["BLACK"]
        game.teams.state.assignment["BLACK"] = "enemy_team"
        game.teams._apply_roster()
        game.combat.hit_character(game.sentry, victim, 500.0, PHYSICAL)
        self.assertGreater(victim.vitals.damage_taken, 200.0)

    def test_ai_switches_its_sustained_powers_off_after_its_turn(self):
        game = reset_game(ai_powers=True)
        game.teams.state.assignment["BLACK"] = "enemy_team"
        game.teams._apply_roster()
        game.elapsed = 100.0
        seen_active = False
        for _ in range(60 * 30):
            game.update(FRAME)
            for character in game.teams.others:
                sustained = [ability for ability in character.powers.abilities.values()
                             if ability.active and ability.ability_id not in ("shield_throw", "squad_summon")]
                if character._ai_move is None:
                    self.assertEqual(sustained, [], character.character_id)
                elif sustained:
                    seen_active = True
        self.assertTrue(seen_active, "AI should have used a power in 30 seconds")


if __name__ == "__main__":
    unittest.main()
