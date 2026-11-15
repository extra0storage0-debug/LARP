"""The character powers and controls update: every key, for every character."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from characters.roster import ROSTER_IDS
from config.power_schema import SCHEMA
from game import controls
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import PowerCase, fresh_tree, object_of
from powers.superman import ExecutionSequence
from powers.common import LaunchedMotion
from powers.universal import NuclearExecution, StrikeAndBreakAway
from powers.vitals import PHYSICAL

FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")
BOMBERS = ("YELLOW", "RED")


class ControlsCase(PowerCase):
    def enemy_for(self, character_id: str, distance: float = 40.0, x: float = 0.0):
        self.play(character_id)
        return self.place_enemy("WHITE" if character_id == "BLACK" else "BLACK", distance, x=x)

    def tough(self):
        self.enemy.vitals.max_health = 1e8
        self.enemy.vitals.health = 1e8


class DisabledInputTests(ControlsCase, unittest.TestCase):
    def test_e_and_both_mouse_buttons_do_nothing_for_all_five(self):
        for character_id in ROSTER_IDS:
            self.enemy_for(character_id, 4.0)
            self.tough()
            for key, release in (("e", "e up"), ("left mouse down", "left mouse up"),
                                 ("right mouse down", "right mouse up")):
                self.game.input(key)
                self.frames(3)
                self.game.input(release)
                self.frames(1)
                self.assertEqual(self.enemy.vitals.damage_taken, 0.0, f"{character_id} {key}")
                self.assertIsNone(self.player.motion, f"{character_id} {key}")
                self.assertFalse(any(ability.active for ability in self.player.powers.abilities.values()),
                                 f"{character_id} {key}")
                self.assertEqual(self.player.powers.held, set())
                self.assertFalse(self.player.powers.aiming)
            self.assertIsNone(self.ability("grab").held)

    def test_soldier_boy_inherits_no_universal_attack(self):
        self.enemy_for("RED", 8.0)
        for name in ("high_speed_attack", "time_stop", "melee"):
            self.assertNotIn(name, self.player.powers.abilities)
        for key in ("+", "=", "-"):  # his own 2 and 3 are in test_soldier_boy_powers
            self.game.input(key)
            self.frames(2)
            self.game.input(f"{key} up")
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0)
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)

    def test_soldier_boy_has_no_flight_from_any_key(self):
        self.enemy_for("RED", 500.0)
        floor = self.game.world.height_at(self.player.x, self.player.z)
        for key in ("control", "shift"):
            self.game.input(key)
            self.frames(5)
            self.game.input(f"{key} up")
            self.assertFalse(self.player.flight.is_flying, key)
        self.assertLess(self.player.y, floor + 1.0)
        self.game.input("f")  # his super jump, which is not flight
        self.frames(5)
        self.game.input("f up")
        self.assertFalse(self.player.flight.is_flying)

    def test_the_slot_tables_match_the_specification(self):
        keys = {character_id: {key: ability.ability_id for key, ability
                               in self.teams.characters[character_id].powers.slots.items()}
                for character_id in ROSTER_IDS}
        for character_id in FLYERS:
            self.assertEqual(keys[character_id]["2"], "high_speed_attack")
            self.assertEqual(keys[character_id]["3"], "time_stop")
            self.assertEqual(keys[character_id]["+"], "melee")
            self.assertEqual(keys[character_id]["-"], "melee")
        self.assertEqual(keys["WHITE"]["1"], "heat_vision")
        self.assertEqual(keys["WHITE"]["4"], "ground_execution")
        self.assertEqual(keys["BLACK"]["1"], "laser_vision")
        self.assertEqual(keys["BLACK"]["4"], "neck_laser_execution")
        self.assertEqual(keys["GREEN"]["1"], "squad_summon")
        self.assertEqual(keys["GREEN"]["4"], "speed_execution")
        self.assertEqual(keys["YELLOW"]["1"], "void_form")
        self.assertEqual(keys["RED"]["1"], "radiation_blast")
        self.assertEqual(keys["YELLOW"]["4"], "void_nuclear_execution")
        self.assertEqual(keys["RED"]["4"], "radioactive_execution")
        self.assertEqual(set(keys["RED"]), {"1", "2", "3", "4", "t"})

    def test_mouse_buttons_and_e_are_not_bound_at_all(self):
        for key in ("e", "left mouse down", "right mouse down"):
            self.assertNotIn(key, controls.ABILITY_SLOTS)
        for key in ("e up", "left mouse up", "right mouse up"):
            self.assertNotIn(key, controls.SLOT_RELEASES)

    def test_switching_gives_each_body_its_own_controls(self):
        for character_id in ("RED", "WHITE", "YELLOW", "RED", "GREEN", "BLACK"):
            self.teams.swap(character_id, save=False)
            slots = self.game.sentry.powers.slots
            self.assertIn("2", slots)
            self.assertEqual(self.game.sentry.flight_allowed, character_id != "RED")
            shown = {card.ability_id for card in SCHEMA[character_id]}
            for ability in slots.values():
                if ability.ability_id not in ("dash", "world_stop"):
                    self.assertIn(ability.ability_id, shown)


class PunchAndKickTests(ControlsCase, unittest.TestCase):
    def test_plus_and_minus_on_every_keyboard_spelling(self):
        for character_id in FLYERS:
            self.enemy_for(character_id, 3.0)
            self.tough()
            melee = self.ability("melee")
            for key, kicks in (("+", 0), ("=", 0), ("-", 1), ("_", 1)):
                melee.kicks = 0
                before = melee.attacks
                self.game.input(key)
                self.game.input(f"{key} up")
                self.assertEqual(melee.attacks, before + 1, f"{character_id} {key}")
                self.assertEqual(melee.kicks, kicks, f"{character_id} {key}")
                self.frames(1)

    def test_punch_and_kick_work_independently_and_kick_knocks_further(self):
        self.enemy_for("WHITE", 3.0)
        self.tough()
        self.tap("=")
        punch_damage, punch_knock = self.enemy.vitals.damage_taken, self.enemy.knock.length()
        self.assertGreater(punch_damage, 0.0)
        self.stand(self.enemy, 0.0, 3.0)
        self.enemy.vitals.damage_taken = 0.0
        self.tap("-")
        self.assertAlmostEqual(self.enemy.vitals.damage_taken, punch_damage, delta=punch_damage * .01)
        self.assertGreater(self.enemy.knock.length(), punch_knock)

    def test_a_held_key_is_one_blow_and_a_repeat_adds_nothing(self):
        self.enemy_for("YELLOW", 3.0)
        self.tough()
        self.game.input("=")
        self.game.input("= hold")
        self.game.input("=")
        self.frames(30)
        self.game.input("= up")
        self.assertEqual(self.ability("melee").attacks, 1)

    def test_turns_to_face_the_enemy_without_moving_the_camera(self):
        self.enemy_for("GREEN", 0.0, x=4.0)
        self.tough()
        yaw = self.game.camera.yaw
        self.tap("=", frames=2)
        self.assertAlmostEqual(self.player.local_yaw, 90.0, delta=1.0)
        self.assertEqual(self.game.camera.yaw, yaw)

    def test_rushes_an_enemy_out_of_arms_reach_and_lands_one_blow(self):
        self.enemy_for("BLACK", 60.0)
        self.tough()
        self.tap("-")
        self.seconds(.5)
        self.assertEqual(self.ability("melee").kicks, 1)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)


class HighSpeedAttackTests(ControlsCase, unittest.TestCase):
    def test_identical_for_all_four_hits_breaks_away_and_returns_control(self):
        for character_id in FLYERS:
            self.enemy_for(character_id, 200.0, x=30.0)
            self.tough()
            self.aim_at = SimVec3(0.0, 2000.0, 0.0)  # looking nowhere near the enemy
            self.press("2")
            self.release("2")
            motion = self.player.motion
            self.assertIsInstance(motion, StrikeAndBreakAway, character_id)
            for _ in range(180):
                self.frames(1)
                if motion.struck:
                    break
            self.assertTrue(motion.struck, character_id)
            at_impact = (self.player.x, self.player.y, self.player.z)
            taken = self.enemy.vitals.damage_taken
            self.assertGreater(taken, 0.0, character_id)
            self.seconds(.2)
            moved = sum((a - b) ** 2 for a, b in zip((self.player.x, self.player.y, self.player.z),
                                                     at_impact)) ** .5
            self.assertGreater(moved, 15.0, f"{character_id} breaks away")
            self.seconds(.4)
            self.assertIsNone(self.player.motion, f"{character_id}: control returned")
            self.assertEqual(self.enemy.vitals.damage_taken, taken, "one hit per use")

    def test_nothing_happens_with_no_enemy_in_range(self):
        self.enemy_for("WHITE", 40.0)
        self.remove_enemy()
        self.tap("2")
        self.assertIsNone(self.player.motion)

    def test_never_targets_an_ally(self):
        self.enemy_for("WHITE", 40.0)
        ally = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = "my_team"
        self.teams._apply_roster()
        self.stand(ally, 0.0, 5.0)
        ally.vitals.damage_taken = 0.0
        self.remove_enemy()
        self.tap("2")
        self.assertIsNone(self.player.motion, "only an ally near: no attack")
        self.assertEqual(ally.vitals.damage_taken, 0.0)

    def test_values_change_the_result(self):
        self.enemy_for("YELLOW", 40.0)
        self.tough()
        self.set("high_speed_attack", "range", 10)
        self.tap("2")
        self.assertIsNone(self.player.motion, "out of Range")
        self.set("high_speed_attack", "range", 1000)
        self.set("high_speed_attack", "damage", 100)
        self.tap("2")
        self.seconds(.3)
        small = self.enemy.vitals.damage_taken
        self.player.release_motion()
        self.stand(self.player, 0.0, 0.0)
        self.stand(self.enemy, 0.0, 40.0)
        self.enemy.vitals.damage_taken = 0.0
        self.set("high_speed_attack", "damage", 1000)
        self.tap("2")
        self.seconds(.3)
        self.assertGreater(self.enemy.vitals.damage_taken, small * 5.0)


class TimeStopTests(ControlsCase, unittest.TestCase):
    def _run_to_end(self) -> None:
        for _ in range(600):
            self.frames(1)
            if not self.combat.time_stopped:
                return
        self.fail("the time stop never ended")

    def test_identical_for_all_four_and_control_comes_back(self):
        for character_id in FLYERS:
            self.enemy_for(character_id, 30.0)
            self.tough()
            self.tap("3")
            self.assertTrue(self.combat.time_stopped, character_id)
            self.assertIsInstance(self.player.motion, NuclearExecution)
            self._run_to_end()
            self.assertGreater(self.enemy.vitals.damage_taken, 0.0, character_id)
            self.assertIsNone(self.player.motion, f"{character_id}: control returned")
            self.assertFalse(self.game.hud.vision_overlay.enabled, "the tint is gone")
            self.assertFalse(self.enemy.vitals.has("held"))
            self.assertIsInstance(self.enemy.motion, LaunchedMotion)
            self.assertGreater(self.enemy.motion.velocity.length(), 50.0, "thrown hard")

    def test_everything_else_is_frozen_and_resumes_as_it_was(self):
        self.enemy_for("WHITE", 30.0)
        self.tough()
        bystander = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = "enemy_team"
        self.teams._apply_roster()
        self.stand(bystander, 200.0, 200.0)
        bystander.vitals.add_status("slowed", 5.0)
        self.combat.fire_projectile(bystander, SimVec3(600.0, 300.0, 600.0), SimVec3(0.0, 0.0, 1.0),
                                    speed=10.0, reach=500.0, damage=1.0, radius=1.0,
                                    tint=(255, 255, 255, 255), size=.2, force=0.0)
        shot = self.combat.projectiles[0]
        tree = fresh_tree(self.game, minimum=300.0)
        self.combat.elements.ignite_tree(tree)
        tree_health = tree.tree_health
        world, sky = self.game.world, self.game.environment
        with mock.patch.object(world, "update", wraps=world.update) as world_update, \
                mock.patch.object(sky, "update", wraps=sky.update) as sky_update:
            self.tap("3")
            first_world_call = world_update.call_count
            first_sky_call = sky_update.call_count
            self.frames(30)
            self.assertTrue(self.combat.time_stopped)
            for call in world_update.call_args_list[first_world_call:]:
                self.assertEqual(call.args[0], 0.0, "no world time passes")
            for call in sky_update.call_args_list[first_sky_call:]:
                self.assertEqual(call.args[0], 0.0, "wind, waves and clouds stop too")
        self.assertEqual(shot.travelled, 0.0, "projectiles hang in the air")
        self.assertEqual(tree.tree_health, tree_health, "fire stops burning")
        self.assertAlmostEqual(bystander.vitals.statuses["slowed"], 5.0, msg="other timers stop")
        self._run_to_end()
        self.frames(5)
        self.assertGreater(shot.travelled, 0.0, "and everything carries on afterwards")
        self.assertLess(bystander.vitals.statuses["slowed"], 5.0)
        self.assertLess(tree.tree_health, tree_health)
        self.combat.reset_world_state()

    def test_other_keys_cannot_interrupt_or_stack(self):
        self.enemy_for("YELLOW", 30.0)
        self.tough()
        self.tap("3")
        sequence = self.player.motion
        for key in ("1", "2", "3", "4", "r", "q", "="):
            self.game.input(key)
            self.game.input(f"{key} up")
        self.assertIs(self.player.motion, sequence)
        self.assertFalse(self.ability("chest_beam").active)
        self._run_to_end()

    def test_one_punch_and_one_explosion(self):
        self.enemy_for("WHITE", 5.0)
        self.tough()
        with mock.patch.object(self.combat, "hit_character", wraps=self.combat.hit_character) as hits:
            self.tap("3")
            self._run_to_end()
        self.assertEqual(hits.call_count, 2)

    def test_switching_character_mid_sequence_restores_the_world(self):
        self.enemy_for("WHITE", 30.0)
        self.tough()
        self.tap("3")
        self.frames(5)
        self.teams.swap("GREEN", save=False)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(self.enemy.vitals.has("held"))

    def test_a_downed_enemy_is_never_chosen(self):
        self.enemy_for("WHITE", 30.0)
        self.enemy.vitals.downed_for = 5.0
        self.game.elapsed += 1.0
        self.tap("3")
        self.assertFalse(self.combat.time_stopped)
        self.enemy.vitals.downed_for = 0.0

    def test_throwing_soldier_boy_never_makes_him_fly(self):
        self.play("WHITE")
        red = self.place_enemy("RED", 30.0)
        self.tough()
        self.tap("3")
        self._run_to_end()
        self.frames(30)
        self.assertFalse(red.flight.is_flying)
        self.assertIs(red.flight.phase, FlightPhase.GROUNDED)


class GroundExecutionTests(ControlsCase, unittest.TestCase):
    """Superman's key 4, watched frame by frame."""

    def setUp(self):
        super().setUp()
        self.enemy_for("WHITE", 80.0, x=30.0)
        self.tough()
        self.aim_at = SimVec3(0.0, 2000.0, 0.0)  # the camera is pointing nowhere useful

    def _run(self, on_frame=None) -> list:
        """Run to the end and return the phases seen, in order."""
        phases = []
        for _ in range(60 * 25):
            motion = self.player.motion
            if not isinstance(motion, ExecutionSequence):
                break
            if not phases or phases[-1] != motion.phase:
                phases.append(motion.phase)
            if on_frame is not None:
                on_frame(motion)
            self.frames(1)
        return phases

    def test_only_superman_has_it_and_4_starts_it_at_once(self):
        for character_id in ("BLACK", "YELLOW", "GREEN", "RED"):
            self.assertNotIn("ground_execution", self.teams.characters[character_id].powers.abilities)
        self.press("4")
        self.release("4")
        self.assertIsInstance(self.player.motion, ExecutionSequence, "no charge time")
        self.assertTrue(self.combat.time_stopped)
        self.assertEqual(self.ability("ground_execution").hud_state(), "ON")

    def test_the_complete_sequence_in_order_with_real_damage_and_world_damage(self):
        craters = len(self.game.world.terrain_impacts)
        scorches = len(self.combat.elements.scorches)
        self.tap("4")
        phases = self._run()
        self.assertEqual(phases, ["rush", "hold", "lift", "punch", "chase", "regrip", "burn", "fall", "away"])
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assertGreater(len(self.game.world.terrain_impacts), craters, "a real crater")
        self.assertGreater(len(self.combat.elements.scorches), scorches, "real burn marks")
        self.assertFalse(self.combat.time_stopped)
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.game.hud.vision_overlay.enabled)
        self.assertFalse(self.enemy.vitals.has("held"))

    def test_most_of_the_damage_is_the_heat_vision_and_it_follows_the_damage_value(self):
        self.set("ground_execution", "damage", 1000)
        self.tap("4")
        at_landing = {}

        def watch(motion):
            if motion.phase == "burn" and not at_landing:
                at_landing["taken"] = self.enemy.vitals.damage_taken
        self._run(watch)
        low = self.enemy.vitals.damage_taken
        self.assertGreater(low, at_landing["taken"] * 3.0)
        self.stand(self.player, 0.0, 0.0)
        self.stand(self.enemy, 30.0, 80.0)
        self.enemy.vitals.damage_taken = 0.0
        self.set("ground_execution", "damage", 5000)
        self.tap("4")
        self._run()
        self.assertGreater(self.enemy.vitals.damage_taken, low * 4.0)

    def test_nobody_teleports(self):
        self.tap("4")
        speed = self.ability("ground_execution").p("speed")
        last = {}
        worst = {"player": 0.0, "enemy": 0.0}

        def watch(motion):
            for name, body in (("player", self.player), ("enemy", self.enemy)):
                here = (float(body.x), float(body.y), float(body.z))
                if name in last:
                    jump = sum((a - b) ** 2 for a, b in zip(here, last[name])) ** .5
                    if name == "enemy" and motion.phase in ("rush", "fall", "burn", "away"):
                        worst[name] = max(worst[name], jump)
                    if name == "player":
                        worst[name] = max(worst[name], jump)
                last[name] = here
        self._run(watch)
        self.assertLessEqual(worst["player"], speed * FRAME * 1.05)
        self.assertLessEqual(worst["enemy"], 350.0 * FRAME * 1.05 + 3.0)

    def test_the_rush_reaches_the_grab_from_any_distance_and_direction(self):
        """A rounding error once left Superman hovering just out of grab range until the time limit."""
        for x, z in ((0.0, 60.0), (0.0, 37.0), (17.3, 41.9), (-60.0, 0.0), (33.3, -71.7), (5.0, 5.0)):
            self.stand(self.player, 0.0, 0.0)
            self.place_enemy("BLACK", z, x=x)
            self.tough()
            self.tap("4")
            self.seconds(.5)
            self.assertNotEqual(self.player.motion.phase, "rush", f"stuck rushing to {x}, {z}")
            self.player.release_motion()

    def test_low_speed_makes_it_slower_rather_than_breaking_it(self):
        self.set("ground_execution", "speed", 200)
        self.tap("4")
        self.seconds(.1)
        self.assertEqual(self.player.motion.phase, "rush", "80 metres takes a while at 200 m/s")
        self.assertEqual(self._run()[-1], "away")

    def test_the_enemy_cannot_escape_and_the_world_stays_frozen_throughout(self):
        bystander = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = "enemy_team"
        self.teams._apply_roster()
        self.stand(bystander, -400.0, -400.0)
        bystander.vitals.add_status("slowed", 5.0)
        shots_from = SimVec3(600.0, 300.0, 600.0)
        self.combat.fire_projectile(bystander, shots_from, SimVec3(0.0, 0.0, 1.0), speed=10.0, reach=500.0,
                                    damage=1.0, radius=1.0, tint=(255, 255, 255, 255), size=.2, force=0.0)
        shot = self.combat.projectiles[0]
        spot = (float(bystander.x), float(bystander.z))
        world_times = []

        def watch(motion):
            self.assertTrue(self.combat.time_stopped)
            if motion.phase != "rush":
                self.assertTrue(self.enemy.vitals.has("held") or motion.phase == "away", motion.phase)
            self.assertEqual(shot.travelled, 0.0)
            self.assertEqual((float(bystander.x), float(bystander.z)), spot)
            self.assertAlmostEqual(bystander.vitals.statuses["slowed"], 5.0)
            world_times.append(self.game.environment._time)
        self.tap("4")
        with mock.patch.object(self.game.input_manager, "movement", return_value=(SimVec3(0.0, 0.0, 1.0), 0.0)):
            self._run(watch)
        self.assertEqual(len(set(world_times[1:])), 1, "clouds and waves did not move")
        self.frames(5)
        self.assertLess(bystander.vitals.statuses["slowed"], 5.0)
        self.assertGreater(shot.travelled, 0.0, "everything resumes")
        self.assertGreater(self.game.environment._time, world_times[-1])
        self.combat.reset_world_state()

    def test_keys_cannot_start_it_twice_or_interrupt_it(self):
        self.tap("4")
        sequence = self.player.motion
        for key in ("4", "4", "1", "2", "3", "r", "q", "=", "-", "f"):
            self.game.input(key)
            self.game.input(f"{key} up")
            self.assertIs(self.player.motion, sequence, key)
        self.assertFalse(self.ability("heat_vision").active)

    def test_it_ends_safely_when_the_target_is_killed_at_any_stage(self):
        for phase in ("rush", "hold", "lift", "fall", "burn"):
            self.stand(self.player, 0.0, 0.0)
            self.place_enemy("BLACK", 80.0, x=30.0)
            self.tough()
            self.tap("4")
            for _ in range(600):
                if self.player.motion.phase == phase:
                    break
                self.frames(1)
            self.assertEqual(self.player.motion.phase, phase)
            self.combat.hit_character(None, self.enemy, 1e12, PHYSICAL)
            self.assertEqual(self._run()[-1], "away", phase)
            self.assertFalse(self.combat.time_stopped, phase)
            self.assertIsNone(self.player.motion, phase)
            self.assertFalse(self.enemy.vitals.has("held"), phase)
            self.enemy.vitals.downed_for = 0.0
            self.enemy.pose_root.setP(0.0)

    def test_it_ends_safely_when_the_target_leaves_or_changes_sides(self):
        self.tap("4")
        self.frames(3)
        self.teams.state.assignment["BLACK"] = "my_team"
        self.teams._apply_roster()
        self.assertEqual(self._run()[-1], "away")
        self.assertFalse(self.combat.time_stopped)

    def test_a_character_switch_part_way_leaves_nothing_behind(self):
        self.tap("4")
        for _ in range(600):
            if self.player.motion.phase == "burn":
                break
            self.frames(1)
        self.frames(2)
        beam = self.player.motion.beam
        self.assertIsNotNone(beam)
        self.teams.swap("GREEN", save=False)
        self.assertFalse(self.combat.time_stopped)
        self.assertFalse(beam.cores[0].visible, "no beam left hanging")
        self.assertFalse(self.enemy.vitals.has("held"))
        self.frames(5)

    def test_beam_pool_is_returned(self):
        pool = len(self.combat._beams)
        self.tap("4")
        self._run()
        self.assertEqual(len(self.combat._beams), pool)

    def test_a_pause_holds_it_and_it_finishes_afterwards(self):
        self.tap("4")
        self.frames(3)
        self.game.input("escape")
        elapsed = self.player.motion.elapsed
        self.frames(10)
        self.assertEqual(self.player.motion.elapsed, elapsed)
        self.game.input("escape")
        self.assertEqual(self._run()[-1], "away")
        self.assertFalse(self.game.paused)

    def test_a_flying_target_is_brought_down_and_an_obstacle_does_not_stop_it(self):
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.enemy.y += 120.0
        building = object_of(self.game, "Building")
        self.stand(self.player, building.x - 90.0, building.z)
        self.enemy.position = (building.x - 30.0, building.y + abs(building.scale_y), building.z)
        self.tap("4")
        self.assertEqual(self._run()[-1], "away")
        self.assertIs(self.enemy.flight.phase, FlightPhase.GROUNDED)
        self.assertLess(self.enemy.y, self.game.world.height_at(self.enemy.x, self.enemy.z) + 1.0)

    def test_soldier_boy_as_the_target_stays_on_the_ground_afterwards(self):
        red = self.place_enemy("RED", 60.0)
        self.tough()
        self.tap("4")
        self._run()
        self.frames(10)
        self.assertFalse(red.flight.is_flying)
        self.assertLess(red.y, self.game.world.height_at(red.x, red.z) + 1.0)

    def test_control_returns_and_a_second_use_works_straight_away(self):
        self.tap("4")
        self._run()
        self.assertIsNone(self.player.motion)
        self.stand(self.enemy, self.player.x + 20.0, self.player.z)
        self.enemy.vitals.health = self.enemy.vitals.max_health
        self.tap("4")
        self.assertIsInstance(self.player.motion, ExecutionSequence)
        self._run()
        self.assertFalse(self.combat.time_stopped)

    def test_no_enemy_in_range_does_nothing(self):
        self.remove_enemy()
        self.tap("4")
        self.assertIsNone(self.player.motion)
        self.assertFalse(self.combat.time_stopped)


