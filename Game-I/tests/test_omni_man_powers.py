"""Omni-Man's keys 1 to 4 on the real game loop: his squad, and the strikes that stop the world."""

from __future__ import annotations

import unittest
from unittest import mock

from characters.roster import KITS
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from config.power_schema import SCHEMA, SLOT_ABILITIES
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import fresh_tree
from powers.common import LaunchedMotion
from powers.omni_man import ShockwaveStrike
from powers.universal import NuclearExecution, StrikeAndBreakAway
from powers.vitals import EXPLOSION, PHYSICAL
from test_gameplay_control_update import LiveCase


class OmniCase(LiveCase):
    def start(self, distance: float = 60.0, enemy: str = "BLACK"):
        self.begin("GREEN", enemy, distance)
        self.tough(self.enemy)
        self.tough(self.player)
        self.frames(1)
        self.squad = self.player.powers.abilities["squad_summon"]

    def run_sequence(self, key: str, limit: float = 30.0) -> None:
        self.game.input(key)
        self.game.input(f"{key} up")
        for _ in range(round(limit / FRAME)):
            if self.player.motion is None:
                return
            self.assertTrue(self.combat.time_stopped)
            self.game.update(FRAME)
        self.fail(f"key {key} never finished")

    def assert_handed_back(self) -> None:
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(self.game.hud.vision_overlay.enabled)
        self.assertEqual(len(self.combat._beams), self.beams_free)


class KeyTests(OmniCase):
    def test_the_keys_are_the_specification_and_nobody_elses_changed(self):
        self.assertEqual(SLOT_ABILITIES["GREEN"], {"1": "squad_summon", "2": "high_speed_attack", "3": "time_stop",
                                                   "4": "speed_execution"})
        self.assertEqual(SLOT_ABILITIES["WHITE"]["1"], "heat_vision")
        self.assertEqual(SLOT_ABILITIES["BLACK"]["4"], "neck_laser_execution")
        self.assertEqual(SLOT_ABILITIES["YELLOW"]["4"], "void_nuclear_execution")
        self.assertEqual(SLOT_ABILITIES["RED"]["1"], "radiation_blast")
        self.start()
        slots = self.player.powers.slots
        for key, ability_id in SLOT_ABILITIES["GREEN"].items():
            self.assertEqual(slots[key].ability_id, ability_id)
        self.assertEqual(slots["+"].ability_id, "melee", "punch and kick are kept")
        self.assertEqual(slots["-"].ability_id, "melee")
        self.assertEqual(slots["t"].ability_id, "world_stop")
        self.assertEqual({card.ability_id for card in SCHEMA["GREEN"]},
                         {"squad_summon", "high_speed_attack", "time_stop", "speed_execution", "melee"})

    def test_he_is_given_no_beam_of_any_kind(self):
        self.start()
        for ability_id in ("chest_beam", "heat_vision", "laser_vision"):
            self.assertNotIn(ability_id, self.player.powers.abilities)

    def test_nobody_else_is_given_his_powers(self):
        self.start()
        for character_id in ("WHITE", "BLACK", "YELLOW", "RED"):
            abilities = self.teams.characters[character_id].powers.abilities
            self.assertNotIn("squad_summon", abilities)
            self.assertNotIn("speed_execution", abilities)
            self.assertNotIsInstance(abilities.get("high_speed_attack"), type(self.player.powers.slots["2"]))


