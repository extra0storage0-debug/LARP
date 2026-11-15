"""Soldier Boy's keys 1 to 4 and T, on the real game loop with real key input."""

from __future__ import annotations

import unittest
from unittest import mock

from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from config.power_schema import ABILITIES, SCHEMA, SLOT_ABILITIES
from game import controls
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import fresh_tree
from powers.chest_beam import RadioactiveChestBeam
from powers.common import LaunchedMotion
from powers.soldier_boy_attacks import (AFTERMATH, AerialGrabBlast, BEAM, DESCEND, GRIP, FlyingPunch, JUMP, LIFT,
                                        APPROACH, PUNCH, REGRAB, RadioactiveExecution, SLAM)
from powers.universal import MAX_LAUNCH_SPEED
from powers.vitals import EXPLOSION, PHYSICAL, RADIATION
from test_gameplay_control_update import LiveCase

SEQUENCES = {"3": AerialGrabBlast, "4": RadioactiveExecution}  # his leaps; Key 2 is in test_power_control
IDS = {"3": "aerial_grab_blast", "4": "radioactive_execution"}
OTHERS = ("WHITE", "BLACK", "YELLOW", "GREEN")


class SoldierBoyCase(LiveCase):
    def start(self, distance: float = 60.0, enemy: str = "BLACK", flying_at: float | None = None):
        self.begin("RED", enemy, distance)
        self.tough(self.enemy)
        self.tough(self.player)
        if flying_at is not None:
            floor = self.game.world.height_at(self.enemy.x, self.enemy.z)
            self.enemy.position = (float(self.enemy.x), floor + flying_at, float(self.enemy.z))
            self.enemy.flight.phase = FlightPhase.CRUISE
        self.frames(1)

    def run_sequence(self, key: str, limit: float = 30.0) -> list:
        """Press the key, then watch the whole thing. His flight state is checked on every frame."""
        self.game.input(key)
        self.game.input(f"{key} up")
        phases = []
        for _ in range(round(limit / FRAME)):
            motion = self.player.motion
            if motion is None:
                return phases
            if not phases or phases[-1] != motion.phase:
                phases.append(motion.phase)
            self.assertTrue(self.combat.time_stopped, "the world stays stopped for all of it")
            self.game.update(FRAME)
            self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED, "he jumps; he never flies")
            self.assertEqual(self.player.flight.velocity.length(), 0.0)
        self.fail(f"key {key} never finished: {phases}")

    def assert_falls_to_the_ground(self) -> None:
        """Thrown, it comes down by itself and really lands, however high it was."""
        thrown = self.enemy.motion
        self.assertIsInstance(thrown, LaunchedMotion)
        self.run_until_settled(self.enemy, 70.0)
        self.assertTrue(thrown.landed)

    def assert_handed_back(self) -> None:
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(self.game.hud.vision_overlay.enabled)
        self.assertEqual(len(self.combat._beams), self.beams_free, "every borrowed visual handed back")
        self.assertEqual(self.player.knock.length(), 0.0)


