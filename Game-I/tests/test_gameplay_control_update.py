"""Homelander's 4, the punch on 2, R doing nothing and the 30-second Time Stop on T.

These run the real game loop with real AI updates, unlike PowerCase, which holds AI still: a thrown
body and a frozen world are both things that loop does.
"""

from __future__ import annotations

import unittest
from unittest import mock

from ursina import held_keys

from characters.roster import ROSTER_IDS
from config.character_roster import AVAILABLE, ENEMY_TEAM, MY_TEAM
from config.power_schema import SCHEMA, SLOT_ABILITIES
from game import controls
from game_fixture import FRAME, reset_game, run_frames
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import fresh_tree
from powers.aiming import center_of
from powers.common import LaunchedMotion, launch_character
from powers.homelander import LASER_SECONDS, LASER_SHARE, LASER, LIFT, NeckLaserExecution
from powers.universal import (AFTERMATH, CARRY, GRIP, MAX_CARRY_SPEED, MAX_LAUNCH_SPEED, PUNCH, PUNCH_STYLES,
                              RUSH, NuclearExecution, StrikeAndBreakAway)

FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")


class LiveCase(unittest.TestCase):
    def begin(self, player: str, enemy: str = "RED", distance: float = 60.0, ai_powers: bool = False):
        self.game = game = reset_game(ai_powers=ai_powers)
        self.teams, self.combat = game.teams, game.combat
        for character_id in ROSTER_IDS:
            self.teams.state.assignment[character_id] = AVAILABLE
        self.teams.state.assignment[player] = MY_TEAM
        self.teams.swap(player, save=False)
        self.teams.state.assignment[enemy] = ENEMY_TEAM
        self.teams._apply_roster()
        self.player, self.enemy = game.sentry, self.teams.characters[enemy]
        self.stand(self.player, 0.0, 0.0)
        self.stand(self.enemy, 0.0, distance)
        self.player.local_yaw = game.camera.yaw = 0.0
        for character in (self.player, self.enemy):
            character.powers.hard_reset()
            character.release_motion()
        self.beams_free = len(self.combat._beams)
        self.addCleanup(self._leave)
        return game

    def _leave(self) -> None:
        for key in ("w", "shift"):
            held_keys[key] = 0
        self.combat.reset_world_state()
        for character in self.teams.characters.values():
            character.release_motion()
            character.powers.hard_reset()

    def stand(self, character, x: float, z: float) -> None:
        character.position = (x, self.game.world.height_at(x, z) + .25, z)
        character.flight.phase = FlightPhase.GROUNDED
        character.flight.velocity = SimVec3()
        character.ground.velocity = SimVec3()
        character.knock = SimVec3()
        character.jump_height = character.jump_velocity = 0.0

    def tough(self, character, health: float = 1e8) -> None:
        character.vitals.max_health = health
        character.vitals.health = health
        character.vitals.regen = 0.0

    def tap(self, key: str) -> None:
        self.game.input(key)
        self.game.update(FRAME)
        self.game.input(f"{key} up")

    def frames(self, count: int, dt: float = FRAME) -> None:
        for _ in range(count):
            self.game.update(dt)

    def seconds(self, length: float) -> None:
        self.frames(round(length / FRAME))

    def on_ground(self, character) -> bool:
        return abs(float(character.y) - self.game.world.height_at(character.x, character.z) - .25) < .35

    def run_until_settled(self, character, limit: float = 14.0) -> None:
        for _ in range(round(limit / FRAME)):
            self.game.update(FRAME)
            if character.motion is None:
                return
        self.fail("still in motion")

    def largest_step_until_settled(self, character, limit: float = 14.0) -> float:
        """The biggest single-frame move on the way down: a teleport cannot hide from this."""
        largest = 0.0
        previous = SimVec3(float(character.x), float(character.y), float(character.z))
        for _ in range(round(limit / FRAME)):
            self.game.update(FRAME)
            here = SimVec3(float(character.x), float(character.y), float(character.z))
            largest = max(largest, (here - previous).length())
            previous = here
            if character.motion is None:
                return largest
        self.fail("still in motion")