class SquadTests(OmniCase):
    def test_exactly_five_viltrumites_and_invincible_near_him_on_his_side(self):
        self.start()
        self.tap("1")
        members = self.squad.members
        self.assertEqual(len(members), 6)
        self.assertEqual(sum(member.display_name == "INVINCIBLE" for member in members), 1)
        self.assertEqual(sum(member.display_name != "INVINCIBLE" for member in members), 5)
        self.assertEqual(len({id(member) for member in members}), 6)
        self.assertTrue(self.squad.active)
        for member in members:
            self.assertFalse(member.parked)
            distance = ((float(member.x) - float(self.player.x)) ** 2
                        + (float(member.z) - float(self.player.z)) ** 2) ** .5
            self.assertLess(distance, 15.0)
            self.assertFalse(self.combat.hostile(member, self.player))
            self.assertTrue(self.combat.hostile(member, self.enemy))
            for other in members:
                self.assertFalse(self.combat.hostile(member, other))

    def test_invincible_and_each_viltrumite_look_different(self):
        self.start()
        self.tap("1")
        looks = {member.kit.parts for member in self.squad.members}
        self.assertEqual(len(looks), 6, "six distinct people")
        invincible = next(member for member in self.squad.members if member.display_name == "INVINCIBLE")
        self.assertFalse(invincible.kit.cape)
        self.assertNotEqual(invincible.palette.suit_light, KITS["GREEN"].parts)

    def test_pressing_again_dismisses_them_and_there_is_never_a_second_squad(self):
        self.start()
        self.tap("1")
        first = list(self.squad.members)
        self.tap("1")
        self.assertFalse(self.squad.active)
        self.assertEqual(self.teams.summons, [])
        self.assertTrue(all(member.parked for member in first))
        for _ in range(5):
            self.tap("1")
            self.assertEqual(len(self.teams.summons), 6)
            self.assertEqual({id(member) for member in self.teams.summons}, {id(member) for member in first},
                             "the same six bodies")
            self.tap("1")
            self.assertEqual(self.teams.summons, [])

    def test_they_never_become_roster_characters(self):
        self.start()
        self.tap("1")
        self.assertEqual(len(self.teams.characters), 5)
        session_keys = set(self.teams.characters)
        self.teams.save_session()
        self.assertEqual(set(self.teams.state.session), session_keys, "and they are never saved")

    def test_all_six_go_after_the_enemy_and_attack_it(self):
        self.start(distance=70.0)
        self.tap("1")
        members = list(self.squad.members)
        attacks = {id(member): 0 for member in members}
        real_presses = []
        for member in members:
            for ability in member.powers.abilities.values():
                press = ability.press

                def counted(press=press, member=member):
                    attacks[id(member)] += 1
                    return press()
                real_presses.append((ability, press))
                ability.press = counted
                if ability.ability_id == "melee":
                    kick = ability.kick

                    def kicked(kick=kick, member=member):
                        attacks[id(member)] += 1
                        return kick()
                    ability.kick = kicked
        friendly_fire = []
        real_hit = self.combat.hit_character

        def spy(source, target, *args, **kwargs):
            dealt = real_hit(source, target, *args, **kwargs)
            if source in members and (target in members or target is self.player) and dealt > 0.0:
                friendly_fire.append((source, target))
            return dealt

        with mock.patch.object(self.combat, "hit_character", spy):
            self.seconds(25.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertEqual(self.player.vitals.damage_taken, 0.0, "never Omni-Man")
        self.assertEqual(friendly_fire, [], "nor each other")
        for member in members:
            self.assertGreater(attacks[id(member)], 0, member.display_name)
        for ability, _press in real_presses:
            ability.__dict__.pop("press", None)
            ability.__dict__.pop("kick", None)

    def test_they_fly_to_an_enemy_in_the_air(self):
        self.start(distance=80.0)
        floor = self.game.world.height_at(self.enemy.x, self.enemy.z)
        self.enemy.position = (float(self.enemy.x), floor + 120.0, float(self.enemy.z))
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.enemy.vitals.add_status("frozen", 600.0)
        self.tap("1")
        self.seconds(8.0)
        self.assertTrue(any(member.flight.is_flying for member in self.squad.members))
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)

    def test_a_fallen_member_leaves_and_the_rest_fight_on_and_the_hud_says_so(self):
        self.start()
        self.tap("1")
        fallen = self.squad.members[0]
        fallen.vitals.take(1e12)
        fallen.on_downed()
        self.seconds(3.5)
        self.assertEqual(len(self.squad.members), 5)
        self.assertTrue(fallen.parked)
        self.assertTrue(self.squad.active)
        self.assertEqual(self.squad.hud_state(), "5/6")
        self.assertIn("SQUAD 5/6", self.squad.status_line())
        self.assertIn("INVINCIBLE", self.squad.status_line())
        for member in list(self.squad.members):
            member.vitals.take(1e12)
            member.on_downed()
        self.seconds(3.5)
        self.assertTrue(self.squad.active, "still on: they are due back next cycle")
        self.assertEqual(self.teams.summons, [])
        self.tap("1")
        self.tap("1")
        self.assertEqual(len(self.teams.summons), 6, "he can call them again, all back on their feet")
        self.assertTrue(all(not member.vitals.downed for member in self.teams.summons))

    def test_switching_away_keeps_them_and_he_leaving_the_world_ends_them(self):
        self.start()
        self.tap("1")
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams.swap("WHITE", save=False)
        self.assertEqual(len(self.teams.summons), 6)
        self.assertTrue(self.squad.active)
        self.frames(30)
        self.teams.swap("GREEN", save=False)
        self.teams.swap("WHITE", save=False)
        self.teams.state.assignment["GREEN"] = AVAILABLE
        self.teams._apply_roster()
        self.assertEqual(self.teams.summons, [])
        self.assertFalse(self.squad.active)

    def test_they_stand_frozen_in_a_time_stop_with_everyone_else(self):
        self.start()
        self.tap("1")
        self.seconds(1.0)
        self.tap("t")
        where = [(float(member.x), float(member.y), float(member.z)) for member in self.squad.members]
        self.seconds(1.0)
        self.assertEqual(where, [(float(member.x), float(member.y), float(member.z)) for member in self.squad.members])
        self.combat.end_world_stop()

    def test_they_do_not_change_the_target_lock_for_him(self):
        self.start(distance=40.0)
        self.tap("1")
        self.game.input("q")
        self.assertIs(self.combat.targets.manual, self.enemy, "the nearest enemy, not an ally beside him")
        self.game.input("q")

    def test_enemy_omni_mans_squad_really_are_enemies(self):
        self.begin("WHITE", "GREEN", 60.0, ai_powers=False)
        self.tough(self.player)
        omni = self.enemy
        omni.powers.abilities["squad_summon"].press()
        members = omni.powers.abilities["squad_summon"].members
        self.assertEqual(len(members), 6)
        for member in members:
            self.assertTrue(self.combat.hostile(member, self.player))
        self.assertIn(members[0], self.combat.hostiles_of(self.player))
        self.seconds(12.0)
        self.assertGreater(self.player.vitals.damage_taken, 0.0)

    def test_the_lock_can_be_put_on_an_enemy_squad_member(self):
        self.begin("WHITE", "GREEN", 60.0, ai_powers=False)
        self.enemy.powers.abilities["squad_summon"].press()
        self.frames(1)
        self.game.input("q")
        seen = set()
        for _ in range(12):
            seen.add(id(self.combat.targets.manual))
            self.game.input("scroll up")
        self.assertTrue(seen & {id(member) for member in self.teams.summons})
        self.game.input("q")

    def test_a_beam_kills_one_of_an_enemy_squad_without_any_trouble(self):
        self.begin("WHITE", "GREEN", 60.0, ai_powers=False)
        ability = self.enemy.powers.abilities["squad_summon"]
        ability.press()
        self.combat.hit_character(self.player, ability.members[0], 1e12, PHYSICAL)
        self.seconds(4.0)
        self.assertEqual(len(ability.members), 5)


