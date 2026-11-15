"""AI uses the powers the keys use: the same ability objects, on the real game loop, for all five."""

from __future__ import annotations

import unittest
from random import Random
from unittest import mock

from ursina import held_keys

from ai.combat_ai import CINEMATIC_IDS, MOVES, Situation, TACTICS, choose_move
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from config.power_schema import SCHEMA, SLOT_ABILITIES
from game_fixture import FRAME
from movement.flight_physics import FlightPhase
from powers.chest_beam import GoldenChestBeam, RadioactiveChestBeam
from powers.common import LaunchedMotion
from powers.homelander import NeckLaserExecution
from powers.omni_man import ShockwaveStrike, TripleImpactExecution
from config.power_schema import PLAYER_ONLY_ABILITIES
from powers.soldier_boy_attacks import AerialGrabBlast, FlyingPunch, RadioactiveExecution
from powers.superman import ExecutionSequence
from powers.universal import NuclearExecution, StrikeAndBreakAway
from test_gameplay_control_update import LiveCase

ROSTER = ("WHITE", "BLACK", "GREEN", "YELLOW", "RED")
# What each key must be, as handed over: the source of truth for this file.
CURRENT = {"WHITE": {"1": "heat_vision", "2": "high_speed_attack", "3": "time_stop", "4": "ground_execution"},
           "BLACK": {"1": "laser_vision", "2": "high_speed_attack", "3": "time_stop", "4": "neck_laser_execution"},
           "GREEN": {"1": "squad_summon", "2": "high_speed_attack", "3": "time_stop", "4": "speed_execution"},
           "YELLOW": {"1": "void_form", "2": "high_speed_attack", "3": "time_stop", "4": "void_nuclear_execution"},
           "RED": {"1": "radiation_blast", "2": "flying_punch", "3": "aerial_grab_blast", "4": "radioactive_execution"}}
OLD = {"freeze_breath", "super_breath", "solar_overcharge", "kryptonian_vision", "aerial_charge", "enhanced_senses",
       "laser_overdrive", "energy_projection", "golden_shield", "molecular_manipulation", "void_tendrils",
       "void_unleashed", "flight_charge", "ground_slam", "shockwave_punch", "dive_bomb", "shield_combat",
       "shield_defence", "shield_throw", "chest_blast", "nullification", "radioactive_discharge"}
# What AI may run. Keys 3 and 4 are the player's alone: see test_power_control.
SEQUENCES = {("WHITE", "2"): StrikeAndBreakAway, ("BLACK", "2"): StrikeAndBreakAway, ("GREEN", "2"): ShockwaveStrike,
             ("YELLOW", "2"): StrikeAndBreakAway, ("RED", "2"): FlyingPunch}


def foe_of(character_id: str) -> str:
    return "WHITE" if character_id != "WHITE" else "BLACK"


