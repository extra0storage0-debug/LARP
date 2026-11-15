"""Who may set off what, Soldier Boy's Key 2, and fighting back from a knockdown. Through the same keys and calls as the game."""

from __future__ import annotations

import unittest

from ursina import held_keys

from ai.combat_ai import CINEMATIC_IDS, MOVES
from characters.registry import definitions
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from config.power_schema import PLAYER_ONLY_ABILITIES, RENAMED_ABILITIES, SLOT_ABILITIES, PowerSettings
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of
from powers.common import LaunchedMotion, launch_character
from powers.soldier_boy_attacks import FlyingPunch
from powers.universal import StrikeAndBreakAway
from test_gameplay_control_update import LiveCase

FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")
ROSTER = (*FLYERS, "RED")
FRAME = 1.0 / 60.0
ORIGINAL_KEY_2 = {"WHITE": "high_speed_attack", "BLACK": "high_speed_attack", "YELLOW": "high_speed_attack", "GREEN": "high_speed_attack"}


class Case(LiveCase):
    def set_up(self, character_id: str, enemy_id: str | None = None, distance: float = 40.0) -> None:
        enemy_id = enemy_id or ("RED" if character_id != "RED" else "WHITE")
        self.begin(character_id, enemy_id, distance)
        self.enemy = self.game.teams.characters[enemy_id]
        self.enemy.vitals.health = self.enemy.vitals.max_health = 1e7
        self.player.vitals.health = self.player.vitals.max_health = 1e7
        self.enemy.vitals.add_status("frozen", 600.0)  # a test of the player's fall, not of the enemy's next move

    def knock(self, up: float = 30.0, back: float = 25.0) -> None:
        launch_character(self.enemy, self.player, SimVec3(0.0, up, -back))
        self.assertIsInstance(self.player.motion, LaunchedMotion)

    def fall_for(self, seconds: float = .4) -> None:
        self.seconds(seconds)
        self.assertIsInstance(self.player.motion, LaunchedMotion, "still falling")

    def lie_down(self) -> None:
        self.knock(up=14.0, back=30.0)
        for _ in range(600):
            self.frames(1)
            motion = self.player.motion
            if motion is None or (isinstance(motion, LaunchedMotion) and motion.landed):
                break
        self.assertIsInstance(self.player.motion, LaunchedMotion, "lying on the ground")
        self.assertTrue(self.player.motion.landed)

    def finish_motion(self, limit: float = 30.0) -> None:
        for _ in range(int(limit * 60)):
            if self.player.motion is None and not self.game.combat.sequence_running:
                return
            self.frames(1)
        self.fail(f"still in {type(self.player.motion).__name__}")