class KeyTests(SoldierBoyCase):
    def test_the_keys_are_exactly_the_specification(self):
        self.assertEqual(SLOT_ABILITIES["RED"], {"1": "radiation_blast", "2": "flying_punch",
                                                 "3": "aerial_grab_blast", "4": "radioactive_execution"})
        self.start()
        slots = {key: ability.ability_id for key, ability in self.player.powers.slots.items()}
        self.assertEqual(slots, {"1": "radiation_blast", "2": "flying_punch", "3": "aerial_grab_blast",
                                 "4": "radioactive_execution", "t": "world_stop"})
        self.assertEqual([card.binding for card in SCHEMA["RED"]], ["1", "2", "3", "4"])
        self.assertEqual(self.game.hud.slots["2"].name.text != "", True)
        self.assertIn("t", self.game.hud.slots)

    def test_no_new_key_mapping_was_added(self):
        self.assertEqual(set(controls.ABILITY_SLOTS), {"1", "2", "3", "4", "t", "+", "=", "-", "_"})
        self.assertNotIn("e", controls.ABILITY_SLOTS)
        self.assertNotIn("r", controls.ABILITY_SLOTS)

    def test_e_r_the_mouse_and_punch_keys_do_nothing_for_him(self):
        self.start(distance=6.0)
        for key in ("e", "r", "left mouse down", "right mouse down", "=", "-"):
            self.tap(key)
            self.frames(2)
            self.assertIsNone(self.player.motion, key)
            self.assertEqual(self.enemy.vitals.damage_taken, 0.0, key)

    def test_t_is_the_ordinary_thirty_second_stop_and_he_moves_in_it(self):
        self.start()
        self.tap("t")
        self.assertTrue(self.combat.world_stopped)
        self.assertAlmostEqual(self.combat.world_stop_left, 30.0, delta=.1)
        self.combat.world_stop_left = FRAME * .5
        self.frames(2)
        self.assertFalse(self.combat.time_stopped)

    def test_his_values_are_all_editable_and_nobody_else_was_touched(self):
        for ability_id in IDS.values():
            for key in ("range", "damage", "speed"):
                self.assertIsNotNone(ABILITIES["RED"][ability_id].param(key))
        self.assertEqual(SLOT_ABILITIES["YELLOW"]["4"], "void_nuclear_execution")
        self.assertEqual(SLOT_ABILITIES["WHITE"]["2"], "high_speed_attack")
        self.assertEqual(SLOT_ABILITIES["GREEN"]["3"], "time_stop")
        self.start()
        for character_id in OTHERS:
            abilities = self.teams.characters[character_id].powers.abilities
            for ability_id in IDS.values():
                self.assertNotIn(ability_id, abilities, character_id)

    def test_no_enemy_means_no_stop(self):
        self.start()
        self.teams.state.assignment["BLACK"] = AVAILABLE
        self.teams._apply_roster()
        for key in SEQUENCES:
            self.tap(key)
            self.assertIsNone(self.player.motion)
            self.assertFalse(self.combat.time_stopped)


class KeyOneTests(SoldierBoyCase):
    def test_green_from_the_chest_with_real_damage_and_standing_still(self):
        self.start(distance=40.0)
        here = (float(self.player.x), float(self.player.y), float(self.player.z))
        beam = self.player.powers.abilities["chest_beam"]
        beam.press()  # no key of its own now
        self.assertIsInstance(beam, RadioactiveChestBeam)
        self.seconds(3.0)
        self.assertTrue(beam.active, "stays on until switched off")
        self.assertEqual((float(self.player.x), float(self.player.y), float(self.player.z)), here)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        glow = beam.visual.glows[0].color
        self.assertGreater(glow[1], glow[0])
        self.assertGreater(float(beam.visual.cores[0].y), here[1])
        beam.press()
        self.assertFalse(beam.active)

    def test_a_sequence_leaves_the_beam_on_if_it_was_on(self):
        self.start(distance=40.0)
        beam = self.player.powers.abilities["chest_beam"]
        beam.press()  # no key of its own now
        self.frames(5)
        self.run_sequence("3")
        self.assertTrue(beam.active, "only the player switches it off")
        self.assert_handed_back_with_beam(beam)
        beam.press()
        self.assertFalse(beam.active)

    def assert_handed_back_with_beam(self, beam) -> None:
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)
        self.frames(2)
        self.assertIsNotNone(beam.visual)