class PunchTests(LiveCase):
    def test_all_four_use_the_same_attack_with_their_own_look(self):
        styles = {PUNCH_STYLES[character_id] for character_id in FLYERS}
        self.assertEqual(len(styles), 4)
        for character_id in FLYERS:
            self.assertEqual(SLOT_ABILITIES[character_id]["2"], "high_speed_attack")
            self.begin(character_id)
            self.tap("2")
            self.assertIsInstance(self.player.motion, StrikeAndBreakAway, character_id)

    def test_punch_launches_the_enemy_who_falls_naturally_and_the_attacker_flies_past(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.begin(character_id)
                self.tough(self.enemy)
                start = SimVec3(self.enemy.x, self.enemy.y, self.enemy.z)
                self.game.input("2")
                largest_step, highest, launched = 0.0, 0.0, False
                previous = start
                for _ in range(round(14.0 / FRAME)):
                    self.game.update(FRAME)
                    here = SimVec3(float(self.enemy.x), float(self.enemy.y), float(self.enemy.z))
                    largest_step = max(largest_step, (here - previous).length())
                    highest = max(highest, here.y - self.game.world.height_at(here.x, here.z))
                    previous = here
                    launched = launched or isinstance(self.enemy.motion, LaunchedMotion)
                    if launched and self.enemy.motion is None and self.player.motion is None:
                        break
                self.game.input("2 up")
                self.assertTrue(launched)
                self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "real damage")
                travelled = (SimVec3(float(self.enemy.x), 0.0, float(self.enemy.z))
                             - SimVec3(start.x, 0.0, start.z)).length()
                self.assertGreater(travelled, 100.0, "a considerable distance")
                self.assertGreater(highest, 5.0, "through the air, not along the ground")
                self.assertLessEqual(largest_step, MAX_LAUNCH_SPEED * FRAME + 1.0, "never teleported")
                self.assertTrue(self.on_ground(self.enemy), "down on the ground")
                self.assertIsNone(self.player.motion, "control is back")
                self.assertGreater(float(self.player.z), start.z, "carried on past where they were")
                self.assertGreater((center_of(self.player) - center_of(self.enemy)).length(), 3.0,
                                   "not stuck inside the enemy")
                self.assertLess(abs(self.player.right_arm.rotation_x), 30.0, "the punch pose has ended")
                self.assertEqual(len(self.combat._beams), self.beams_free, "streak handed back")

    def test_the_world_stops_for_the_attack_and_resumes_after_it(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.begin(character_id, "RED", distance=200.0)
                self.tough(self.enemy)
                bystander = self.teams.characters["GREEN" if character_id != "GREEN" else "WHITE"]
                self.teams.state.assignment[bystander.character_id] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(bystander, 400.0, 400.0)
                bystander.flight.velocity = SimVec3(1.0, 0.0, 0.0)
                self.tap("2")
                self.assertTrue(self.combat.time_stopped, "immediately")
                motion = self.player.motion
                where = float(bystander.x), float(bystander.z)
                flew = None
                while self.player.motion is motion:
                    self.assertEqual(where, (float(bystander.x), float(bystander.z)))
                    if isinstance(self.enemy.motion, LaunchedMotion):
                        flew = flew if flew is not None else float(self.enemy.z)
                    self.game.update(FRAME)
                self.assertGreater(float(self.enemy.z), flew, "the target flies in stopped time")
                self.game.update(FRAME)
                self.assertFalse(self.combat.time_stopped, "and it ends with the attack")
                self.assertFalse(self.game.hud.vision_overlay.enabled)
                self.assertIsNone(self.player.motion)
                self.assertLessEqual(self.largest_step_until_settled(self.enemy),
                                     MAX_LAUNCH_SPEED * FRAME + 1.0)
                self.assertTrue(self.on_ground(self.enemy))

    def test_a_blow_that_downs_the_enemy_still_sends_them_flying_and_they_recover(self):
        self.begin("GREEN")
        self.enemy.vitals.health = 5.0
        start_z = float(self.enemy.z)
        self.game.input("2")
        for _ in range(60):
            self.game.update(FRAME)
            if self.enemy.vitals.downed:
                break
        self.game.input("2 up")
        self.assertTrue(self.enemy.vitals.downed)
        self.assertIsInstance(self.enemy.motion, LaunchedMotion)
        self.run_until_settled(self.enemy)
        self.assertGreater(float(self.enemy.z) - start_z, 50.0)
        self.assertTrue(self.on_ground(self.enemy))
        self.enemy.vitals.downed_for = .01
        self.frames(3)
        self.assertFalse(self.enemy.vitals.downed)
        self.assertIsNone(self.enemy.motion)

    def test_target_vanishing_during_the_charge_cancels_safely(self):
        self.begin("BLACK", distance=3000.0)
        self.combat.settings.set("BLACK", "high_speed_attack", "speed", 100)
        self.tap("2")
        self.assertIsInstance(self.player.motion, StrikeAndBreakAway)
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        self.frames(2)
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)
        self.assertEqual(len(self.combat._beams), self.beams_free)
        self.assertLess(abs(self.player.right_arm.rotation_x), 30.0)

    def test_no_enemy_means_no_attack(self):
        self.begin("WHITE")
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        self.tap("2")
        self.assertIsNone(self.player.motion)

    def test_a_thrown_body_is_stopped_by_a_building_rather_than_passing_through(self):
        self.begin("WHITE")
        self.tough(self.enemy)
        tree = fresh_tree(self.game, minimum=8.0)
        self.stand(self.enemy, tree.x, tree.z - 30.0)
        launch_character(self.player, self.enemy, SimVec3(0.0, 2.0, 300.0))
        before = tree.tree_health
        self.run_until_settled(self.enemy)
        self.assertTrue(tree.is_empty() or tree.tree_health < before, "the tree took the hit")