class KeyTwoTests(OmniCase):
    def test_it_is_the_universal_strike_with_a_shockwave_that_does_real_damage(self):
        self.start(enemy="BLACK")
        self.assertIs(type(self.player.powers.slots["2"].strike), type(ShockwaveStrike))
        self.assertTrue(issubclass(ShockwaveStrike, StrikeAndBreakAway))
        bystander = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(bystander, 3.0, 60.0)
        self.tough(bystander)
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            self.game.input("2")
            self.assertTrue(self.combat.time_stopped, "at once")
            self.assertIsInstance(self.player.motion, ShockwaveStrike)
            self.game.input("2 up")
            self.run_sequence("2")
        self.assertEqual(blast.call_count, 1)
        self.assertEqual(blast.call_args.kwargs["kind"], EXPLOSION)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertGreater(bystander.vitals.damage_taken, 0.0, "the shockwave itself hurts")
        self.assertIsInstance(self.enemy.motion, LaunchedMotion)
        self.assert_handed_back()

    def test_the_shockwave_breaks_the_world_too(self):
        self.start()
        tree = fresh_tree(self.game, minimum=8.0)
        self.stand(self.enemy, tree.x + 6.0, tree.z)
        self.stand(self.player, tree.x + 6.0, tree.z - 60.0)
        before = tree.tree_health
        self.run_sequence("2")
        self.assertTrue(tree.is_empty() or tree.tree_health < before)

    def test_he_carries_on_past_them(self):
        self.start()
        self.run_sequence("2")
        self.assertGreater(float(self.player.z), 60.0, "beyond where the enemy stood")