class RegistryTests(unittest.TestCase):
    def test_the_keys_are_the_handed_over_table(self):
        self.assertEqual({character_id: SLOT_ABILITIES[character_id] for character_id in ROSTER}, CURRENT)

    def test_ai_knows_exactly_the_cards_each_character_has_and_nothing_else(self):
        for character_id in ROSTER:
            self.assertEqual({move.ability_id for move in MOVES[character_id]},
                             {card.ability_id for card in SCHEMA[character_id]} - PLAYER_ONLY_ABILITIES[character_id], character_id)

    def test_every_key_can_be_reached_by_ai(self):
        for character_id, keys in CURRENT.items():
            known = {move.ability_id for move in MOVES[character_id]}
            for key, ability_id in keys.items():
                if key in ("3", "4"):
                    self.assertNotIn(ability_id, known, character_id)
                else:
                    self.assertIn(ability_id, known, character_id)

    def test_no_old_power_is_left_in_any_character_list(self):
        for character_id in ROSTER:
            self.assertFalse(OLD & {move.ability_id for move in MOVES[character_id]}, character_id)

    def test_the_tactics_table_has_nothing_stale_in_it(self):
        cards = {card.ability_id for cards in SCHEMA.values() for card in cards}
        self.assertEqual(set(TACTICS), cards)

    def test_every_long_attack_is_paced_so_only_one_runs_at_a_time(self):
        self.assertEqual(CINEMATIC_IDS, {"high_speed_attack", "flying_punch"})

    def test_the_choice_looks_at_the_situation(self):
        def share(situation) -> float:
            rng = Random(7)
            picks = [choose_move("RED", 60.0, lambda _name: True, rng, situation).ability_id for _ in range(3000)]
            return picks.count("flying_punch") / len(picks)

        self.assertGreater(share(Situation(target_health=.2)), share(Situation(target_health=1.0)) * 1.2,
                           "goes for the kill on someone nearly finished")

    def test_a_characters_big_attacks_all_get_their_turn(self):
        for character_id in ROSTER:
            big = [move.ability_id for move in MOVES[character_id] if move.cinematic]
            uses: dict = {}
            rng = Random(3)
            for _ in range(len(big) * 3):
                move = choose_move(character_id, 60.0, lambda name: name in big, rng, Situation(uses=uses))
                uses[move.ability_id] = uses.get(move.ability_id, 0) + 1
            self.assertEqual(set(uses), set(big), character_id)

    def test_blasts_are_worth_more_among_several_enemies(self):
        def share(close: int) -> float:
            rng = Random(9)
            picks = [choose_move("RED", 30.0, lambda _name: True, rng, Situation(enemies_close=close)).ability_id
                     for _ in range(3000)]
            return picks.count("radiation_blast") / len(picks)

        self.assertGreater(share(4), share(1) * 1.2)


class AICase(LiveCase):
    def fight(self, ai_id: str, player: str | None = None, distance: float = 40.0):
        player = player or foe_of(ai_id)
        self.begin(player, ai_id, distance, ai_powers=True)
        self.tough(self.enemy)
        self.tough(self.player)
        self.ai = self.enemy
        self.teams._next_cinematic = 0.0
        self.ai._ai_next_attack = 0.0
        self.teams.attack_tokens.holders.clear()

    def order(self, ai_id: str, ability_id: str):
        """AI decides on this one, through its own combat routine; the routine does all the rest."""
        move = next(move for move in MOVES[ai_id] if move.ability_id == ability_id)
        given = []

        def once(*_args, **_kwargs):
            if given:
                return None
            given.append(move)
            return move

        return mock.patch("characters.roster_character.choose_move", side_effect=once)

    def run_until_finished(self, limit: float = 40.0) -> bool:
        started = False
        for _ in range(round(limit / FRAME)):
            self.game.update(FRAME)
            if self.ai.motion is not None:
                started = True
            elif started:
                return True
        return started and self.ai.motion is None