class NuclearExecutionTests(LiveCase):
    def run_to(self, motion, phase, limit=900):
        for _ in range(limit):
            if motion.phase == phase or self.player.motion is not motion:
                return
            self.game.update(FRAME)
        self.fail(f"never reached {phase}")

    def test_the_whole_sequence_for_all_four(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.begin(character_id, "RED", distance=80.0)
                self.tough(self.enemy)
                bystander = self.teams.characters["GREEN" if character_id != "GREEN" else "WHITE"]
                self.teams.state.assignment[bystander.character_id] = ENEMY_TEAM
                self.teams._apply_roster()
                self.stand(bystander, 60.0, 80.0)
                self.tough(bystander)
                craters = len(self.game.world.terrain_impacts)
                self.tap("3")
                motion = self.player.motion
                self.assertIsInstance(motion, NuclearExecution)
                self.assertTrue(self.combat.time_stopped, "immediately")
                self.run_to(motion, GRIP)
                self.assertLessEqual((center_of(self.enemy) - center_of(self.player)).length(), 3.1)
                self.run_to(motion, CARRY)
                self.assertTrue(self.enemy.vitals.has("held"))
                ground = self.game.world.height_at(self.enemy.x, self.enemy.z)
                self.assertGreater(float(self.enemy.y) - ground, 20.0, "driven down from a height")
                largest, previous = 0.0, float(self.enemy.y)
                while motion.phase == CARRY:
                    self.game.update(FRAME)
                    largest = max(largest, abs(float(self.enemy.y) - previous))
                    previous = float(self.enemy.y)
                self.assertLessEqual(largest, MAX_CARRY_SPEED * FRAME + 1.0, "carried, not teleported")
                self.assertEqual(motion.phase, PUNCH)
                self.assertTrue(self.on_ground(self.player), "on the ground")
                self.assertTrue(self.enemy.vitals.has("held"), "the grab holds through the impact")
                self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "the punch comes next")
                self.run_to(motion, AFTERMATH)
                self.assertTrue(self.combat.time_stopped)
                self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "punch and blast are real")
                self.assertGreater(bystander.vitals.damage_taken, 0.0, "the blast reaches others")
                self.assertGreater(len(self.game.world.terrain_impacts), craters, "the ground is torn up")
                self.assertFalse(self.enemy.vitals.has("held"), "let go")
                self.assertIsInstance(self.enemy.motion, LaunchedMotion)
                moved_from = float(bystander.x)
                self.seconds(.5)
                self.assertFalse(self.combat.time_stopped, "time resumes")
                self.assertIsNone(self.player.motion, "control is back")
                self.assertFalse(self.game.hud.vision_overlay.enabled)
                self.assertLess(abs(self.player.left_arm.rotation_x), 30.0, "the punch pose has ended")
                self.assertEqual(len(self.combat._beams), self.beams_free)
                self.seconds(.5)
                self.assertNotEqual(float(bystander.x), moved_from, "and the blast's push arrives")
                self.run_until_settled(self.enemy)
                self.assertTrue(self.on_ground(self.enemy))

    def test_every_tree_inside_the_blast_is_hit_and_none_outside(self):
        self.begin("WHITE", "RED", distance=80.0)
        self.tough(self.enemy)
        world = self.game.world
        everything = [tree for chunk in world.chunks.values() for tree in chunk.tree_colliders
                      if tree.tree_health >= world.TREE_MAX_HEALTH]

        def apart(a, b) -> float:
            return ((a.x - b.x) ** 2 + (a.z - b.z) ** 2) ** .5

        # Other tests flatten the same ground, so go wherever there is still a grove standing.
        center = max(everything, key=lambda tree: sum(apart(tree, other) < 150.0 for other in everything))
        cx, cz = float(center.x), float(center.z)
        self.stand(self.enemy, cx, cz)
        self.stand(self.player, cx, cz - 80.0)
        place = {tree: (((tree.x - cx) ** 2 + (tree.z - cz) ** 2) ** .5, tree.tree_health) for tree in everything}
        inside = [tree for tree, (metres, _health) in place.items() if metres < 150.0]
        outside = [tree for tree, (metres, _health) in place.items() if metres > 300.0]
        self.assertGreater(len(inside), 3, "a test needs trees to test")
        self.tap("3")
        self.run_to(self.player.motion, AFTERMATH)
        for tree in inside:
            self.assertTrue(tree.is_empty() or tree.tree_health < place[tree][1], f"{place[tree][0]:.0f} m")
        for tree in outside:
            self.assertEqual(tree.tree_health, place[tree][1])

    def test_it_detonates_even_when_the_punch_alone_is_fatal(self):
        self.begin("WHITE", "RED", distance=40.0)
        self.combat.settings.set("WHITE", "time_stop", "damage", 20000)
        self.tap("3")
        motion = self.player.motion
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            self.run_to(motion, AFTERMATH)
        self.assertEqual(blast.call_count, 1)
        self.assertTrue(self.enemy.vitals.downed)
        self.assertIsInstance(self.enemy.motion, LaunchedMotion)
        self.assertLessEqual(self.largest_step_until_settled(self.enemy), MAX_LAUNCH_SPEED * FRAME + 1.0)
        self.assertTrue(self.on_ground(self.enemy))

    def test_range_sets_the_size_of_the_explosion(self):
        self.begin("WHITE", "RED", distance=40.0)
        self.tough(self.enemy)
        self.combat.settings.set("WHITE", "time_stop", "range", 500)
        self.tap("3")
        motion = self.player.motion
        with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
            self.run_to(motion, AFTERMATH)
        self.assertEqual(blast.call_args.args[2], 50.0)

    def test_target_vanishing_part_way_cancels_with_no_explosion_and_time_resumes(self):
        for stage in (RUSH, CARRY, PUNCH):
            with self.subTest(stage):
                self.begin("BLACK", "RED", distance=300.0)
                self.combat.settings.set("BLACK", "time_stop", "speed", 300)
                self.tough(self.enemy)
                self.tap("3")
                motion = self.player.motion
                self.run_to(motion, stage)
                self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
                self.teams._apply_roster()
                with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast:
                    self.frames(2)
                self.assertEqual(blast.call_count, 0)
                self.assertIsNone(self.player.motion)
                self.assertFalse(self.combat.time_stopped)
                self.assertFalse(self.enemy.vitals.has("held"))
                self.assertEqual(len(self.combat._beams), self.beams_free)

    def test_switching_character_part_way_lets_go_and_resumes_time(self):
        self.begin("GREEN", "RED", distance=40.0)
        self.tough(self.enemy)
        self.tap("3")
        motion = self.player.motion
        self.run_to(motion, CARRY)
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams.swap("WHITE", save=False)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(self.enemy.vitals.has("held"))
        self.assertLess(self.largest_step_until_settled(self.enemy), 2.0)
        self.assertTrue(self.on_ground(self.enemy))

    def test_keys_cannot_interrupt_it(self):
        self.begin("YELLOW")
        self.tough(self.enemy)
        self.tap("3")
        motion = self.player.motion
        for key in ("1", "2", "3", "4", "t", "q", "="):
            self.tap(key)
        self.assertIs(self.player.motion, motion)
        self.assertFalse(self.combat.world_stopped)