class KeyThreeTests(SoldierBoyCase):
    def test_grab_face_punch_blast_and_throw(self):
        self.start()
        self.combat.settings.set("RED", "aerial_grab_blast", "damage", 2000)
        self.enemy.vitals.resistance = 0.0
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast, \
                mock.patch.object(self.combat, "hit_character", wraps=self.combat.hit_character) as hit:
            phases = self.run_sequence("3")
        self.assertEqual(phases, [JUMP, APPROACH, GRIP, LIFT, PUNCH, DESCEND, AFTERMATH])
        self.assertEqual(blast.call_count, 1, "one explosion")
        self.assertEqual(blast.call_args.kwargs["kind"], EXPLOSION)
        self.assertGreaterEqual(blast.call_args.args[2], 200.0, "massive at the default Range")
        punch = hit.call_args_list[0].args
        self.assertEqual((punch[1], punch[3]), (self.enemy, PHYSICAL))
        self.assertGreater(self.enemy.vitals.damage_taken, 2000.0 * 1.35 * .5)
        self.assert_handed_back()
        self.assert_falls_to_the_ground()

    def test_the_explosion_is_at_the_face_and_breaks_the_world_around_it(self):
        self.start()
        tree = fresh_tree(self.game, minimum=8.0)
        self.stand(self.enemy, tree.x + 20.0, tree.z)
        self.stand(self.player, tree.x + 20.0, tree.z - 60.0)
        tree_id = tree.tree_id
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            self.run_sequence("3")
        point = blast.call_args.args[1]
        self.assertGreater(point.y - self.game.world.height_at(point.x, point.z), 25.0, "up in the air")
        state = self.game.world.tree_states.get(tree_id, {})
        self.assertTrue(state.get("destroyed") or tree.is_empty() or tree.tree_health < tree.tree_max_health)

    def test_range_sets_its_size(self):
        self.start()
        self.combat.settings.set("RED", "aerial_grab_blast", "range", 200)
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            self.run_sequence("3")
        self.assertAlmostEqual(blast.call_args.args[2], 20.0, delta=.1)

    def test_it_grabs_a_flying_enemy_up_there(self):
        self.start(flying_at=150.0)
        self.run_sequence("3")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assert_handed_back()
        self.assert_falls_to_the_ground()


class KeyFourTests(SoldierBoyCase):
    def test_all_five_phases_in_order_with_real_damage_of_each_kind(self):
        self.start()
        self.combat.settings.set("RED", "radioactive_execution", "damage", 2000)
        self.enemy.vitals.resistance = 0.0
        with mock.patch.object(self.combat, "hit_character", wraps=self.combat.hit_character) as hit, \
                mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            phases = self.run_sequence("4")
        self.assertEqual(phases, [JUMP, APPROACH, GRIP, LIFT, SLAM, REGRAB, LIFT, SLAM, REGRAB, LIFT, PUNCH, "position",
                                  "catch", BEAM, "thrown_down", DESCEND, AFTERMATH])
        self.assertEqual(blast.call_count, 5, "two slams, two nuclear spheres and the last landing")
        kinds = {call.args[3] for call in hit.call_args_list if len(call.args) > 3 and call.args[1] is self.enemy}
        self.assertLessEqual({PHYSICAL, RADIATION}, kinds)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)

    def test_two_craters_and_he_is_grabbed_again_after_each(self):
        self.start()
        craters = len(self.game.world.terrain_impacts)
        self.game.input("4")
        self.game.input("4 up")
        seen_on_ground = 0
        was = None
        while self.player.motion is not None:
            motion = self.player.motion
            if motion.phase == REGRAB and was != REGRAB:
                seen_on_ground += 1
                self.assertTrue(self.on_ground(self.enemy) or float(self.enemy.y) >= float(self.player.y))
            was = motion.phase
            self.game.update(FRAME)
        self.assertEqual(seen_on_ground, 2)
        self.assertGreaterEqual(len(self.game.world.terrain_impacts) - craters, 2)

    def test_the_beam_is_his_own_green_one_from_the_chest_and_the_fire_is_green(self):
        self.start()
        self.game.input("4")
        self.game.input("4 up")
        while self.player.motion.phase != BEAM:
            self.game.update(FRAME)
        self.frames(30)
        motion = self.player.motion
        chest_beam = self.player.powers.abilities["chest_beam"]
        self.assertFalse(chest_beam.active, "the sequence draws it; key 1 has not been switched on")
        self.assertIsNotNone(motion.visual)
        self.assertEqual(motion.visual.flare.color, RadioactiveChestBeam.FLARE)
        self.assertEqual(motion.visual.cores[0].color, RadioactiveChestBeam.CORE)
        self.assertFalse(motion.visual.cores[1].visible, "one beam, not two eyes")
        self.assertGreater(float(motion.visual.cores[0].y), float(self.player.y) + 1.0)
        flames = self.player.powers.abilities["radioactive_execution"].flames.entity
        self.assertTrue(flames.visible)
        self.assertGreater(flames.color[1], flames.color[0])
        self.assertLess((SimVec3(*flames.position) - SimVec3(self.enemy.x, self.enemy.y, self.enemy.z)).length(), 3.0)
        while self.player.motion is not None:
            self.game.update(FRAME)
        self.assertFalse(flames.visible, "out when it ends")
        self.assert_handed_back()

    def test_it_pursues_a_flying_enemy_and_still_slams_it_twice(self):
        self.start(flying_at=150.0)
        phases = self.run_sequence("4")
        self.assertEqual(phases.count(SLAM), 2)
        self.assert_handed_back()

    def test_the_slams_damage_the_world_nearby(self):
        self.start()
        tree = fresh_tree(self.game, minimum=8.0)
        self.stand(self.enemy, tree.x + 8.0, tree.z)
        self.stand(self.player, tree.x + 8.0, tree.z - 40.0)
        before = tree.tree_health
        self.run_sequence("4")
        self.assertTrue(tree.is_empty() or tree.tree_health < before)