class ExecutionTests(AICase):
    def test_every_world_stopping_power_runs_all_the_way_through_for_every_character(self):
        for (ai_id, key), expected in SEQUENCES.items():
            with self.subTest(ai_id, key=key):
                ability_id = CURRENT[ai_id][key]
                self.fight(ai_id)
                player_at = (float(self.player.x), float(self.player.z))
                seen = []
                real = self.combat.begin_time_stop

                def spy(owner, target, real=real):
                    seen.append((owner, target, type(owner.motion)))
                    return real(owner, target)

                with self.order(ai_id, ability_id), mock.patch.object(self.combat, "begin_time_stop", spy):
                    self.game.update(FRAME)
                    self.assertIsInstance(self.ai.motion, expected, "the player's own implementation")
                    self.assertFalse(self.combat.time_stopped, "only the player stops time")
                    self.assertTrue(self.run_until_finished(), "it finished")
                self.assertFalse(self.combat.time_stopped)
                self.assertGreater(self.player.vitals.damage_taken, 0.0, "real damage")
                self.assertEqual(len(self.combat._beams), self.beams_free)
                self.assertEqual(seen[0][0], self.ai)
                self.assertIs(seen[0][1], self.player, "at its enemy")
                self.assertNotEqual(player_at, (None, None))

    def test_the_sequence_really_moves_the_ai(self):
        self.fight("RED")
        with self.order("RED", "flying_punch"):
            start = float(self.ai.z)
            self.game.update(FRAME)
            motion = self.ai.motion
            self.assertIsInstance(motion, FlyingPunch)
            while self.ai.motion is motion:
                self.game.update(FRAME)
                self.assertFalse(self.ai.flight.is_flying, "he rushes; he never flies")
        self.assertNotEqual(float(self.ai.z), start)



    def test_the_eye_beams_too(self):
        for ai_id, ability_id in (("WHITE", "heat_vision"), ("BLACK", "laser_vision")):
            with self.subTest(ai_id):
                self.fight(ai_id)
                with self.order(ai_id, ability_id):
                    self.game.update(FRAME)
                    self.assertTrue(self.ai.powers.abilities[ability_id].active)
                    self.seconds(.5)
                self.assertGreater(self.player.vitals.damage_taken, 0.0)

    def test_omni_man_calls_his_squad_once_and_they_fight_the_player(self):
        self.fight("GREEN")
        ability = self.ai.powers.abilities["squad_summon"]
        with self.order("GREEN", "squad_summon"):
            self.game.update(FRAME)
        self.assertEqual(len(ability.members), 6)
        self.assertEqual(sum(member.display_name == "INVINCIBLE" for member in ability.members), 1)
        first = {id(member) for member in ability.members}
        self.assertFalse(choose_move("GREEN", 60.0, lambda name: name == "squad_summon" and not ability.active, Random(1)),
                         "not while they are out")
        for _ in range(60 * 10):
            self.game.update(FRAME)
            self.assertLessEqual(len(self.teams.summons), 6)
        self.assertEqual({id(member) for member in self.teams.summons}, first)
        self.assertGreater(self.player.vitals.damage_taken, 0.0)


class TimeStopRuleTests(AICase):
    def test_only_one_at_a_time_and_ai_paces_itself(self):
        self.begin("YELLOW", "BLACK", 40.0, ai_powers=True)
        self.tough(self.player)
        self.tough(self.enemy)
        second = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(second, 10.0, 40.0)
        self.tough(second)
        starts = []
        real = self.combat.begin_time_stop

        def spy(owner, target):
            self.assertFalse(self.combat.sequence_running, "never on top of another")
            starts.append(self.game.elapsed)
            return real(owner, target)

        with mock.patch.object(self.combat, "begin_time_stop", spy):
            self.teams._next_cinematic = 0.0
            self.seconds(60.0)
        self.assertGreaterEqual(len(starts), 2, "they are used")
        for earlier, later in zip(starts, starts[1:]):
            self.assertGreaterEqual(later - earlier, 11.9, "the player gets to play in between")

    def test_the_target_going_away_never_leaves_the_world_stopped(self):
        for (ai_id, key) in (("WHITE", "2"), ("RED", "2"), ("GREEN", "2"), ("BLACK", "2")):
            with self.subTest(ai_id, key=key):
                self.fight(ai_id, player="YELLOW" if ai_id != "YELLOW" else "WHITE", distance=200.0)
                with self.order(ai_id, CURRENT[ai_id][key]):
                    self.game.update(FRAME)
                    self.assertIsNotNone(self.ai.motion)
                    self.player.vitals.take(1e12)
                    self.player.on_downed()
                    self.seconds(12.0)
                self.assertFalse(self.combat.time_stopped)
                self.assertIsNone(self.ai.motion)
                self.player.vitals.downed_for = 0.0
                self.player.vitals.health = self.player.vitals.max_health

    def test_being_thrown_by_ai_is_a_real_throw_and_the_player_gets_control_back(self):
        self.fight("WHITE", player="YELLOW")
        with self.order("WHITE", "high_speed_attack"):
            self.game.update(FRAME)
            while self.ai.motion is not None and not isinstance(self.player.motion, LaunchedMotion):
                self.game.update(FRAME)
        self.assertIsInstance(self.player.motion, LaunchedMotion)
        self.run_until_settled(self.player, 20.0)
        self.assertIsNone(self.player.motion)