class HomelanderExecutionTests(LiveCase):
    def begin_execution(self, enemy="RED", distance=60.0):
        self.begin("BLACK", enemy, distance)
        self.tough(self.enemy)
        self.tap("4")
        return self.player.motion

    def run_to(self, motion, phase, limit=600):
        for _ in range(limit):
            if motion.phase == phase or self.player.motion is not motion:
                return
            self.game.update(FRAME)
        self.fail(f"never reached {phase}")

    def test_only_homelander_got_this_and_the_other_fours_are_kept(self):
        self.assertEqual(SLOT_ABILITIES["BLACK"]["4"], "neck_laser_execution")
        self.assertEqual(SLOT_ABILITIES["WHITE"]["4"], "ground_execution")
        self.assertEqual(SLOT_ABILITIES["YELLOW"]["4"], "void_nuclear_execution")
        self.assertEqual(SLOT_ABILITIES["GREEN"]["4"], "speed_execution")
        self.assertEqual(SLOT_ABILITIES["RED"]["4"], "radioactive_execution")

    def test_the_whole_sequence(self):
        motion = self.begin_execution()
        self.assertIsInstance(motion, NeckLaserExecution)
        self.assertTrue(self.player.flight.is_flying)
        self.run_to(motion, LIFT)
        self.assertLessEqual((center_of(self.enemy) - center_of(self.player)).length(), 3.1, "at the neck")
        self.assertTrue(self.enemy.vitals.has("held"))
        ground = self.game.world.height_at(self.enemy.x, self.enemy.z)
        self.run_to(motion, LASER)
        self.assertGreater(float(self.enemy.y) - ground, 20.0, "lifted into the air")
        # Exactly three seconds of laser, in frames, with real damage all the way through.
        frames = 0
        taken = []
        while self.player.motion is motion and motion.phase == LASER:
            self.game.update(FRAME)
            frames += 1
            taken.append(self.enemy.vitals.damage_taken)
            if frames == 60:
                beam = motion.beam
                self.assertTrue(beam.cores[0].visible and beam.cores[1].visible, "both eyes")
                face = motion._face_of_target()
                self.assertLess((SimVec3(*beam.flare.position) - face).length(), .01, "into the face")
                self.assertTrue(self.enemy.vitals.has("held"))
            self.assertLess(frames, 900)
        self.assertAlmostEqual(frames * FRAME, LASER_SECONDS, delta=FRAME, msg="exactly as long as the laser stage is set to last")
        self.assertGreater(len(set(taken)), 25, "damage throughout, not all at once")
        expected = (self.combat.settings.get("BLACK", "neck_laser_execution", "damage")
                    * self.player.powers.strength * LASER_SHARE * .55)  # Soldier Boy's resistance is 45%
        self.assertAlmostEqual(self.enemy.vitals.damage_taken, expected, delta=expected * .001)
        self.assertEqual(motion.damage_dealt, self.enemy.vitals.damage_taken)
        # Clones, the second grip and the juggle come next, and then everything is put back.
        for _ in range(round(60.0 / FRAME)):
            if self.player.motion is not motion:
                break
            self.game.update(FRAME)
        self.assertIsNot(self.player.motion, motion, "the sequence ends")
        self.assertFalse(self.enemy.vitals.has("held"))
        self.assertEqual(len(self.combat._beams), self.beams_free, "beam stopped")
        self.assertEqual(self.enemy.flight.phase, FlightPhase.GROUNDED)
    def test_three_seconds_are_real_seconds_even_at_a_low_frame_rate(self):
        motion = self.begin_execution()
        self.run_to(motion, LASER)
        frames = 0
        while motion.phase == LASER:
            self.game.update(.1)  # 10 FPS, slower than the simulation's .05 cap
            frames += 1
            self.assertLess(frames, 100)
        self.assertAlmostEqual(frames * .1, 4.0, delta=.1)
        self.player.release_motion()

    def test_full_damage_setting_is_what_is_dealt_and_is_editable(self):
        self.begin("BLACK")
        self.combat.settings.set("BLACK", "neck_laser_execution", "damage", 100)
        self.tough(self.enemy)
        self.tap("4")
        motion = self.player.motion
        self.run_to(motion, LASER)
        while self.player.motion is motion:
            self.game.update(FRAME)
        # The clones' staggered blows come to a little under their whole share.
        self.assertAlmostEqual(self.enemy.vitals.damage_taken, 100 * self.player.powers.strength * .55 * .96,
                               delta=.1)

    def test_target_dying_during_the_laser_cancels_and_they_fall(self):
        motion = self.begin_execution()
        self.run_to(motion, LASER)
        self.seconds(.5)
        self.enemy.vitals.health = 1.0
        self.frames(12)
        self.assertTrue(self.enemy.vitals.downed)
        self.assertIsNone(self.player.motion)
        self.assertEqual(len(self.combat._beams), self.beams_free)
        self.assertFalse(self.enemy.vitals.has("held"))
        self.assertLess(abs(self.player.right_arm.rotation_x), 30.0)
        self.assertIsInstance(self.enemy.motion, LaunchedMotion)
        self.assertGreater(float(self.enemy.y) - self.game.world.height_at(self.enemy.x, self.enemy.z), 20.0,
                           "still up there when let go")
        self.assertLess(self.largest_step_until_settled(self.enemy), 2.0, "a fall, not a snap to the floor")
        self.assertTrue(self.on_ground(self.enemy))

    def test_target_despawning_or_changing_sides_cancels(self):
        for change in (AVAILABLE, MY_TEAM):
            with self.subTest(change):
                motion = self.begin_execution()
                self.run_to(motion, LASER)
                self.teams.state.assignment[self.enemy.character_id] = change
                self.teams._apply_roster()
                self.frames(2)
                self.assertIsNone(self.player.motion)
                self.assertEqual(len(self.combat._beams), self.beams_free)
                self.assertFalse(self.enemy.vitals.has("held"))

    def test_switching_character_mid_laser_leaves_nothing_behind(self):
        motion = self.begin_execution()
        self.run_to(motion, LASER)
        self.teams.state.assignment["WHITE"] = MY_TEAM
        self.teams.swap("WHITE", save=False)
        self.assertIsNone(self.teams.characters["BLACK"].motion)
        self.assertFalse(self.enemy.vitals.has("held"))
        self.assertEqual(len(self.combat._beams), self.beams_free)
        self.assertLess(self.largest_step_until_settled(self.enemy), 2.0)
        self.assertTrue(self.on_ground(self.enemy))

    def test_a_second_press_does_not_restart_it_and_no_enemy_does_nothing(self):
        motion = self.begin_execution()
        self.tap("4")
        self.assertIs(self.player.motion, motion)
        self.begin("BLACK")
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        self.tap("4")
        self.assertIsNone(self.player.motion)