class KeyThreeTests(OmniCase):
    def test_the_universal_execution_is_kept_as_it_was(self):
        self.start()
        self.game.input("3")
        self.game.input("3 up")
        self.assertIs(type(self.player.motion), NuclearExecution)
        self.run_sequence("3")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assert_handed_back()


class RuleTests(OmniCase):
    def test_a_manual_lock_comes_first_for_all_three(self):
        for key in ("2", "3", "4"):
            with self.subTest(key):
                self.start(distance=90.0)
                near = self.teams.characters["WHITE"]
                self.teams.state.assignment["WHITE"] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(near, 10.0, 0.0)
                self.tough(near)
                self.frames(1)
                self.game.input("q")
                while self.combat.targets.manual is not self.enemy:
                    self.game.input("scroll up")
                self.game.input(key)
                self.game.input(f"{key} up")
                self.assertIs(self.player.motion.target, self.enemy)
                self.player.release_motion()
                self.game.input("q")

    def test_keys_cannot_start_a_second_one(self):
        for key in ("2", "3", "4"):
            with self.subTest(key):
                self.start()
                self.game.input(key)
                self.game.input(f"{key} up")
                motion = self.player.motion
                for other in ("1", "2", "3", "4", "t", "q", "="):
                    self.tap(other)
                    self.assertIs(self.player.motion, motion, other)
                self.assertFalse(self.squad.active, "nothing is summoned in the middle of one")
                self.player.release_motion()
                self.assert_handed_back()

    def test_the_target_going_away_never_leaves_the_world_stopped(self):
        for key in ("2",):
            for frames_in in (1, 5, 15):
                with self.subTest(key, frames_in=frames_in):
                    self.start(distance=200.0)
                    self.game.input(key)
                    self.game.input(f"{key} up")
                    self.frames(frames_in)
                    if self.player.motion is not None:
                        self.teams.state.assignment["BLACK"] = AVAILABLE
                        self.teams._apply_roster()
                    self.seconds(4.0)
                    self.assert_handed_back()

    def test_the_world_is_held_still_and_then_carries_on(self):
        for key in ("2", "4"):
            with self.subTest(key):
                self.begin("GREEN", "BLACK", 60.0, ai_powers=True)
                self.tough(self.enemy)
                self.tough(self.player)
                other = self.teams.characters["WHITE"]
                self.teams.state.assignment["WHITE"] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(other, 200.0, 200.0)
                self.tough(other)
                self.teams._next_cinematic = 1e9  # this one is about his stop, not theirs
                self.frames(30)
                sky = self.game.environment._time
                self.game.input(key)
                self.game.input(f"{key} up")
                bystander = other if self.player.motion.target is not other else self.enemy
                where = (float(bystander.x), float(bystander.y), float(bystander.z))
                while self.player.motion is not None:
                    self.game.update(FRAME)
                    if self.player.motion is not None:
                        self.assertEqual((float(bystander.x), float(bystander.y), float(bystander.z)), where)
                        self.assertEqual(self.game.environment._time, sky)
                self.seconds(1.0)
                self.assertGreater(self.game.environment._time, sky)


class BudgetTests(OmniCase):
    def test_a_long_fight_stays_within_its_limits(self):
        self.start()
        puffs = self.combat.puffs
        total = len(puffs.free) + len(puffs.live)
        self.tap("1")
        self.frames(5)
        bodies = {id(member) for member in self.teams.summons}
        for _ in range(6):
            self.seconds(5.0)
            self.tap("1")
            self.frames(2)
            self.tap("1")
            self.assertEqual({id(member) for member in self.teams.summons}, bodies)
        self.assertLessEqual(len(self.game.world.debris), self.game.world.debris_budget.maximum_live_pieces)
        self.assertEqual(len(puffs.free) + len(puffs.live), total)
        self.assertEqual(len(self.combat._beams), self.beams_free)
        self.assertEqual(len(self.teams._squad), 6)


if __name__ == "__main__":
    unittest.main()