class MassiveBlastTests(ControlsCase, unittest.TestCase):
    def test_it_blasts_once_per_press_centred_on_him(self):
        for character_id in ("YELLOW",):
            self.enemy_for(character_id, 60.0)
            self.tough()
            with mock.patch.object(self.combat, "blast", wraps=self.combat.blast) as blast, \
                    mock.patch.object(self.combat, "hit_character", wraps=self.combat.hit_character) as hits:
                self.ability("massive_blast").press()  # no key of its own now
                self.frames(30)
                self.game.input("4 hold")
                self.game.input("4 up")
                self.frames(5)
            self.assertEqual(blast.call_count, 1, character_id)
            origin = blast.call_args.args[1]
            self.assertAlmostEqual(origin.x, self.player.x, delta=.01)
            self.assertAlmostEqual(origin.z, self.player.z, delta=.01)
            self.assertEqual(hits.call_count, 1, "damage applies once, not every frame")

    def test_full_damage_everywhere_inside_and_range_sets_the_size(self):
        self.enemy_for("YELLOW", 150.0)
        self.tough()
        self.set("massive_blast", "damage", 1000)
        self.ability("massive_blast").press()  # no key of its own now
        self.frames(1)
        far = self.enemy.vitals.damage_taken
        self.assertGreater(far, 0.0)
        self.stand(self.enemy, 0.0, 20.0)
        self.enemy.vitals.damage_taken = 0.0
        self.ability("massive_blast").press()  # no key of its own now
        self.frames(1)
        self.assertAlmostEqual(self.enemy.vitals.damage_taken, far, delta=far * .01)
        self.set("massive_blast", "range", 100)
        self.stand(self.enemy, 0.0, 150.0)
        self.enemy.vitals.damage_taken = 0.0
        self.ability("massive_blast").press()  # no key of its own now
        self.frames(1)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0, "outside the sphere")

    def test_it_destroys_trees_buildings_and_ground(self):
        self.enemy_for("YELLOW", 500.0)
        tree = fresh_tree(self.game, minimum=1.0)
        tree_id = tree.tree_id
        self.stand(self.player, tree.x + 10.0, tree.z)
        self.ability("massive_blast").press()  # no key of its own now
        self.frames(1)
        self.assertTrue(self.game.world.tree_states[tree_id]["destroyed"])
        building = object_of(self.game, "Building")
        self.stand(self.player, building.x - 30.0, building.z)
        craters = len(self.game.world.terrain_impacts)
        self.ability("massive_blast").press()  # no key of its own now
        self.frames(1)
        self.assertTrue(building.health.broken)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)
        self.frames(5)
        self.assertLessEqual(len(self.game.world.debris), self.game.world.debris_budget.maximum_live_pieces)

    def test_allies_are_safe(self):
        self.enemy_for("YELLOW", 60.0)
        ally = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = "my_team"
        self.teams._apply_roster()
        self.stand(ally, 5.0, 5.0)
        ally.vitals.damage_taken = 0.0
        self.tap("4")
        self.assertEqual(ally.vitals.damage_taken, 0.0)

    def test_a_single_blast_does_not_stall_the_game(self):
        self.enemy_for("YELLOW", 500.0)
        started = time.perf_counter()
        self.game.input("4")
        self.game.update(FRAME)
        self.game.input("4 up")
        self.assertLess(time.perf_counter() - started, 1.0, "headless, including felling every tree")