class KeyRTests(LiveCase):
    def state_of(self):
        player = self.player
        return ({name: ability.active for name, ability in player.powers.abilities.items()},
                player.motion, player.flight.phase, float(player.x), float(player.y), float(player.z),
                player.vitals.health, self.combat.time_stopped, len(self.combat.projectiles),
                self.game._notification)

    def test_r_does_nothing_for_all_five(self):
        for character_id in ROSTER_IDS:
            with self.subTest(character_id):
                self.begin(character_id, "BLACK" if character_id != "BLACK" else "RED")
                self.player.vitals.regen = 0.0
                self.frames(2)
                before = self.state_of()
                self.game.input("r")
                self.assertEqual(self.state_of(), before)
                self.game.input("r up")
                self.game.input("R")
                self.game.input("r hold")
                self.assertEqual(self.state_of(), before)
                self.assertNotIn("r", self.player.powers.slots)
                self.assertNotIn("r", self.player.powers.held)

    def test_r_is_gone_from_every_table_and_cannot_be_reassigned(self):
        self.assertNotIn("r", controls.ABILITY_SLOTS)
        self.assertNotIn("r up", controls.SLOT_RELEASES)
        self.assertNotIn("r", controls.KEY_ACTIONS)
        self.assertEqual(controls.binding_conflict("camera_reset", "r"), "reserved")
        for character_id in ROSTER_IDS:
            self.assertNotIn("r", SLOT_ABILITIES[character_id])
            for ability in SCHEMA[character_id]:
                self.assertNotIn("R", ability.binding.split(", "), ability.ability_id)

    def test_nobody_is_bound_to_the_old_target_toggle_and_targeting_stays_on(self):
        self.assertNotIn("auto_target", controls.CONTROL_BINDINGS)
        self.begin("RED", "BLACK")
        self.tap("t")
        self.assertTrue(self.combat.targets.enabled)
        self.combat.end_world_stop()