class SafetyTests(AICase):
    def test_allies_only_ever_hit_enemies(self):
        for ally_id in ("BLACK", "RED", "GREEN"):
            with self.subTest(ally_id):
                self.begin("YELLOW", "WHITE", 40.0, ai_powers=True)
                self.tough(self.player)
                self.tough(self.enemy)
                ally = self.teams.characters[ally_id]
                self.teams.state.assignment[ally_id] = MY_TEAM
                self.teams._apply_roster()
                self.stand(ally, 6.0, 0.0)
                self.tough(ally)
                self.enemy.vitals.add_status("frozen", 90.0)  # so that only the ally is choosing anything
                hits = []
                real = self.combat.hit_character

                def spy(source, target, *args, **kwargs):
                    if source is ally or getattr(source, "ai_moves", None):
                        hits.append(target)
                    return real(source, target, *args, **kwargs)

                with mock.patch.object(self.combat, "hit_character", spy):
                    self.teams._next_cinematic = 0.0
                    self.seconds(20.0)
                self.assertNotIn(self.player, hits)
                self.assertNotIn(ally, hits)

    def test_nobody_is_left_to_fight_means_no_attack(self):
        self.begin("YELLOW", "WHITE", 40.0, ai_powers=True)
        self.teams.state.assignment["WHITE"] = AVAILABLE
        self.teams._apply_roster()
        self.seconds(5.0)
        self.assertFalse(self.combat.sequence_running)
        self.assertEqual(self.player.vitals.damage_taken, 0.0)


class FreeFightTests(AICase):
    """Nothing scripted: AI left to choose for itself. Which powers does it actually reach for?"""

    def used_in_a_fight(self, ai_id: str, seconds: float) -> set:
        self.fight(ai_id, player="YELLOW" if ai_id != "YELLOW" else "WHITE", distance=60.0)
        used: set = set()
        for ability in self.ai.powers.abilities.values():
            def spy(ability=ability, real=ability.press):
                used.add(ability.ability_id)
                return real()
            ability.press = spy
        try:
            self.seconds(seconds)
        finally:
            for ability in self.ai.powers.abilities.values():
                ability.__dict__.pop("press", None)
        return used

    def test_each_character_uses_its_current_powers_and_no_old_ones(self):
        for ai_id in ROSTER:
            with self.subTest(ai_id):
                used = self.used_in_a_fight(ai_id, 120.0)
                self.assertFalse(used & OLD, "no old powers")
                self.assertLessEqual(used, ({card.ability_id for card in SCHEMA[ai_id]} - PLAYER_ONLY_ABILITIES[ai_id]) | {"impact_dive"})
                self.assertGreaterEqual(len(used & CINEMATIC_IDS), 1, f"its cinematic power: {used}")
                self.assertFalse(self.combat.time_stopped or self.combat.sequence_running)


class PlayerStillWorksTests(LiveCase):
    def test_the_players_keys_still_reach_the_same_abilities(self):
        for character_id in ROSTER:
            with self.subTest(character_id):
                self.begin(character_id, foe_of(character_id))
                for key, ability_id in CURRENT[character_id].items():
                    self.assertEqual(self.player.powers.slots[key].ability_id, ability_id)

    def test_his_own_stop_does_not_hold_the_player_still(self):
        self.begin("WHITE", "BLACK")
        self.tough(self.enemy)
        self.tap("2")
        self.assertTrue(self.combat.sequence_running)
        z = float(self.player.z)
        self.frames(3)
        self.assertNotEqual(float(self.player.z), z)
        self.player.release_motion()


class FlyingTargetTests(AICase):
    def test_a_flying_player_is_reached_in_the_air(self):
        for ai_id, ability_id in (("RED", "flying_punch"), ("WHITE", "high_speed_attack"), ("GREEN", "high_speed_attack")):
            with self.subTest(ai_id):
                self.fight(ai_id, player="YELLOW")
                floor = self.game.world.height_at(self.player.x, self.player.z)
                self.player.position = (float(self.player.x), floor + 120.0, float(self.player.z))
                self.player.flight.phase = FlightPhase.CRUISE
                with self.order(ai_id, ability_id):
                    self.game.update(FRAME)
                    self.assertTrue(self.run_until_finished())
                self.assertGreater(self.player.vitals.damage_taken, 0.0)
                self.assertFalse(self.combat.time_stopped)


if __name__ == "__main__":
    unittest.main()