class PermissionTests(Case):
    def test_keys_3_and_4_are_player_only_for_everyone_on_the_roster(self):
        for item in definitions():
            self.assertEqual(PLAYER_ONLY_ABILITIES[item.character_id],
                             {item.slots[key] for key in ("3", "4") if key in item.slots}, item.character_id)

    def test_ai_is_never_offered_them(self):
        for character_id in ROSTER:
            offered = {move.ability_id for move in MOVES[character_id]}
            self.assertFalse(offered & PLAYER_ONLY_ABILITIES[character_id], character_id)
            self.assertIn(SLOT_ABILITIES[character_id]["1"], offered)
            self.assertIn(SLOT_ABILITIES[character_id]["2"], offered)

    def test_calling_the_ability_directly_as_ai_does_nothing(self):
        for character_id in ROSTER:
            with self.subTest(character_id):
                self.set_up(character_id)
                body = self.enemy  # someone AI runs
                body.vitals.clear_status("frozen")
                self.assertFalse(body.controlled)
                for key in ("3", "4"):
                    body.powers.slots[key].press()
                    self.assertIsNone(body.motion, key)
                    self.assertFalse(self.game.combat.sequence_running)
                # through the key route as well, which is not AI's, but must not be a way round
                body.powers.press("3")
                body.powers.press("4")
                self.assertIsNone(body.motion)

    def test_a_long_ai_fight_never_starts_them(self):
        for character_id in ROSTER:
            with self.subTest(character_id):
                enemy_id = "RED" if character_id != "RED" else "WHITE"
                self.begin(enemy_id, character_id, 25.0)
                body = self.game.teams.characters[character_id]
                self.player.vitals.health = self.player.vitals.max_health = 1e7
                body.vitals.health = body.vitals.max_health = 1e7
                forbidden = PLAYER_ONLY_ABILITIES[character_id]
                used = set()
                for ability_id in forbidden:
                    ability = body.powers.abilities[ability_id]
                    ability.press = lambda chosen=ability_id: used.add(chosen)  # were anything to get past the table
                for _ in range(600):
                    self.frames(1)
                for ability_id in forbidden:
                    del body.powers.abilities[ability_id].press
                self.assertEqual(used, set())

    def test_the_player_still_has_both(self):
        for character_id in ROSTER:
            with self.subTest(character_id):
                self.set_up(character_id)
                for key in ("3", "4"):
                    self.set_up(character_id)
                    self.enemy.vitals.clear_status("frozen")
                    self.game.input(key)
                    self.frames(2)
                    self.assertIsNotNone(self.player.motion, f"key {key}")
                    self.game.input(f"{key} up")
                    self.finish_motion(40.0)
                    self.assertFalse(self.game.combat.time_stopped, f"key {key}")

    def test_when_the_player_leaves_a_body_ai_loses_them_and_the_new_body_has_them(self):
        self.set_up("WHITE")
        white = self.player
        self.assertTrue(white.powers.slots["3"].permitted)
        self.game.teams.state.assignment["BLACK"] = MY_TEAM
        self.game.teams._apply_roster()
        self.game.teams.swap("BLACK", save=False)
        self.assertFalse(white.powers.slots["3"].permitted)
        self.assertTrue(self.game.teams.characters["BLACK"].powers.slots["3"].permitted)

    def test_a_future_power_is_covered_without_being_listed(self):
        from powers.base import Ability

        class NewPower(Ability):
            ability_id = PLAYER_ONLY_ABILITIES["WHITE"].__iter__().__next__()
            fired = False

            def press(self):
                type(self).fired = True

        self.set_up("WHITE")
        NewPower(self.enemy if self.enemy.character_id == "WHITE" else self.game.teams.characters["WHITE"])
        body = self.enemy
        power = NewPower.__new__(NewPower)
        power.owner, power.character_id, power.active = body, "WHITE", False
        power.press()
        self.assertFalse(NewPower.fired)
        power.owner = self.player
        power.press()
        self.assertTrue(NewPower.fired)