class TimeStopRuleTests(SoldierBoyCase):
    def test_the_rest_of_the_world_stands_still_and_then_carries_on(self):
        for key in SEQUENCES:
            with self.subTest(key):
                self.begin("RED", "BLACK", 60.0, ai_powers=True)
                self.tough(self.enemy)
                other = self.teams.characters["GREEN"]
                self.teams.state.assignment["GREEN"] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(other, 80.0, 80.0)
                self.tough(other)
                self.teams._next_cinematic = 1e9  # this one is about his stop, not theirs
                self.frames(30)
                sky = self.game.environment._time
                self.game.input(key)
                self.game.input(f"{key} up")
                if self.player.motion.target is other:  # whichever of the two it did not pick
                    other = self.enemy
                where = (float(other.x), float(other.y), float(other.z))
                while self.player.motion is not None:
                    self.game.update(FRAME)
                    if self.player.motion is not None:  # on its last frame time has already resumed
                        self.assertEqual((float(other.x), float(other.y), float(other.z)), where)
                        self.assertEqual(self.game.environment._time, sky)
                self.assertFalse(self.combat.time_stopped)
                self.seconds(1.0)
                self.assertGreater(self.game.environment._time, sky, "time runs again")

    def test_a_manual_lock_comes_before_the_nearest(self):
        for key in SEQUENCES:
            with self.subTest(key):
                self.start(distance=90.0)
                near = self.teams.characters["GREEN"]
                self.teams.state.assignment["GREEN"] = ENEMY_TEAM
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

    def test_the_nearest_is_chosen_without_a_lock(self):
        for key in SEQUENCES:
            with self.subTest(key):
                self.start(distance=90.0)
                near = self.teams.characters["GREEN"]
                self.teams.state.assignment["GREEN"] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(near, 10.0, 0.0)
                self.tough(near)
                self.combat.targets.clear()
                self.frames(1)
                self.game.input(key)
                self.game.input(f"{key} up")
                self.assertIs(self.player.motion.target, near)
                self.player.release_motion()

    def test_keys_cannot_start_a_second_one_or_interrupt_it(self):
        for key in SEQUENCES:
            with self.subTest(key):
                self.start()
                self.game.input(key)
                self.game.input(f"{key} up")
                motion = self.player.motion
                for other in ("1", "2", "3", "4", "t", "q", "="):
                    self.tap(other)
                    self.assertIs(self.player.motion, motion, other)
                self.assertFalse(self.combat.world_stopped)
                self.assertFalse(self.player.powers.abilities["chest_beam"].active)
                self.player.release_motion()
                self.assert_handed_back()

    def test_a_target_dying_at_any_point_never_leaves_the_world_stopped(self):
        for key in SEQUENCES:
            for frames_in in (2, 20, 40, 70, 110, 160, 220):
                with self.subTest(key, frames_in=frames_in):
                    self.start()
                    self.game.input(key)
                    self.game.input(f"{key} up")
                    self.frames(frames_in)
                    self.enemy.vitals.take(1e12)
                    if self.enemy.vitals.downed:
                        self.enemy.on_downed()
                    self.seconds(8.0)
                    self.assert_handed_back()
                    self.assertLess(float(self.player.y) - self.game.world.height_at(self.player.x, self.player.z),
                                    1.0)
                    self.enemy.vitals.downed_for = 0.0
                    self.enemy.vitals.health = self.enemy.vitals.max_health

    def test_a_target_despawning_part_way_never_leaves_the_world_stopped(self):
        for key in SEQUENCES:
            with self.subTest(key):
                self.start()
                self.game.input(key)
                self.game.input(f"{key} up")
                self.frames(25)
                self.teams.state.assignment["BLACK"] = AVAILABLE
                self.teams._apply_roster()
                self.seconds(8.0)
                self.assert_handed_back()

    def test_switching_character_part_way_hands_everything_back(self):
        for key in SEQUENCES:
            with self.subTest(key):
                self.start()
                self.game.input(key)
                self.game.input(f"{key} up")
                self.frames(25)
                red = self.player
                self.teams.state.assignment["WHITE"] = MY_TEAM
                self.teams.swap("WHITE", save=False)
                self.assertIsNone(red.motion)
                self.assertFalse(self.combat.time_stopped)
                self.assertEqual(len(self.combat._beams), self.beams_free)
                self.seconds(8.0)
                self.assertLess(float(red.y) - self.game.world.height_at(red.x, red.z), 1.0, "and he comes down")
                self.teams.swap("RED", save=False)

    def test_a_low_speed_setting_times_out_rather_than_stopping_the_world_forever(self):
        for key, ability_id in IDS.items():
            with self.subTest(key):
                self.start(distance=2000.0)
                self.combat.settings.set("RED", ability_id, "speed", 1)
                self.game.input(key)
                self.game.input(f"{key} up")
                self.player.motion.time_limit = 1.0
                self.seconds(60.0)
                self.assert_handed_back()

    def test_he_can_be_nullified_out_of_starting_one(self):
        self.start()
        self.player.vitals.add_status("nullified", 30.0)
        for key in SEQUENCES:
            self.tap(key)
            self.assertIsNone(self.player.motion)
            self.assertFalse(self.combat.time_stopped)

    def test_allies_are_never_touched(self):
        self.start()
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams._apply_roster()
        self.stand(ally, 3.0, 62.0)
        for key in SEQUENCES:
            self.run_sequence(key)
            self.assertEqual(ally.vitals.damage_taken, 0.0, key)
            self.seconds(3.0)


