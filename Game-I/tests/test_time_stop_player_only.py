"""Only the player stops time. AI keeps every attack, and plays each one out with the world running."""

from __future__ import annotations

import unittest
from unittest import mock

from ursina import held_keys

from config.character_roster import ENEMY_TEAM
from config.power_schema import SLOT_ABILITIES
from game_fixture import FRAME
from test_ai_power_sync import AICase, CURRENT, foe_of
from test_gameplay_control_update import LiveCase

ROSTER = ("WHITE", "BLACK", "GREEN", "YELLOW", "RED")
# Every key on each character that stops time when the player presses it.
# What AI may run that stops time for a player: Keys 3 and 4 are never AI's.
STOPPING = {"WHITE": ("2",), "BLACK": ("2",), "GREEN": ("2",), "YELLOW": ("2",), "RED": ("2",)}


class AICannotTests(AICase):
    def test_each_of_the_five_uses_each_attack_and_the_world_never_stops(self):
        for ai_id in ROSTER:
            for key in STOPPING[ai_id]:
                ability_id = CURRENT[ai_id][key]
                with self.subTest(ai_id, ability=ability_id):
                    self.fight(ai_id, distance=40.0)
                    with self.order(ai_id, ability_id):
                        self.game.update(FRAME)
                        motion = self.ai.motion
                        self.assertIsNotNone(motion, "the power is still there, and used")
                        for _ in range(round(40.0 / FRAME)):
                            self.assertFalse(self.combat.time_stopped)
                            self.assertFalse(self.combat.sequence_running)
                            if self.ai.motion is not motion:
                                break
                            self.game.update(FRAME)
                    self.assertIsNot(self.ai.motion, motion, "and it finishes")
                    self.assertGreater(self.player.vitals.damage_taken, 0.0, "with its real damage")

    def test_t_for_ai_does_nothing_on_all_five(self):
        for ai_id in ROSTER:
            with self.subTest(ai_id):
                self.fight(ai_id, distance=40.0)
                self.ai.powers.abilities["world_stop"].press()
                self.assertFalse(self.combat.world_stopped)
                self.assertFalse(self.combat.time_stopped)

    def test_the_world_keeps_moving_around_an_ai_attack(self):
        self.fight("GREEN", player="YELLOW", distance=40.0)
        with self.order("GREEN", "high_speed_attack"):
            self.game.update(FRAME)
            self.assertIsNotNone(self.ai.motion)
            elapsed = self.game.elapsed
            with mock.patch.object(self.game.world_manager, "update", wraps=self.game.world_manager.update) as world:
                self.frames(30)
            self.assertTrue(all(call.args[0] > 0.0 for call in world.call_args_list), "world time is advancing")
            self.assertGreater(self.game.elapsed, elapsed)
            self.ai.release_motion()

    def test_the_player_keeps_control_while_ai_attacks_someone_else_or_rushes_them(self):
        self.fight("WHITE", player="YELLOW", distance=300.0)
        x = float(self.player.x)
        with self.order("WHITE", "high_speed_attack"):
            self.game.update(FRAME)
            self.assertIsNotNone(self.ai.motion)
            held_keys["d"] = 1
            self.frames(10)
            held_keys["d"] = 0
            self.assertNotEqual(float(self.player.x), x, "not frozen")
            self.ai.release_motion()

    def test_two_ai_never_run_two_of_these_at_once(self):
        self.begin("YELLOW", "BLACK", 40.0, ai_powers=True)
        self.tough(self.player)
        self.tough(self.enemy)
        second = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(second, 10.0, 40.0)
        self.tough(second)
        running = (self.enemy, second)
        from ai.combat_ai import CINEMATIC_IDS
        for _ in range(round(40.0 / FRAME)):
            self.game.update(FRAME)
            self.assertFalse(self.combat.time_stopped)
            going = 0
            for body in running:
                ability = getattr(body.motion, "ability", None)
                going += ability is not None and ability.ability_id in CINEMATIC_IDS
            self.assertLessEqual(going, 1)

    def test_someone_who_left_mid_attack_does_not_block_the_next_attacker(self):
        self.fight("GREEN", player="YELLOW", distance=40.0)
        self.ai.motion = mock.Mock()
        self.teams.cinematic_started(self.game.elapsed, self.ai)
        self.teams._next_cinematic = 0.0
        self.assertFalse(self.teams.cinematic_ready(self.game.elapsed), "still at it")
        self.ai.set_parked(True)
        self.assertTrue(self.teams.cinematic_ready(self.game.elapsed))
        self.ai.motion = None
        self.ai.set_parked(False)

    def test_an_ai_attack_ending_does_not_end_the_players_stop(self):
        self.fight("GREEN", player="YELLOW", distance=40.0)
        with self.order("GREEN", "high_speed_attack"):
            self.game.update(FRAME)
            motion = self.ai.motion
            self.assertIsNotNone(motion)
            self.combat.begin_time_stop(self.player, self.ai)
            self.assertTrue(self.combat.sequence_running)
            self.ai.release_motion()
            self.assertTrue(self.combat.sequence_running, "still the player's")
            self.combat.end_time_stop(self.player)
            self.assertFalse(self.combat.time_stopped)


class PlayerCanTests(LiveCase):
    def tap(self, key: str) -> None:
        self.game.input(key)
        self.game.input(f"{key} up")

    def test_t_stops_the_world_for_all_five_and_ai_stands_frozen(self):
        for character_id in ROSTER:
            with self.subTest(character_id):
                self.begin(character_id, foe_of(character_id), 300.0, ai_powers=True)
                where = (float(self.enemy.x), float(self.enemy.z))
                self.tap("t")
                self.assertTrue(self.combat.world_stopped)
                self.seconds(1.0)
                self.assertEqual((float(self.enemy.x), float(self.enemy.z)), where, "frozen")
                self.assertIsNone(self.enemy.motion)
                self.combat.end_world_stop()

    def test_each_key_still_stops_the_world_when_the_player_presses_it(self):
        for character_id in ROSTER:
            for key in STOPPING[character_id]:
                with self.subTest(character_id, key=key):
                    self.assertIn(key, SLOT_ABILITIES[character_id])
                    self.begin(character_id, foe_of(character_id), 40.0)
                    self.tough(self.enemy)
                    self.tough(self.player)
                    self.frames(1)
                    self.tap(key)
                    motion = self.player.motion
                    self.assertIsNotNone(motion)
                    self.assertTrue(self.combat.time_stopped)
                    self.assertIs(self.combat.time_stop_owner, self.player)
                    for _ in range(round(45.0 / FRAME)):
                        if self.player.motion is not motion:
                            break
                        self.game.update(FRAME)
                    self.assertIsNot(self.player.motion, motion)
                    self.assertFalse(self.combat.time_stopped, "and time resumes")
                    self.assertGreater(self.enemy.vitals.damage_taken, 0.0)


if __name__ == "__main__":
    unittest.main()