class Key2Tests(Case):
    def test_the_other_four_keep_their_own(self):
        for character_id, ability_id in ORIGINAL_KEY_2.items():
            with self.subTest(character_id):
                self.assertEqual(SLOT_ABILITIES[character_id]["2"], ability_id)
                self.set_up(character_id, distance=60.0)
                self.game.input("2")
                self.frames(1)
                self.assertIsInstance(self.player.motion, StrikeAndBreakAway)
                self.assertNotIsInstance(self.player.motion, FlyingPunch)
                self.game.input("2 up")
                self.finish_motion()
                self.assertFalse(self.game.combat.time_stopped)

    def test_soldier_boys_old_key_2_is_gone(self):
        self.assertEqual(SLOT_ABILITIES["RED"]["2"], "flying_punch")
        self.set_up("RED", distance=60.0)
        self.assertNotIn("high_jump_punch", self.player.powers.abilities)

    def start(self, distance: float = 80.0) -> None:
        self.set_up("RED", distance=distance)
        self.enemy.vitals.clear_status("frozen")
        self.game.input("2")
        self.frames(1)
        self.game.input("2 up")
        self.assertIsInstance(self.player.motion, FlyingPunch)

    def test_it_stops_the_world_and_he_is_the_one_still_moving(self):
        self.set_up("RED", distance=400.0)
        self.enemy.vitals.clear_status("frozen")
        bystander = self.game.teams.characters["BLACK"]
        self.game.teams.state.assignment["BLACK"] = ENEMY_TEAM
        self.game.teams._apply_roster()
        self.stand(bystander, 300.0, 300.0)
        self.frames(2)
        self.game.input("2")
        self.game.input("2 up")
        self.assertTrue(self.game.combat.time_stopped)
        where = (float(self.enemy.x), float(self.enemy.y), float(self.enemy.z))
        aside = (float(bystander.x), float(bystander.y), float(bystander.z))
        before = float(self.player.z)
        self.frames(2)
        self.assertGreater(float(self.player.z), before + 20.0, "he moves")
        self.assertEqual(where, (float(self.enemy.x), float(self.enemy.y), float(self.enemy.z)), "the target waits")
        self.assertEqual(aside, (float(bystander.x), float(bystander.y), float(bystander.z)), "and so does everyone else")
        self.finish_motion()
        self.frames(30)
        self.assertNotEqual(aside, (float(bystander.x), float(bystander.y), float(bystander.z)), "until it is over")

    def test_the_punch_lands_on_the_target_where_it_really_is_and_throws_them(self):
        self.start(distance=200.0)
        speeds, last = [], (float(self.player.x), float(self.player.y), float(self.player.z))
        before = self.enemy.vitals.damage_taken
        distance = None
        while self.player.motion is not None and self.player.motion.connected_for is None:
            self.frames(1)
            now = (float(self.player.x), float(self.player.y), float(self.player.z))
            speeds.append(sum((a - b) ** 2 for a, b in zip(now, last)) ** .5 * 60.0)
            last = now
            distance = (center_of(self.player) - center_of(self.enemy)).length() if self.enemy.motion is None else distance
        self.assertLess(distance, 4.0, "he stopped at the target")
        self.assertGreater(max(speeds), 500.0, "extreme speed")
        self.assertGreater(self.enemy.vitals.damage_taken, before)
        self.assertIsInstance(self.enemy.motion, LaunchedMotion)
        self.finish_motion()
        self.assertFalse(self.game.combat.time_stopped)
        spot = float(self.enemy.z)
        self.frames(10)
        self.assertNotEqual(float(self.enemy.z), spot, "and when time resumes the target flies")

    def test_it_reaches_a_target_in_the_air(self):
        self.set_up("RED", distance=50.0)
        self.enemy.y = float(self.enemy.y) + 60.0
        self.enemy.vitals.clear_status("frozen")
        before = self.enemy.vitals.damage_taken
        self.game.input("2")
        self.frames(1)
        self.game.input("2 up")
        self.finish_motion()
        self.assertGreater(self.enemy.vitals.damage_taken, before)

    def test_he_never_gains_flight_and_comes_back_down(self):
        self.start()
        flying = []
        for _ in range(240):
            self.frames(1)
            flying.append(self.player.flight.is_flying)
        self.assertFalse(any(flying))
        self.assertIsNone(self.player.motion)
        self.assertLess(self.player.jump_height, .01, "and he is back on the ground")

    def test_a_second_press_does_not_stack_a_stop(self):
        self.start()
        motion = self.player.motion
        self.game.input("2")
        self.frames(1)
        self.game.input("2 up")
        self.assertIs(self.player.motion, motion)
        self.finish_motion()
        self.assertFalse(self.game.combat.time_stopped)

    def test_time_always_resumes_if_the_target_goes_away(self):
        for leave in ("parked", "downed", "released", "swapped"):
            with self.subTest(leave):
                self.start(distance=300.0)
                if leave == "parked":
                    self.game.teams.state.assignment[self.enemy.character_id] = AVAILABLE
                    self.game.teams._apply_roster()
                elif leave == "downed":
                    self.enemy.vitals.downed_for = 5.0
                elif leave == "released":
                    self.player.motion = None  # however the motion went, without its own clean-up
                else:
                    self.game.teams.state.assignment[self.enemy.character_id] = MY_TEAM
                    self.game.teams._apply_roster()
                self.frames(5)
                self.finish_motion(5.0)
                self.frames(2)
                self.assertFalse(self.game.combat.time_stopped, leave)
                self.game.teams.state.assignment[self.enemy.character_id] = ENEMY_TEAM

    def test_something_that_blocks_him_cannot_leave_time_stopped(self):
        self.start(distance=300.0)
        self.player.motion._carry = lambda step: None  # however it comes about, he makes no progress
        self.finish_motion(5.0)
        self.assertFalse(self.game.combat.time_stopped)

    def test_ai_soldier_boy_uses_it_with_the_world_still_running(self):
        self.begin("WHITE", "RED", 60.0)
        red = self.game.teams.characters["RED"]
        red.vitals.health = red.vitals.max_health = 1e7
        self.player.vitals.health = self.player.vitals.max_health = 1e7
        red.powers.abilities["flying_punch"].press()
        self.assertIsInstance(red.motion, FlyingPunch)
        self.assertFalse(self.game.combat.time_stopped, "only a player stops time")
        self.assertIn("flying_punch", CINEMATIC_IDS)

    def test_what_the_player_set_on_the_old_one_carries_over(self):
        import json
        import tempfile
        from pathlib import Path
        self.assertEqual(RENAMED_ABILITIES[("RED", "high_jump_punch")], "flying_punch")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "powers.json"
            path.write_text(json.dumps({"version": 3, "values": {"RED": {"high_jump_punch": {"speed": 186, "damage": 2000}}}}), encoding="utf-8")
            settings = PowerSettings(path)
            self.assertEqual(settings.get("RED", "flying_punch", "speed"), 186)
            self.assertEqual(settings.get("RED", "flying_punch", "damage"), 2000)