class NoRegressionTests(ControlsCase, unittest.TestCase):
    def test_keys_never_change_graphics_quality(self):
        with mock.patch.object(self.game, "set_quality") as quality:
            for character_id in ROSTER_IDS:
                self.enemy_for(character_id, 300.0)
                for key in ("1", "2", "3", "4", "=", "-", "e", "r"):
                    self.game.input(key)
                    self.game.input(f"{key} up")
                self.player.powers.cancel_all()
                self.player.release_motion()
                self.combat.reset_world_state()
        quality.assert_not_called()

    def test_typing_in_a_menu_field_does_not_trigger_abilities(self):
        self.enemy_for("YELLOW", 30.0)
        self.tough()
        self.game.input("p")
        panel = self.game.power_panel
        panel.begin_edit(panel.card_of("void_form").rows["damage"])
        for key in ("1", "2", "3", "4", "-", "=", "+"):
            self.game.input(key)
        self.game.input("enter")
        self.game.input("p")
        self.assertFalse(self.ability("void_form").active)
        self.assertFalse(self.combat.time_stopped)
        self.assertIsNone(self.player.motion)
        self.assertEqual(self.ability("melee").attacks, 0)

    def test_pause_blocks_new_keys_and_a_time_stop_waits_out_a_pause(self):
        self.enemy_for("WHITE", 30.0)
        self.game.input("escape")
        for key in ("2", "3", "="):
            self.game.input(key)
            self.game.input(f"{key} up")
        self.assertIsNone(self.player.motion)
        self.game.input("escape")
        self.tough()
        self.tap("3")
        self.game.input("escape")
        before = self.player.motion.elapsed
        self.frames(10)
        self.assertEqual(self.player.motion.elapsed, before)
        self.assertTrue(self.combat.time_stopped)
        self.game.input("escape")
        self.player.release_motion()
        self.assertFalse(self.combat.time_stopped)

    def test_flight_keys_are_the_same_for_the_four(self):
        from ursina import held_keys
        for character_id in FLYERS:
            self.enemy_for(character_id, 400.0)
            self.game.input("f")
            self.assertTrue(self.player.flight.is_flying, character_id)
            for key, positive in (("space", True), ("control", False)):
                held_keys[key] = 1
                axis = self.game.input_manager.movement(flying=True)[1]
                held_keys[key] = 0
                self.assertEqual(axis > 0.0, positive, f"{character_id} {key}")
            self.game.input("f")
            self.frames(1)


if __name__ == "__main__":
    unittest.main()