class TimeStopTests(LiveCase):
    def snapshot(self, character):
        return (float(character.x), float(character.y), float(character.z), character.flight.phase,
                character.flight.velocity.x, character.flight.velocity.y, character.flight.velocity.z,
                character.knock.x, character.knock.z, character.jump_velocity, character.vitals.health,
                dict(character.vitals.statuses), character.vitals.downed_for, character.next_decision)

    def test_exactly_thirty_seconds_at_60_fps(self):
        self.begin("WHITE")
        self.tap("t")  # the first of the frames
        self.assertTrue(self.combat.world_stopped)
        frames = 1
        while self.combat.world_stopped:
            self.game.update(FRAME)
            frames += 1
            self.assertLess(frames, 1900)
        self.assertAlmostEqual(frames * FRAME, 30.0, delta=FRAME)

    def test_thirty_real_seconds_at_a_low_frame_rate_for_each_flyer(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.begin(character_id)
                self.game.input("t")
                frames = 0
                while self.combat.world_stopped:
                    self.game.update(.2)  # 5 FPS: the simulation's own step is capped at .05
                    frames += 1
                    self.assertLess(frames, 200)
                self.assertAlmostEqual(frames * .2, 30.0, delta=.2)

    def test_soldier_boy_has_it_too_and_it_gives_him_no_flight(self):
        self.begin("RED", "BLACK")
        self.tap("t")
        self.assertTrue(self.combat.world_stopped)
        self.assertFalse(self.player.flight_allowed)

    def test_ai_can_never_trigger_it(self):
        self.begin("WHITE")
        self.enemy = self.teams.characters["RED"]
        black = self.teams.characters["BLACK"]
        black.powers.abilities["world_stop"].press()
        self.assertFalse(self.combat.world_stopped)

    def test_another_press_neither_resets_nor_extends_it(self):
        self.begin("BLACK")
        self.tap("t")
        self.seconds(5.0)
        left = self.combat.world_stop_left
        self.tap("t")
        self.assertAlmostEqual(self.combat.world_stop_left, left - FRAME, delta=1e-6)

    def test_the_world_freezes_and_resumes_with_everything_as_it_was(self):
        self.begin("WHITE", ai_powers=True)
        self.game.input("f")
        self.seconds(.5)
        self.seconds(9.0)  # AI is under way
        enemy = self.enemy
        launch_character(None, enemy, SimVec3(10.0, 40.0, 5.0))
        self.seconds(.3)
        velocity = enemy.motion.velocity
        self.combat.fire_projectile(enemy, center_of(enemy), SimVec3(0.0, 0.0, -1.0), speed=20.0,
                                    reach=500.0, damage=1.0, radius=1.0, tint=(255, 255, 255, 255),
                                    size=.5, force=0.0)
        shot = self.combat.projectiles[-1]
        environment = self.game.environment._time
        elapsed_before = self.game.elapsed
        wait = enemy._ai_next_attack - elapsed_before
        fall_frozen = self.snapshot(enemy)
        shot_at = shot.position
        self.tap("t")
        self.assertTrue(self.combat.world_stopped)
        for _ in range(40):
            self.game.update(FRAME)
            self.assertEqual(self.snapshot(enemy)[:3], fall_frozen[:3], "does not move at all")
        self.assertIs(enemy.motion.velocity, velocity, "keeps the velocity it had")
        self.assertEqual(shot.position, shot_at, "enemy shots hang in the air")
        self.assertEqual(self.game.environment._time, environment, "clouds, waves and wind wait too")
        self.assertEqual(self.snapshot(enemy)[3:], fall_frozen[3:])
        self.combat.end_world_stop()
        self.game.update(FRAME)
        self.assertAlmostEqual(enemy._ai_next_attack - self.game.elapsed, wait, delta=2 * FRAME,
                               msg="the AI's wait is what it was")
        self.seconds(.2)
        self.assertNotEqual(float(enemy.y), fall_frozen[1], "and the fall carries on")
        self.assertGreater(self.game.environment._time, environment)

    def test_civilians_vehicles_debris_and_objects_get_no_time(self):
        """They all advance only on the time the world is handed, and it is handed none."""
        self.begin("WHITE")
        world = self.game.world
        self.tap("t")
        with mock.patch.object(world, "update", wraps=world.update) as world_update:
            self.frames(10)
        self.assertEqual({call.args[0] for call in world_update.call_args_list}, {0.0})
        self.combat.end_world_stop()
        with mock.patch.object(world, "update", wraps=world.update) as world_update:
            self.frames(3)
        self.assertGreater(world_update.call_args_list[-1].args[0], 0.0)

    def test_ai_is_fully_active_again_afterwards(self):
        self.begin("WHITE", ai_powers=True)
        self.tap("t")
        self.seconds(1.0)
        before = float(self.enemy.x), float(self.enemy.z)
        self.seconds(1.0)
        self.assertEqual(before, (float(self.enemy.x), float(self.enemy.z)))
        self.combat.world_stop_left = FRAME * .5
        self.seconds(25.0)
        self.assertFalse(self.combat.time_stopped)
        self.assertNotEqual(before, (float(self.enemy.x), float(self.enemy.z)))
        self.assertGreater(self.player.vitals.damage_taken, 0.0, "and it attacks again")

    def test_the_player_moves_flies_and_fights_while_time_is_stopped(self):
        self.begin("WHITE", distance=40.0)
        self.tough(self.enemy)
        self.tap("t")
        start = float(self.player.z)
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertGreater(abs(float(self.player.z) - start) + abs(float(self.player.x)), 1.0, "walks")
        self.tap("f")
        self.seconds(1.0)
        self.assertTrue(self.player.flight.is_flying, "flies")
        taken = self.enemy.vitals.damage_taken
        self.tap("1")
        self.seconds(.5)
        self.assertTrue(self.player.powers.abilities["heat_vision"].active)
        self.tap("1")
        self.assertGreater(self.enemy.vitals.damage_taken, taken, "the beam really hurts")
        taken = self.enemy.vitals.damage_taken
        self.tap("=")
        self.seconds(2.0)
        self.tap("-")
        self.seconds(2.0)
        self.assertGreater(self.enemy.vitals.damage_taken, taken, "punch and kick land")
        self.assertTrue(self.combat.world_stopped)

    def test_a_punch_launch_in_stopped_time_waits_and_then_flies(self):
        self.begin("GREEN")
        self.tough(self.enemy)
        self.tap("t")
        self.game.input("2")
        for _ in range(30):
            self.game.update(FRAME)
            if isinstance(self.enemy.motion, LaunchedMotion):
                break
        self.game.input("2 up")
        self.assertIsInstance(self.enemy.motion, LaunchedMotion)
        self.seconds(1.0)
        self.assertIsNone(self.player.motion, "the attacker has flown on and is free")
        where = float(self.enemy.z)
        self.seconds(1.0)
        self.assertEqual(float(self.enemy.z), where, "held in stopped time")
        self.combat.end_world_stop()
        self.run_until_settled(self.enemy)
        self.assertGreater(float(self.enemy.z) - where, 50.0)
        self.assertTrue(self.on_ground(self.enemy))

    def test_the_players_own_shots_fly_and_explode_while_others_stay_put(self):
        self.begin("YELLOW", "RED", distance=30.0)
        self.tough(self.enemy)
        self.tap("t")
        self.player.powers.abilities["energy_projection"].press()
        for _ in range(240):
            self.game.update(FRAME)
            if self.enemy.vitals.damage_taken > 0.0:
                break
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "the player's own shot reached them")

    def test_a_key_3_sequence_inside_it_ends_without_ending_the_stop(self):
        self.begin("BLACK")
        self.tough(self.enemy)
        self.tap("t")
        self.tap("3")
        self.assertTrue(self.combat.sequence_running)
        self.assertEqual(self.game.hud.countdown.text[:9], "TIME STOP")
        for _ in range(600):
            self.game.update(FRAME)
            if not self.combat.sequence_running:
                break
        self.assertFalse(self.combat.sequence_running)
        self.assertTrue(self.combat.world_stopped)
        self.assertTrue(self.game.hud.vision_overlay.enabled)
        self.assertEqual(self.game.hud.countdown.text[:9], "TIME STOP")
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)

    def test_homelanders_4_works_inside_it(self):
        self.begin("BLACK")
        self.tough(self.enemy)
        self.tap("t")
        self.tap("4")
        motion = self.player.motion
        self.assertIsInstance(motion, NeckLaserExecution)
        for _ in range(600):
            self.game.update(FRAME)
            if self.player.motion is not motion:
                break
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertFalse(self.enemy.vitals.has("held"))
        self.assertTrue(self.combat.world_stopped)

    def test_switching_character_during_it_changes_who_moves_and_not_the_clock(self):
        self.begin("WHITE")
        self.tap("t")
        self.seconds(5.0)
        white = self.player
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams.swap("GREEN", save=False)
        green = self.game.sentry
        self.stand(green, 40.0, 0.0)
        where = float(white.x), float(white.z)
        self.assertTrue(self.combat.world_stopped)
        self.assertTrue(self.game.hud.vision_overlay.enabled, "the look survives the switch")
        self.assertEqual(self.game.hud.countdown.text[:9], "TIME STOP")
        left = self.combat.world_stop_left
        start = float(green.x), float(green.z)
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertNotEqual(start, (float(green.x), float(green.z)), "the new character is the free one")
        self.assertEqual(where, (float(white.x), float(white.z)), "the old one is now frozen")
        self.assertAlmostEqual(self.combat.world_stop_left, left - 1.0, delta=FRAME * 2)
        self.teams.state.assignment["RED"] = MY_TEAM
        self.teams.swap("RED", save=False)  # switching again cannot leave it stuck
        self.combat.world_stop_left = FRAME * .5
        self.frames(2)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(self.game.hud.vision_overlay.enabled)

    def test_things_destroyed_or_changing_during_it_are_safe(self):
        self.begin("WHITE", distance=20.0)
        tree = fresh_tree(self.game, minimum=8.0)
        self.tap("t")
        self.game.world.damage_tree(tree, 1e6, SimVec3(0.0, 0.0, 1.0))
        self.teams.state.assignment[self.enemy.character_id] = AVAILABLE
        self.teams._apply_roster()
        self.teams.state.assignment["GREEN"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.seconds(.5)
        self.combat.world_stop_left = FRAME * .5
        self.seconds(.5)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(self.teams.characters["GREEN"].parked)

    def test_a_menu_or_pause_holds_the_countdown(self):
        self.begin("WHITE")
        self.tap("t")
        left = self.combat.world_stop_left
        self.game.input("escape")
        self.frames(30)
        self.assertEqual(self.combat.world_stop_left, left)
        self.game.input("escape")
        self.frames(1)
        self.assertLess(self.combat.world_stop_left, left)

    def test_countdown_and_look(self):
        self.begin("WHITE")
        hud = self.game.hud
        self.assertEqual(hud.countdown.text, "")
        self.tap("t")
        self.assertEqual(hud.countdown.text, "TIME STOP  30")
        self.assertTrue(hud.vision_overlay.enabled)
        self.assertTrue(hud.ripple.enabled)
        self.seconds(1.0)
        self.assertFalse(hud.ripple.enabled, "the ripple passes")
        self.assertIn(hud.countdown.text, ("TIME STOP  29", "TIME STOP  28"))
        self.combat.world_stop_left = FRAME * .5
        self.frames(1)
        self.assertEqual(hud.countdown.text, "")
        self.assertFalse(hud.vision_overlay.enabled)

    def test_a_world_reset_clears_it(self):
        self.begin("WHITE")
        self.tap("t")
        self.combat.reset_world_state()
        self.assertFalse(self.combat.time_stopped)
        self.assertEqual(self.game.hud.countdown.text, "")


class RestartTests(unittest.TestCase):
    def test_game_starts_and_runs_with_no_time_stop_left_over(self):
        game = reset_game()
        run_frames(game, 2)
        self.assertFalse(game.combat.time_stopped)


if __name__ == "__main__":
    unittest.main()