class KnockdownTests(Case):
    def test_the_blow_still_lands_and_the_body_really_falls(self):
        self.set_up("WHITE")
        self.knock()
        y = float(self.player.y)
        self.seconds(.3)
        self.assertGreater(float(self.player.y), y, "it goes up with the blow")
        self.assertIsInstance(self.player.motion, LaunchedMotion)

    def test_every_key_works_while_falling_for_everyone(self):
        for character_id in ROSTER:
            for key in ("1", "2", "3", "4"):
                with self.subTest(character=character_id, key=key):
                    self.set_up(character_id)
                    self.knock()
                    self.fall_for()
                    ability = self.player.powers.slots[key]
                    position = (float(self.player.x), float(self.player.y), float(self.player.z))
                    self.game.input(key)
                    moved = sum((a - b) ** 2 for a, b in zip(position, (float(self.player.x), float(self.player.y), float(self.player.z))))
                    self.assertLess(moved, 1.0, "no teleport")
                    self.assertNotIsInstance(self.player.motion, LaunchedMotion, "out of the tumble")
                    self.assertTrue(ability.active or self.player.motion is not None or ability.hud_state(), "the power started")
                    self.game.input(f"{key} up")
                    self.frames(2)
                    self.player.powers.cancel_all()
                    self.player.release_motion()
                    self.game.combat.end_time_stop()
                    self.frames(2)
                    self.assertFalse(self.game.combat.time_stopped)

    def test_every_key_works_lying_on_the_ground(self):
        for character_id in ROSTER:
            for key in ("1", "2", "3", "4"):
                with self.subTest(character=character_id, key=key):
                    self.set_up(character_id)
                    self.lie_down()
                    ability = self.player.powers.slots[key]
                    self.game.input(key)
                    self.assertNotIsInstance(self.player.motion, LaunchedMotion)
                    self.assertTrue(ability.active or self.player.motion is not None or ability.hud_state(), "the power started")
                    self.game.input(f"{key} up")
                    self.frames(2)
                    self.player.powers.cancel_all()
                    self.player.release_motion()
                    self.game.combat.end_time_stop()

    def test_key_2_and_3_land_on_the_target_from_a_fall_and_time_resumes(self):
        for character_id in ROSTER:
            for key in ("2", "3"):
                with self.subTest(character=character_id, key=key):
                    self.set_up(character_id, distance=50.0)
                    self.enemy.vitals.clear_status("frozen")
                    self.knock()
                    self.fall_for()
                    before = self.enemy.vitals.damage_taken
                    self.game.input(key)
                    self.frames(1)
                    self.assertTrue(self.game.combat.time_stopped)
                    self.game.input(f"{key} up")
                    self.finish_motion(40.0)
                    self.assertFalse(self.game.combat.time_stopped)
                    self.assertGreater(self.enemy.vitals.damage_taken, before)

    def test_a_power_that_does_not_move_the_body_leaves_it_falling_as_it_was(self):
        self.set_up("WHITE", distance=50.0)
        self.knock(up=40.0, back=30.0)
        self.fall_for(.25)
        speed_back = self.player.motion.velocity.z
        self.game.input("1")
        self.game.input("1 up")
        self.assertIsNone(self.player.motion)
        self.assertGreater(self.player.jump_height, 1.0)
        self.assertAlmostEqual(self.player.ground.velocity.z, speed_back, delta=1.0, msg="its speed is its own still")
        for _ in range(900):
            self.frames(1)
            if self.player.jump_height <= 0.0:
                break
        self.assertLess(self.player.jump_height, .01, "and gravity brings it down")
        self.assertLess(abs(self.player.pose_root.getP()), 30.0)
        self.player.powers.cancel_all()

    def test_f_recovers_into_flight_from_a_fall_with_its_speed(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.set_up(character_id)
                self.knock()
                self.fall_for()
                velocity = self.player.motion.velocity
                y = float(self.player.y)
                self.game.input("f")
                self.game.input("f up")
                self.assertTrue(self.player.flight.is_flying)
                self.assertIsNone(self.player.motion)
                self.assertAlmostEqual(self.player.flight.velocity.z, velocity.z, delta=1.0)
                self.assertAlmostEqual(float(self.player.y), y, delta=.5)
                pitch = []
                for _ in range(90):
                    self.frames(1)
                    pitch.append(abs(self.player.visual.body_root.getP()))
                self.assertLess(pitch[-1], 2.0, "upright again")
                self.assertTrue(self.player.flight.is_flying)
                self.assertEqual(self.player.flight_pose, "hands_on_hips")

    def test_f_recovers_into_flight_from_the_ground(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.set_up(character_id)
                self.lie_down()
                self.game.input("f")
                self.game.input("f up")
                self.assertTrue(self.player.flight.is_flying)
                self.assertIsNone(self.player.motion)

    def test_f_after_another_power_has_ended_the_tumble_still_flies(self):
        self.set_up("WHITE")
        self.knock()
        self.fall_for()
        self.game.input("1")
        self.game.input("1 up")
        self.assertIsNone(self.player.motion)
        self.game.input("f")
        self.game.input("f up")
        self.assertTrue(self.player.flight.is_flying)
        self.assertIsNone(self.player.motion)
        self.player.powers.cancel_all()

    def test_f_in_the_air_after_a_jump_is_still_the_slam(self):
        self.set_up("WHITE")
        self.game.input("space")
        self.seconds(.4)
        self.game.input("space up")
        self.player.jump_height = max(self.player.jump_height, 8.0)
        self.game.input("f")
        self.game.input("f up")
        self.assertFalse(self.player.flight.is_flying)
        self.assertIsNotNone(self.player.motion)

    def test_soldier_boy_cannot_recover_into_flight(self):
        self.set_up("RED")
        self.knock(up=60.0)
        self.fall_for(.5)
        self.game.input("f")
        self.game.input("f up")
        self.assertFalse(self.player.flight.is_flying)
        self.frames(10)
        self.assertFalse(self.player.flight.is_flying)

    def test_t_works_while_falling_and_the_world_resumes(self):
        self.set_up("WHITE")
        self.knock()
        self.fall_for()
        self.game.input("t")
        self.game.input("t up")
        self.frames(1)
        self.assertTrue(self.game.combat.world_stopped)
        self.assertNotIsInstance(self.player.motion, LaunchedMotion)
        self.game.combat.end_world_stop()
        self.assertFalse(self.game.combat.time_stopped)

    def test_the_skeleton_is_whole_after_a_recovery(self):
        for character_id in ROSTER:
            with self.subTest(character_id):
                self.set_up(character_id)
                self.knock()
                self.fall_for()
                self.game.input("1")
                self.game.input("1 up")
                self.seconds(2.5)
                self.player.powers.cancel_all()
                self.seconds(1.0)
                visual = self.player.visual
                self.assertLess(abs(self.player.pose_root.getP()), 12.0)
                self.assertLess(abs(visual.body_root.getP()), 2.0)
                self.assertLess(abs(self.player.left_leg.rotation_x), 12.0)
                self.assertLess(abs(self.player.left_arm.rotation_x), 20.0)

    def test_a_key_with_nothing_available_does_not_get_the_body_up(self):
        self.set_up("WHITE")
        self.knock()
        self.fall_for()
        self.player.vitals.add_status("nullified", 30.0)
        self.game.input("1")
        self.game.input("1 up")
        self.assertIsInstance(self.player.motion, LaunchedMotion)

    def test_ai_gets_no_such_help(self):
        self.set_up("WHITE")
        body = self.enemy
        body.vitals.clear_status("frozen")
        launch_character(self.player, body, SimVec3(0.0, 30.0, 10.0))
        body.powers.press("1")
        self.assertIsInstance(body.motion, LaunchedMotion, "AI is still knocked about")
        body.release_motion()

    def test_nothing_about_a_blow_changes_at_zero_health(self):
        self.set_up("WHITE")
        self.knock()
        self.fall_for()
        self.player.vitals.downed_for = 5.0
        self.game.input("1")
        self.game.input("1 up")
        self.assertIsInstance(self.player.motion, LaunchedMotion, "defeat is not a knockdown")
        self.player.vitals.downed_for = 0.0


if __name__ == "__main__":
    unittest.main()