class StillNoFlightTests(SoldierBoyCase):
    def test_he_cannot_fly_afterwards_and_walks_as_normal(self):
        for key in SEQUENCES:
            with self.subTest(key):
                self.start()
                self.run_sequence(key)
                self.assertFalse(self.player.flight_allowed)
                self.game.input("f")
                self.frames(5)
                self.assertFalse(self.player.flight.is_flying, "F is his jump, which is not flight")

class BudgetTests(SoldierBoyCase):
    def test_repeated_use_adds_no_entities_and_keeps_the_pools_whole(self):
        self.start()
        puffs = self.combat.puffs
        total = len(puffs.free) + len(puffs.live)
        self.run_sequence("3")
        self.seconds(5.0)
        world = self.game.world
        explosions = len(world._active_explosions) + len(world._explosion_pool)
        largest = 0
        for _ in range(3):
            for key in SEQUENCES:
                self.game.input(key)
                self.game.input(f"{key} up")
                while self.player.motion is not None:
                    self.game.update(FRAME)
                    largest = max(largest, len(puffs.live))
                self.assertEqual(len(self.combat._beams), self.beams_free)
                self.enemy.vitals.health = self.enemy.vitals.max_health
                self.seconds(5.0)
                self.enemy.release_motion()
                self.stand(self.enemy, float(self.player.x), float(self.player.z) + 60.0)
        self.seconds(15.0)  # the biggest of them leave the most falling behind
        self.assertEqual(len(puffs.free) + len(puffs.live), total)
        self.assertLessEqual(largest, total)
        self.assertLessEqual(len(self.game.world.debris), self.game.world.debris_budget.maximum_live_pieces)
        self.assertLessEqual(len(world._active_explosions) + len(world._explosion_pool),
                             max(explosions, world.MAX_ACTIVE_EXPLOSIONS))
        self.assertEqual(len(world.effects), 0, "every effect has finished")

    def test_a_maximum_launch_stays_within_the_limit(self):
        self.start()
        self.game.input("2")
        self.game.input("2 up")
        while not isinstance(self.enemy.motion, LaunchedMotion):
            self.game.update(FRAME)
        self.assertLessEqual(self.enemy.motion.velocity.length(), MAX_LAUNCH_SPEED + 1.0)
        while self.player.motion is not None:
            self.game.update(FRAME)


if __name__ == "__main__":
    unittest.main()
