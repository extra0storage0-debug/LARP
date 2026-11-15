"""The overhaul of keys 1 and 4, on the real game loop: every stage, every exact time, and the cleaning up."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from panda3d.core import ShaderAttrib
from ursina import held_keys

from ai.combat_ai import CINEMATIC_IDS, MOVES
from characters.squad import Puppet
from config.character_roster import ENEMY_TEAM, MY_TEAM
from config.power_schema import PLAYER_ONLY_ABILITIES
from config.power_schema import SCHEMA, SLOT_ABILITIES, SQUAD_KEYS, PowerSettings, params_of
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers import homelander, omni_man, soldier_boy_attacks, superman, void
from powers.aiming import center_of
from powers.common import LaunchedMotion
from powers.homelander import NeckLaserExecution
from powers.omni_man import TripleImpactExecution
from powers.soldier_boy_attacks import RadioactiveExecution
from powers.superman import ExecutionSequence
from powers.void import GROUND_SHADOW_SHADER, SHADOW_SHADER, VoidNuclearExecution, is_black, is_ground_shadow
from test_gameplay_control_update import LiveCase


class OverhaulCase(LiveCase):
    def fight(self, player: str, enemy: str = None, distance: float = 40.0, ai_powers: bool = False):
        enemy = enemy or ("WHITE" if player != "WHITE" else "BLACK")
        self.begin(player, enemy, distance, ai_powers=ai_powers)
        self.tough(self.player, 1e7)
        self.tough(self.enemy, 1e7)
        self.enemy._ai_next_attack = 1e9  # not in this first frame, before the test has said what it wants
        self.enemy._end_ai_move()
        self.frames(1)

    def tap(self, key: str) -> None:
        self.game.input(key)
        self.game.input(f"{key} up")

    def run_through(self, motion, limit: float = 60.0, watch=None) -> float:
        """Until it ends; returns how long it took, in seconds of game time."""
        frames = 0
        for _ in range(round(limit / FRAME)):
            if self.player.motion is not motion:
                return frames * FRAME
            if watch is not None:
                watch()
            self.game.update(FRAME)
            frames += 1
        self.fail(f"still running after {limit} s, in {getattr(motion, 'phase', '?')}")

    def durations(self, motion, limit: float = 60.0) -> dict:
        """How long the sequence spent in each stage."""
        spent: dict = {}

        def watch():
            spent[motion.phase] = spent.get(motion.phase, 0.0) + FRAME

        self.run_through(motion, limit, watch)
        return spent

    def assert_no_leftovers(self) -> None:
        self.assertEqual(self.player.motion, None)
        self.assertFalse(self.combat.time_stopped)
        self.assertEqual(len(self.combat._beams), self.beams_free, "every beam is back in the pool")
        for pool in self.teams._puppets.values():
            for puppet in pool:
                self.assertTrue(puppet.parked, "no clone left in the world")
        self.assertFalse(self.enemy.vitals.has("held"))
        self.assertFalse(self.enemy.vitals.has("restrained"))


class RegistryTests(unittest.TestCase):
    def test_the_keys_are_the_new_ones_and_two_three_t_are_not_touched(self):
        self.assertEqual(SLOT_ABILITIES["YELLOW"], {"1": "void_form", "2": "high_speed_attack", "3": "time_stop",
                                                    "4": "void_nuclear_execution"})
        self.assertEqual(SLOT_ABILITIES["RED"], {"1": "radiation_blast", "2": "flying_punch", "3": "aerial_grab_blast",
                                                 "4": "radioactive_execution"})
        self.assertEqual(SLOT_ABILITIES["WHITE"]["1"], "heat_vision")
        self.assertEqual(SLOT_ABILITIES["BLACK"]["1"], "laser_vision")
        self.assertEqual(SLOT_ABILITIES["GREEN"]["4"], "speed_execution")

    def test_ai_knows_every_card_and_the_long_attacks_are_paced(self):
        for character_id, cards in SCHEMA.items():
            self.assertEqual({move.ability_id for move in MOVES[character_id]},
                             {card.ability_id for card in cards} - PLAYER_ONLY_ABILITIES[character_id], character_id)
        self.assertLessEqual({"high_speed_attack", "flying_punch"}, CINEMATIC_IDS)

    def test_soldier_boys_blast_defaults_to_exactly_1000(self):
        self.assertEqual(params_of("RED", "radiation_blast")["damage"].default, 1000.0)


class SupermanTests(OverhaulCase):
    def test_every_stage_in_order_in_a_stopped_world_with_real_damage(self):
        self.fight("WHITE", "BLACK")
        self.tap("4")
        motion = self.player.motion
        self.assertIsInstance(motion, ExecutionSequence)
        self.assertTrue(self.combat.time_stopped, "time stop, on the player's key")
        self.assertIs(self.combat.time_stop_owner, self.player)
        before = self.enemy.vitals.damage_taken
        heat, flown = [], []
        real = self.combat.hit_character

        def spy(source, target, amount, kind="physical", *args, **kwargs):
            heat.append(kind)
            return real(source, target, amount, kind, *args, **kwargs)

        with mock.patch.object(self.combat, "hit_character", spy):
            def watch():
                if motion.phase == superman.CHASE and isinstance(self.enemy.motion, LaunchedMotion):
                    flown.append((float(self.enemy.x), float(self.enemy.y), float(self.enemy.z)))
            self.run_through(motion, watch=watch)
        self.assertEqual(motion.stages, ["rush", "hold", "lift", "punch", "chase", "regrip", "burn", "fall", "away"])
        self.assertGreater(motion.caught_above, 1.0, "caught before reaching the ground")
        self.assertGreater(self.enemy.vitals.damage_taken, before)
        self.assertIn("heat", heat)
        self.assertIn("physical", heat)
        self.assertGreater(len(set(flown)), 3, "it really flew")
        self.assert_no_leftovers()

    def test_the_impact_breaks_the_ground_and_control_comes_back(self):
        self.fight("WHITE", "BLACK")
        craters = len(self.game.world.terrain_impacts)
        self.tap("4")
        self.run_through(self.player.motion)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)
        floor = self.game.world.height_at(self.enemy.x, self.enemy.z) + .25
        self.assertAlmostEqual(float(self.enemy.y), floor, delta=1.0)
        self.tap("1")
        self.assertTrue(self.player.powers.abilities["heat_vision"].active, "and his Heat Vision is still key 1")
        self.tap("1")

    def test_it_goes_for_the_locked_enemy_over_a_nearer_one(self):
        self.fight("WHITE", "BLACK", 100.0)
        nearer = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(nearer, 0.0, 10.0)
        self.tough(nearer, 1e7)
        self.combat.targets.manual = self.enemy
        self.tap("4")
        self.assertIs(self.player.motion.target, self.enemy)
        self.player.release_motion()
        self.combat.targets.manual = None
        self.assert_no_leftovers()

    def test_the_target_dying_at_any_stage_leaves_nothing_behind(self):
        for stage in ("hold", "punch", "chase", "burn", "fall"):
            with self.subTest(stage):
                self.fight("WHITE", "BLACK")
                self.tap("4")
                motion = self.player.motion
                for _ in range(round(30.0 / FRAME)):
                    if motion.phase == stage:
                        break
                    self.game.update(FRAME)
                self.assertEqual(motion.phase, stage)
                self.combat.hit_character(None, self.enemy, 1e12)
                self.run_through(motion)
                self.assert_no_leftovers()
                self.enemy.vitals.downed_for = 0.0
                self.enemy.vitals.health = self.enemy.vitals.max_health


class HomelanderTests(OverhaulCase):
    def test_exactly_four_clones_and_the_exact_times(self):
        self.fight("BLACK", "WHITE")
        self.tap("4")
        motion = self.player.motion
        self.assertIsInstance(motion, NeckLaserExecution)
        self.assertFalse(self.combat.time_stopped, "his has never stopped time")
        out = set()

        def watch():
            if motion.phase in (homelander.CLONES, homelander.JUGGLE):
                self.assertEqual(len(motion.clones), homelander.CLONE_COUNT)
                out.update(motion.clones)
                for clone in motion.clones:
                    self.assertFalse(clone.parked)
                    self.assertIsInstance(clone, Puppet)

        spent: dict = {}

        def both():
            spent[motion.phase] = spent.get(motion.phase, 0.0) + FRAME
            watch()

        self.run_through(motion, watch=both)
        self.assertEqual(len(out), 4)
        self.assertEqual(motion.stages, ["rush", "lift", "laser", "clones", "regrab", "juggle", "fall", "after"])
        self.assertAlmostEqual(spent["laser"], 4.0, delta=FRAME * 2)
        self.assertAlmostEqual(spent["clones"], 3.0, delta=FRAME * 2)
        self.assertAlmostEqual(spent["juggle"], 2.0, delta=FRAME * 2)
        self.assertGreater(motion.clone_hits, 10, "they really attack")
        self.assertEqual(motion.bounces, 4)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.assert_no_leftovers()
        self.assertEqual(len(self.teams._puppets["BLACK"]), 4, "built once")

    def test_again_uses_the_same_four(self):
        self.fight("BLACK", "WHITE")
        self.tap("4")
        self.run_through(self.player.motion)
        pool = list(self.teams._puppets["BLACK"])
        self.stand(self.enemy, 0.0, 40.0)
        self.stand(self.player, 0.0, 0.0)
        self.tap("4")
        self.tap("4")  # a second press while it runs starts nothing
        self.run_through(self.player.motion)
        self.assertEqual(self.teams._puppets["BLACK"], pool)

    def test_clones_are_not_in_the_world_for_anyone_to_hit_or_target(self):
        self.fight("BLACK", "WHITE")
        self.tap("4")
        motion = self.player.motion
        for _ in range(round(30.0 / FRAME)):
            if motion.phase == homelander.CLONES:
                break
            self.game.update(FRAME)
        for clone in motion.clones:
            self.assertNotIn(clone, self.combat.in_world)
            self.assertIsNone(clone.collider)
        self.assertNotIn(self.player, self.combat.hostiles_of(self.player))
        self.player.release_motion()
        self.assert_no_leftovers()

    def test_only_his_enemy_takes_damage_from_the_clones(self):
        self.fight("BLACK", "WHITE")
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        ally = self.teams.characters["GREEN"]
        self.stand(ally, 3.0, 40.0)
        self.tough(ally)
        ally.vitals.add_status("frozen", 60.0)
        self.tap("4")
        self.run_through(self.player.motion)
        self.assertEqual(ally.vitals.damage_taken, 0.0)
        self.assertEqual(self.player.vitals.damage_taken, 0.0)

    def test_cut_short_during_the_clones_they_all_go(self):
        for way in ("target down", "character switch"):
            with self.subTest(way):
                self.fight("BLACK", "WHITE")
                self.teams.state.assignment["YELLOW"] = MY_TEAM
                self.teams._apply_roster()
                self.tap("4")
                motion = self.player.motion
                for _ in range(round(30.0 / FRAME)):
                    if motion.phase == homelander.CLONES:
                        break
                    self.game.update(FRAME)
                self.assertEqual(len(motion.clones), 4)
                if way == "target down":
                    self.combat.hit_character(None, self.enemy, 1e12)
                    self.frames(2)
                else:
                    self.teams.swap("YELLOW", save=False)
                    self.frames(2)
                for clone in self.teams._puppets["BLACK"]:
                    self.assertTrue(clone.parked)
                self.enemy.vitals.downed_for = 0.0
                self.enemy.vitals.health = self.enemy.vitals.max_health


class VoidFormTests(OverhaulCase):
    def on(self):
        self.fight("YELLOW", "WHITE")
        self.void = self.player.powers.abilities["void_form"]
        self.tap("1")
        self.assertTrue(self.void.active)

    def test_it_toggles_and_leaves_nothing_black(self):
        self.on()
        self.assertTrue(is_black(self.player))
        self.frames(5)
        self.assertTrue(is_ground_shadow(self.enemy))
        self.tap("1")
        self.assertFalse(self.void.active)
        self.assertFalse(is_black(self.player))
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertFalse(self.enemy.vitals.immobile)

    def test_the_whole_cycle_on_the_simulation_clock(self):
        """Run for real, 71 seconds of it, noting what both of them are at every frame."""
        self.on()
        self.frames(1)
        looks = []
        x = float(self.enemy.x)
        for _ in range(round(71.0 / FRAME)):
            self.game.update(FRAME)
            vitals = self.enemy.vitals
            look = ("shadow" if is_ground_shadow(self.enemy) else "black" if is_black(self.enemy) else "normal",
                    is_black(self.player), vitals.has("restrained"), vitals.has("weakened"))
            if not looks or looks[-1][1] != look:
                looks.append((self.void.cycle, look, vitals.damage_taken))
                x = float(self.enemy.x)
            if look[0] == "shadow":
                self.assertTrue(vitals.immobile)
                self.assertFalse(self.enemy.powers.abilities["heat_vision"].usable(quiet=True))
                self.assertAlmostEqual(float(self.enemy.x), x, delta=.01)
        self.assertEqual([look[1] for look in looks[:4]],
                         [("shadow", True, True, False), ("black", False, False, True),
                          ("shadow", True, True, False), ("black", False, False, True)], looks)
        self.assertAlmostEqual(looks[1][0], 10.0, delta=FRAME * 2)
        self.assertAlmostEqual(looks[2][0], 60.0, delta=FRAME * 2)
        self.assertAlmostEqual(looks[3][0], 70.0, delta=FRAME * 2)
        self.assertEqual(looks[1][2], 0.0, "no damage in the first part")
        self.assertGreater(looks[2][2], 0.0, "real damage in the second")
        self.tap("1")

    def test_dark_effects_show_on_the_enemy_only_while_it_is_being_hurt(self):
        self.on()
        self.frames(2)
        points = []
        real = self.combat.puffs.emit

        def spy(point, *args, **kwargs):
            points.append(point)
            return real(point, *args, **kwargs)

        def near_enemy() -> int:
            center = center_of(self.enemy)
            return sum((point - center).length() < 4.0 for point in points)

        self.player.position = (float(self.player.x), float(self.player.y), float(self.player.z) - 200.0)
        with mock.patch.object(self.combat.puffs, "emit", spy):
            self.frames(30)
            self.assertEqual(near_enemy(), 0, "as a shadow on the ground there is nothing around it")
            self.void.cycle = 20.0
            self.frames(30)
            self.assertGreater(near_enemy(), 5)
        self.tap("1")

    def test_black_is_the_body_in_the_world_and_it_can_be_run_into(self):
        self.on()
        self.frames(1)
        self.void.cycle = 20.0
        self.frames(2)
        self.assertTrue(is_black(self.enemy))
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertFalse(self.enemy.collider.node_path.isStashed())
        self.tap("1")
        self.assertFalse(is_black(self.enemy))

    def test_the_cycle_repeats_every_sixty_seconds(self):
        self.on()
        self.frames(2)
        self.void.cycle = 30.0
        self.frames(2)
        self.assertFalse(self.enemy.vitals.has("restrained"))
        self.void.cycle = 59.95
        self.frames(10)
        self.assertTrue(self.enemy.vitals.has("restrained"), "the second cycle has begun")
        self.assertLess(self.void.cycle % 60.0, 1.0)

    def test_a_weakened_enemy_hits_for_less(self):
        self.on()
        self.frames(2)
        self.void.cycle = 20.0
        self.frames(2)
        self.assertTrue(self.enemy.vitals.has("weakened"))
        health = self.player.vitals.health
        self.combat.hit_character(self.enemy, self.player, 100.0)
        weak = health - self.player.vitals.health
        self.enemy.vitals.clear_status("weakened")
        health = self.player.vitals.health
        self.combat.hit_character(self.enemy, self.player, 100.0)
        self.assertLess(weak, health - self.player.vitals.health)

    def test_it_never_touches_a_friend(self):
        self.fight("YELLOW", "WHITE")
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        ally = self.teams.characters["GREEN"]
        self.stand(ally, 3.0, 3.0)
        self.tough(ally)
        self.tap("1")
        self.seconds(6.0)
        self.assertFalse(is_ground_shadow(ally))
        self.assertEqual(ally.vitals.damage_taken, 0.0)
        self.assertFalse(ally.vitals.has("restrained"))

    def test_when_the_enemy_goes_down_it_is_itself_again_and_the_next_one_gets_it(self):
        self.fight("YELLOW", "WHITE")
        second = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(second, 0.0, 300.0)
        self.tough(second, 1e7)
        void_form = self.player.powers.abilities["void_form"]
        self.tap("1")
        self.frames(3)
        first = void_form.subject
        self.assertIs(first, self.enemy)
        self.combat.hit_character(None, first, 1e12)
        self.frames(3)
        self.assertFalse(is_ground_shadow(first))
        self.assertIs(void_form.subject, second)
        self.assertTrue(is_ground_shadow(second))
        self.tap("1")
        self.assertFalse(is_ground_shadow(second))
        first.vitals.downed_for = 0.0
        first.vitals.health = first.vitals.max_health

    def test_a_new_manual_lock_moves_it_cleanly(self):
        self.fight("YELLOW", "WHITE")
        second = self.teams.characters["GREEN"]
        self.teams.state.assignment["GREEN"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(second, 0.0, 300.0)
        self.tough(second, 1e7)
        self.tap("1")
        self.frames(3)
        self.combat.targets.manual = second
        self.frames(3)
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertFalse(self.enemy.vitals.has("restrained"))
        self.assertTrue(is_ground_shadow(second))
        self.combat.targets.manual = None
        self.tap("1")

    def test_a_character_switch_ends_it_with_nobody_left_black(self):
        self.on()
        self.frames(2)
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        sentry = self.player
        self.teams.swap("GREEN", save=False)
        self.frames(2)
        self.assertFalse(is_black(sentry))
        self.assertFalse(is_ground_shadow(self.enemy))


class GroundShadowTests(OverhaulCase):
    def on(self, distance: float = 40.0):
        self.fight("YELLOW", "WHITE", distance)
        self.void = self.player.powers.abilities["void_form"]
        self.shader_before = self.enemy.pose_root.getAttrib(ShaderAttrib)
        self.tap("1")
        self.frames(2)
        self.assertIs(self.void.subject, self.enemy)

    def test_sentry_is_black_all_over_and_the_enemy_is_only_a_shadow(self):
        self.on()
        self.assertEqual(self.player.pose_root.getShader(), SHADOW_SHADER._shader)
        self.assertEqual(self.enemy.pose_root.getShader(), GROUND_SHADOW_SHADER._shader)
        self.assertFalse(is_black(self.enemy), "no black figure either")
        self.assertFalse(is_ground_shadow(self.player))

    def test_it_comes_back_exactly_as_it_was(self):
        self.on()
        health = self.enemy.vitals.health
        self.tap("1")
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertEqual(self.enemy.pose_root.getAttrib(ShaderAttrib), self.shader_before)
        self.assertFalse(self.enemy.pose_root.node().isFinal())
        self.assertEqual(self.enemy.pose_root.getTransparency(), 0)
        self.assertEqual(self.enemy.vitals.health, health)
        self.assertFalse(self.enemy.vitals.immobile)
        self.assertNotIn(self.enemy, self.teams.ground_shadows)
        self.assertFalse(self.enemy.collider.node_path.isStashed())

    def test_no_invisible_collision_while_it_lasts_and_the_real_one_after(self):
        self.on()
        self.assertTrue(self.enemy.collider.node_path.isStashed())
        self.frames(1)
        self.tap("1")
        self.assertFalse(self.enemy.collider.node_path.isStashed())

    def test_the_ground_it_lies_on_follows_the_body_while_it_moves(self):
        self.on()
        self.enemy.position = (float(self.enemy.x) + 700.0, float(self.enemy.y), float(self.enemy.z) + 500.0)
        self.frames(1)
        x, z = float(self.enemy.x), float(self.enemy.z)
        ground = self.enemy.pose_root.getShaderInput("u_ground").getVector()
        world_height = self.game.world.height_at(x, z)
        self.assertAlmostEqual(ground[0] * x + ground[1] * z + ground[2], world_height, delta=.2)
        self.tap("1")

    def test_a_flying_enemy_leaves_its_shadow_on_the_ground_and_is_held_up_there(self):
        self.fight("YELLOW", "WHITE")
        floor = self.game.world.height_at(self.enemy.x, self.enemy.z)
        self.enemy.position = (float(self.enemy.x), floor + 90.0, float(self.enemy.z))
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.tap("1")
        self.frames(3)
        y = float(self.enemy.y)
        self.seconds(1.0)
        self.assertTrue(is_ground_shadow(self.enemy))
        self.assertAlmostEqual(float(self.enemy.y), y, delta=1.0)
        self.tap("1")
        self.assertFalse(is_ground_shadow(self.enemy))

    def test_it_takes_damage_as_a_shadow_and_going_down_brings_it_back(self):
        self.on()
        self.void.cycle = 20.0
        self.seconds(1.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "its damage is real, and is kept")
        self.combat.hit_character(None, self.enemy, 1e12)
        self.frames(2)
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertFalse(is_black(self.enemy))
        self.assertFalse(self.enemy.collider.node_path.isStashed())
        self.enemy.vitals.downed_for = 0.0
        self.enemy.vitals.health = self.enemy.vitals.max_health
        self.tap("1")

    def test_it_leaving_the_world_or_sentry_leaving_the_world_ends_it(self):
        self.on()
        self.teams.state.assignment["WHITE"] = "available"
        self.teams._apply_roster()
        self.frames(2)
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertEqual(self.teams.ground_shadows, set())

    def test_a_player_taken_by_ai_sentry_gets_their_body_and_keys_back(self):
        self.fight("WHITE", "YELLOW", 40.0, ai_powers=True)
        self.enemy.powers.abilities["void_form"].press()
        self.frames(3)
        self.assertTrue(is_ground_shadow(self.player))
        self.tap("1")
        self.assertFalse(self.player.powers.abilities["heat_vision"].active, "no attacks in the ten seconds")
        self.enemy.powers.abilities["void_form"].cancel()
        self.assertFalse(is_ground_shadow(self.player))
        self.frames(1)
        self.tap("1")
        self.assertTrue(self.player.powers.abilities["heat_vision"].active)
        self.tap("1")

    def test_key_four_is_exactly_five_seconds_of_shadow_and_then_the_body_is_back(self):
        self.fight("YELLOW", "WHITE")
        self.tap("4")
        motion = self.player.motion
        state = {}

        def watch():
            if motion.phase == void.VOID:
                state["void"] = is_ground_shadow(self.enemy)
            if motion.phase == void.COPY:
                state["copy"] = is_ground_shadow(self.enemy)

        self.run_through(motion, watch=watch)
        self.assertEqual(state, {"void": True, "copy": False})
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertFalse(self.enemy.collider.node_path.isStashed())


class SoldierBoyRunTests(OverhaulCase):
    def race(self, body, steer) -> list:
        speeds = []
        for _ in range(round(1.0 / FRAME)):
            steer()
            self.game.update(FRAME)
            speeds.append(body.ground.velocity.length())
        return speeds

    def test_the_player_is_at_top_speed_almost_at_once_and_faster_than_anyone_flies(self):
        self.fight("RED", "BLACK", 3000.0)
        held_keys["w"] = held_keys["shift"] = 1
        speeds = self.race(self.player, lambda: None)
        held_keys["w"] = held_keys["shift"] = 0
        top = self.player.ground.max_running_speed
        reached = next(index for index, speed in enumerate(speeds) if speed >= top * .95) + 1
        self.assertLessEqual(reached * FRAME, .2, f"95% of {top:.0f} m/s in {reached * FRAME:.2f} s")
        self.assertGreater(speeds[0], top * .2, "from the very first frame")
        for earlier, later in zip(speeds, speeds[1:]):
            self.assertGreaterEqual(later, earlier - 1e-3, "smooth: it only ever rises")
        for body in self.teams.characters.values():
            if body.kit.can_fly:
                self.assertGreater(top, body.flight.config.boost_speed, body.character_id)
        self.assertFalse(self.player.flight.is_flying)

    def test_he_stops_and_turns_as_quickly(self):
        self.fight("RED", "BLACK", 3000.0)
        held_keys["w"] = held_keys["shift"] = 1
        self.seconds(.5)
        held_keys["w"] = 0
        held_keys["s"] = 1
        self.seconds(.25)
        held_keys["s"] = held_keys["shift"] = 0
        self.assertLess(self.player.ground.velocity.z, 0.0, "already going the other way")
        self.seconds(.6)
        self.assertLess(self.player.ground.velocity.length(), self.player.ground.max_running_speed * .05)

    def test_ai_soldier_boy_has_it_too(self):
        self.fight("WHITE", "RED", 3000.0)
        ground = self.enemy.ground
        self.game.update(FRAME)
        self.assertGreaterEqual(ground.acceleration, ground.max_running_speed * 20.0)

    def test_nobody_else_and_no_stat_changes(self):
        self.fight("RED", "BLACK", 3000.0)
        for character_id in ("WHITE", "BLACK", "YELLOW", "GREEN"):
            body = self.teams.characters[character_id]
            self.assertIsNone(body.ground.air_acceleration)
            self.assertLess(body.ground.acceleration, body.ground.max_running_speed * 20.0)

    def test_the_air_is_as_it_was(self):
        self.fight("RED", "BLACK", 3000.0)
        self.game.update(FRAME)
        ground = self.player.ground
        self.assertAlmostEqual(ground.air_acceleration, ground.max_running_speed * 1.2, delta=1.0)


class VoidExecutionTests(OverhaulCase):
    def test_every_stage_with_exact_times_one_copy_and_nothing_left(self):
        self.fight("YELLOW", "WHITE")
        self.tap("4")
        motion = self.player.motion
        self.assertIsInstance(motion, VoidNuclearExecution)
        self.assertFalse(self.combat.time_stopped)
        spent: dict = {}
        blacks = {}
        copies = set()
        places = set()
        craters = len(self.game.world.terrain_impacts)

        def watch():
            phase = motion.phase
            spent[phase] = spent.get(phase, 0.0) + FRAME
            if phase == void.VOID and self.player.motion is motion:
                blacks.setdefault("self", is_black(self.player))
                blacks.setdefault("enemy", is_ground_shadow(self.enemy))
                self.assertTrue(self.enemy.vitals.immobile)
            if phase == void.COPY:
                self.assertFalse(is_black(self.player), "he is himself again")
                copies.add(motion.copy)
                self.assertTrue(is_black(motion.copy))
                places.add((round(float(motion.copy.x), 1), round(float(motion.copy.z), 1)))

        before = self.enemy.vitals.damage_taken
        self.run_through(motion, watch=watch)
        self.assertEqual(motion.stages, ["rush", "grip", "lift", "nuke", "fall", "void", "copy", "charge", "lift_again",
                                         "fall_again", "after"])
        self.assertAlmostEqual(spent["void"], 5.0, delta=FRAME * 2)
        self.assertAlmostEqual(spent["copy"], 5.0, delta=FRAME * 2)
        self.assertEqual(blacks, {"self": True, "enemy": True})
        self.assertEqual(len(copies), 1, "one copy")
        self.assertGreater(len(places), 8, "it really moves from place to place")
        self.assertGreaterEqual(motion.copy_hits, 13)
        self.assertGreater(self.enemy.vitals.damage_taken, before)
        self.assertGreaterEqual(len(self.game.world.terrain_impacts), craters + 2, "both landings break the ground")
        self.assertFalse(is_black(self.player))
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertEqual(len(self.teams._puppets["YELLOW"]), 1)
        for bubble in self.player.powers.abilities["void_nuclear_execution"].charges:
            self.assertTrue(bubble.entity.isHidden() or not bubble.entity.enabled)
        self.assert_no_leftovers()

    def test_the_charges_are_on_the_enemy_only_after_the_copy_and_until_the_last_explosion(self):
        self.fight("YELLOW", "WHITE")
        self.tap("4")
        motion = self.player.motion
        seen = {}

        def watch():
            seen.setdefault(motion.phase, motion.charges_on)
            seen[motion.phase] = seen[motion.phase] or motion.charges_on

        self.run_through(motion, watch=watch)
        self.assertFalse(seen["copy"])
        self.assertTrue(seen["lift_again"])
        self.assertTrue(seen["fall_again"])
        self.assertFalse(motion.charges_on)

    def test_with_void_form_on_he_stays_void_afterwards(self):
        self.fight("YELLOW", "WHITE")
        self.tap("1")
        self.frames(2)
        self.tap("4")
        self.run_through(self.player.motion)
        self.assertTrue(self.player.powers.abilities["void_form"].active)
        self.frames(2)
        self.tap("1")
        self.assertFalse(is_black(self.player))
        self.assertFalse(is_ground_shadow(self.enemy))
        self.assertFalse(is_black(self.enemy))

    def test_cut_short_at_any_stage_it_cleans_up(self):
        for stage in ("lift", "fall", "void", "copy", "fall_again"):
            with self.subTest(stage):
                self.fight("YELLOW", "WHITE")
                self.tap("4")
                motion = self.player.motion
                for _ in range(round(40.0 / FRAME)):
                    if motion.phase == stage:
                        break
                    self.game.update(FRAME)
                self.assertEqual(motion.phase, stage)
                self.combat.hit_character(None, self.enemy, 1e12)
                self.frames(2)
                self.assertIsNone(self.player.motion)
                self.assertFalse(is_black(self.player))
                self.assertFalse(is_ground_shadow(self.enemy))
                self.assertFalse(motion.charges_on)
                self.assert_no_leftovers()
                self.enemy.vitals.downed_for = 0.0
                self.enemy.vitals.health = self.enemy.vitals.max_health


class RadiationBlastTests(OverhaulCase):
    def on(self, distance: float = 30.0):
        self.fight("RED", "WHITE", distance)
        self.blast = self.player.powers.abilities["radiation_blast"]
        self.enemy.vitals.resistance = 0.0
        self.enemy.vitals.add_status("frozen", 600.0)
        self.tap("1")
        self.assertTrue(self.blast.active)

    def test_exactly_1000_every_exactly_three_seconds(self):
        self.on()
        times = []
        amounts = []
        real = self.combat.blast

        def spy(source, origin, radius, damage, *args, **kwargs):
            times.append(self.game.elapsed)
            amounts.append(damage)
            self.assertGreater(radius, 50.0, "a large blast")
            self.assertTrue(kwargs["even_damage"])
            return real(source, origin, radius, damage, *args, **kwargs)

        with mock.patch.object(self.combat, "blast", spy):
            self.seconds(9.5)
        self.assertEqual(len(times), 4, "at once, then 3, 6 and 9 seconds later")
        for earlier, later in zip(times, times[1:]):
            self.assertAlmostEqual(later - earlier, 3.0, delta=FRAME * 1.5)
        self.assertEqual(set(amounts), {1000.0})
        self.assertAlmostEqual(self.enemy.vitals.damage_taken, 4000.0, delta=1.0, msg="really dealt, at no resistance")

    def test_it_stops_when_toggled_off_and_toggling_cannot_make_it_faster(self):
        self.on()
        self.frames(1)
        self.assertEqual(self.blast.blasts, 1)
        for _ in range(20):
            self.tap("1")
            self.frames(1)
        self.assertEqual(self.blast.blasts, 1, "still only the one")
        if self.blast.active:
            self.tap("1")
        count = self.blast.blasts
        self.seconds(7.0)
        self.assertEqual(self.blast.blasts, count, "off is off")

    def test_no_recoil_and_he_keeps_walking(self):
        self.on()
        self.frames(1)
        where = (float(self.player.x), float(self.player.z))
        self.seconds(3.5)
        self.assertLess(((float(self.player.x) - where[0]) ** 2 + (float(self.player.z) - where[1]) ** 2) ** .5, .05)
        self.assertEqual(self.player.knock.length(), 0.0)
        self.assertTrue(self.player.powers.braced)
        z = float(self.player.z)
        from ursina import held_keys
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertGreater(float(self.player.z), z + 1.0)
        self.assertFalse(self.player.flight.is_flying)

    def test_it_throws_enemies_and_breaks_the_world(self):
        self.fight("RED", "WHITE", 30.0)
        self.tough(self.enemy, 1e7)
        craters = len(self.game.world.terrain_impacts)
        self.tap("1")
        self.frames(2)
        self.assertGreater(len(self.game.world.terrain_impacts), craters)
        self.assertGreater(self.enemy.moving_velocity.length(), 0.0)

    def test_friends_are_safe(self):
        self.fight("RED", "WHITE", 300.0)
        self.teams.state.assignment["GREEN"] = MY_TEAM
        self.teams._apply_roster()
        ally = self.teams.characters["GREEN"]
        self.stand(ally, 5.0, 5.0)
        self.tough(ally)
        self.tap("1")
        self.seconds(4.0)
        self.assertEqual(ally.vitals.damage_taken, 0.0)

    def test_it_waits_during_his_own_sequences(self):
        self.on()
        self.frames(1)
        count = self.blast.blasts
        self.enemy.vitals.clear_status("frozen")
        self.tap("2")
        self.assertIsNotNone(self.player.motion)
        motion = self.player.motion
        self.run_through(motion)
        self.assertEqual(self.blast.blasts, count, "not on top of a sequence")
        self.assertTrue(self.blast.active, "and it is still on")


class SoldierBoyExecutionTests(OverhaulCase):
    def test_every_stage_in_order_never_flying_and_the_beam_from_the_chest(self):
        self.fight("RED", "WHITE")
        self.tap("4")
        motion = self.player.motion
        self.assertIsInstance(motion, RadioactiveExecution)
        self.assertTrue(self.combat.time_stopped)
        nukes = []
        origins = []
        real = self.combat.blast
        chest = self.player.powers.abilities["chest_beam"]
        real_origin = chest.beam_origin

        def spy(source, origin, radius, damage, *args, **kwargs):
            nukes.append((motion.phase, kwargs.get("even_damage", False)))
            return real(source, origin, radius, damage, *args, **kwargs)

        def record():
            point = real_origin()
            origins.append(point)
            return point

        craters = len(self.game.world.terrain_impacts)
        before = self.enemy.vitals.damage_taken

        def watch():
            self.assertFalse(self.player.flight.is_flying, "a jump, never flight")

        with mock.patch.object(self.combat, "blast", spy), mock.patch.object(chest, "beam_origin", record):
            self.run_through(motion, 80.0, watch)
        self.assertEqual(motion.stages, ["jump", "approach", "grip", "lift", "slam", "regrab", "lift", "slam", "regrab", "lift",
                                         "punch", "position", "catch", "beam", "thrown_down", "descend", "aftermath"])
        self.assertEqual(motion.slams, 2)
        self.assertEqual(sum(1 for _phase, even in nukes if even), 2, "two nuclear spheres")
        self.assertEqual(nukes[-1][0], "thrown_down", "and the final ground impact last")
        self.assertGreater(len(origins), 10)
        self.assertGreater(self.enemy.vitals.damage_taken, before)
        self.assertGreaterEqual(len(self.game.world.terrain_impacts), craters + 3)
        self.assertAlmostEqual(float(self.player.y) - self.game.world.height_at(self.player.x, self.player.z), .25, delta=1.5)
        self.assert_no_leftovers()

    def test_the_jump_is_extremely_high_and_reaches_a_flying_enemy(self):
        self.fight("RED", "WHITE")
        floor = self.game.world.height_at(self.enemy.x, self.enemy.z)
        self.enemy.position = (float(self.enemy.x), floor + 200.0, float(self.enemy.z))
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.tap("4")
        motion = self.player.motion
        self.assertGreaterEqual(motion.peak.y - float(self.player.y), 150.0)
        self.run_through(motion, 80.0)
        self.assertGreaterEqual(motion.slams, 2)

    def test_key_three_still_jumps_as_it_did(self):
        self.assertEqual(soldier_boy_attacks.AerialGrabBlast.jump_height, soldier_boy_attacks.JUMP_HEIGHT)

    def test_the_target_going_down_at_any_stage_ends_it_safely(self):
        for stage in ("slam", "punch", "position", "beam", "thrown_down"):
            with self.subTest(stage):
                self.fight("RED", "WHITE")
                self.tap("4")
                motion = self.player.motion
                for _ in range(round(50.0 / FRAME)):
                    if motion.phase == stage:
                        break
                    self.game.update(FRAME)
                self.assertEqual(motion.phase, stage)
                self.combat.hit_character(None, self.enemy, 1e12)
                self.run_through(motion, 30.0)
                self.assert_no_leftovers()
                self.enemy.vitals.downed_for = 0.0
                self.enemy.vitals.health = self.enemy.vitals.max_health


class OmniKeyOneTests(OverhaulCase):
    def on(self):
        self.fight("GREEN", "WHITE", 300.0)
        self.combat.settings.reset_all()  # another test may have left a different squad chosen
        self.summon = self.player.powers.abilities["squad_summon"]
        self.tap("1")
        self.assertTrue(self.summon.active)

    def counts(self) -> tuple:
        names = [member.palette.name for member in self.teams.summons]
        return (sum(name.startswith("VILTRUMITE") for name in names), names.count("INVINCIBLE"))

    def test_five_and_mark_for_thirty_seconds_in_every_sixty(self):
        self.on()
        self.enemy.vitals.add_status("frozen", 600.0)  # at 0.5% health, a live enemy could fairly end this count early
        self.assertEqual(self.counts(), (5, 1))
        up, down, spans = 0, 0, []
        run = 0
        for _ in range(round(125.0 / FRAME)):
            self.game.update(FRAME)
            if self.teams.summons:
                self.assertEqual(self.counts(), (5, 1), "never a duplicate")
                run += 1
            elif run:
                spans.append(run * FRAME)
                run = 0
        self.assertEqual(self.summon.summons_made, 3, "at 0, 60 and 120 seconds")
        self.assertEqual(len(spans), 2)
        for span in spans:
            self.assertAlmostEqual(span, 30.0, delta=FRAME * 2)
        self.assertEqual(len(self.teams._squad), 6, "the same six bodies")

    def test_pressing_again_ends_it_at_any_moment(self):
        self.on()
        self.seconds(1.0)
        self.tap("1")
        self.assertFalse(self.summon.active)
        self.assertEqual(self.teams.summons, [])
        self.summon.cycle = 59.0
        self.seconds(2.0)
        self.assertEqual(self.teams.summons, [], "and they do not come back")
        self.tap("1")
        self.assertEqual(self.counts(), (5, 1), "on again: straight away, and only one squad")
        self.summon.cycle = 29.5
        self.seconds(1.0)
        self.assertEqual(self.teams.summons, [])
        self.assertTrue(self.summon.active)
        self.summon.cycle = 59.5
        self.seconds(1.0)
        self.assertEqual(self.counts(), (5, 1))
        self.tap("1")

    def tearDown(self):
        if hasattr(self, "game"):
            self.game.combat.settings.reset_squad()

    def choose(self, **values) -> None:
        store = self.game.combat.settings
        for key, value in values.items():
            store.set("GREEN", "squad_summon", key, value)

    def test_who_comes_is_chosen_and_it_counts_from_the_next_call(self):
        for count, mark, expected in ((3, True, (3, 1)), (5, False, (5, 0)), (0, True, (0, 1)), (2, False, (2, 0))):
            with self.subTest(count=count, mark=mark):
                self.fight("GREEN", "WHITE", 300.0)
                self.choose(viltrumites=count, mark=1 if mark else 0)
                self.tap("1")
                self.assertEqual(self.counts(), expected)
                self.tap("1")
                self.assertEqual(self.teams.summons, [])

    def test_nobody_at_all_is_harmless(self):
        self.fight("GREEN", "WHITE", 300.0)
        self.choose(viltrumites=0, mark=0)
        self.tap("1")
        self.seconds(1.0)
        self.assertEqual(self.teams.summons, [])
        self.assertTrue(self.player.powers.abilities["squad_summon"].active)
        self.tap("1")

    def test_the_times_are_chosen_and_change_live(self):
        self.on()
        self.choose(active_seconds=2, cycle_seconds=5)
        self.seconds(2.5)
        self.assertEqual(self.teams.summons, [], "out for two")
        self.seconds(2.6)
        self.assertEqual(self.counts(), (5, 1), "back at five")
        self.assertEqual(self.summon.summons_made, 2, "and only once")
        self.tap("1")

    def test_active_can_never_outlast_the_cycle(self):
        self.on()
        store = self.game.combat.settings
        self.choose(active_seconds=50, cycle_seconds=5)
        self.seconds(6.0)
        self.assertEqual(self.counts(), (5, 1), "no time off: they stay")
        self.assertEqual(self.summon.summons_made, 1, "and are not called again")
        self.assertTrue(store.fit_squad_times())
        self.assertEqual(store.get("GREEN", "squad_summon", "active_seconds"), 5)
        self.assertFalse(store.fit_squad_times())
        self.tap("1")

    def test_it_saves_loads_and_resets(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PowerSettings(Path(folder) / "powers.json")
            self.assertEqual([store.get("GREEN", "squad_summon", key) for key in SQUAD_KEYS], [5, 1, 30, 60])
            for key, value in zip(SQUAD_KEYS, (2, 0, 12, 40)):
                store.set("GREEN", "squad_summon", key, value)
            store.set("GREEN", "squad_summon", "range", 777)
            self.assertTrue(store.save())
            loaded = PowerSettings(store.path)
            self.assertEqual([loaded.get("GREEN", "squad_summon", key) for key in SQUAD_KEYS], [2, 0, 12, 40])
            loaded.reset_squad()
            self.assertEqual([loaded.get("GREEN", "squad_summon", key) for key in SQUAD_KEYS], [5, 1, 30, 60])
            self.assertEqual(loaded.get("GREEN", "squad_summon", "range"), 777, "only those")
            loaded.max_character("GREEN")
            self.assertEqual(loaded.get("GREEN", "squad_summon", "active_seconds"), 30, "MAX ALL leaves them alone")

    def test_the_menu_shows_it_on_omni_mans_tab_only(self):
        self.fight("GREEN", "WHITE", 300.0)
        panel = self.game.power_panel
        self.game.input("p")
        card = panel.squad_card
        panel.select_character("GREEN")
        self.assertIn("Out for 30 s, then away for 30 s, every 60 s", card.inactive.text)
        mark = card.rows["mark"]
        self.assertEqual(mark.value.text.strip(), "ON")
        mark.begin_edit()
        self.assertEqual(mark.value.text.strip(), "OFF")
        panel.begin_edit(card.rows["viltrumites"])
        self.game.input("3")
        self.game.input("enter")
        panel.begin_edit(card.rows["active_seconds"])
        self.game.input("9")
        self.game.input("9")
        self.game.input("enter")
        panel.begin_edit(card.rows["cycle_seconds"])
        self.game.input("2")
        self.game.input("0")
        self.game.input("enter")
        self.assertIn("Out for 20 s, then away for 0 s, every 20 s", card.inactive.text)
        panel.apply()
        store = self.game.combat.settings
        self.assertEqual([store.get("GREEN", "squad_summon", key) for key in SQUAD_KEYS], [3, 0, 20, 20])
        self.assertIn("cut", panel.status.text)
        card.reset_button.on_click()
        self.assertEqual([store.get("GREEN", "squad_summon", key) for key in SQUAD_KEYS], [5, 1, 30, 60])
        panel.select_character("WHITE")
        self.assertFalse(card.background.enabled)
        self.assertFalse(card.rows["mark"].track.enabled)
        self.game.input("p")

    def test_they_keep_their_health_shares_and_do_not_heal(self):
        self.on()
        for member in self.teams.summons:
            share = .05 if member.palette.name == "INVINCIBLE" else .005
            self.assertAlmostEqual(member.vitals.max_health,
                                   share * self.combat.settings.get("GREEN", "character", "health"))
            self.assertEqual(member.health_share, share)
            self.assertEqual(member.vitals.regen, 0.0)
        member = self.teams.summons[0]
        member.vitals.health *= .5
        health = member.vitals.health
        self.seconds(1.0)
        self.assertLessEqual(member.vitals.health, health, "only ever down")
        self.tap("1")

    def test_they_never_hit_their_own_side(self):
        self.fight("GREEN", "WHITE", 12.0)
        self.tap("1")
        self.seconds(3.0)
        self.assertEqual(self.player.vitals.damage_taken, 0.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0, "and they do fight")
        self.tap("1")

    def test_time_stop_holds_the_clock_and_time_starting_again_lets_it_go_on(self):
        self.on()
        self.summon.cycle = 29.0
        cycle = self.summon.cycle
        self.tap("t")
        self.assertTrue(self.combat.world_stopped)
        self.seconds(5.0)
        self.assertAlmostEqual(self.summon.cycle, cycle, delta=FRAME * 2)
        self.assertEqual(self.counts(), (5, 1))
        self.combat.end_world_stop()
        self.seconds(1.5)
        self.assertEqual(self.teams.summons, [])
        self.tap("1")


class OmniKeyFourTests(OverhaulCase):
    def test_key_four_is_exactly_as_it_was(self):
        self.fight("GREEN", "WHITE")
        self.tap("4")
        motion = self.player.motion
        self.assertIsInstance(motion, TripleImpactExecution)
        self.assertTrue(self.combat.time_stopped)
        most = 0

        def watch():
            nonlocal most
            most = max(most, len(self.teams.summons))

        self.run_through(motion, 80.0, watch)
        self.assertEqual(most, 6)
        self.assertEqual(motion.impacts, len(omni_man.IMPACTS))
        self.assertEqual(self.teams.summons, [], "its temporary squad went back")
        self.assertFalse(self.combat.time_stopped)

    def test_with_key_one_on_the_cycle_waits_and_the_squad_is_shared(self):
        self.fight("GREEN", "WHITE")
        self.tap("1")
        summon = self.player.powers.abilities["squad_summon"]
        self.tap("4")
        motion = self.player.motion
        cycle = summon.cycle
        most = 0

        def watch():
            nonlocal most
            most = max(most, len(self.teams.summons))

        self.run_through(motion, 80.0, watch)
        self.assertEqual(most, 6, "no second squad")
        self.assertAlmostEqual(summon.cycle, cycle, delta=FRAME * 2, msg="the clock stood still")
        self.assertTrue(summon.active)
        self.tap("1")
        self.assertEqual(self.teams.summons, [])


class AITests(OverhaulCase):

    def test_ai_sentry_goes_void_and_stays_void_and_ai_soldier_boy_blasts_and_stops(self):
        self.fight("WHITE", "YELLOW", 40.0, ai_powers=True)
        self.enemy._ai_next_attack = 0.0
        self.teams.attack_tokens.holders.clear()
        move = next(move for move in MOVES["YELLOW"] if move.ability_id == "void_form")
        with mock.patch("characters.roster_character.choose_move", side_effect=[move] + [None] * 2000):
            self.seconds(3.0)
            void_form = self.enemy.powers.abilities["void_form"]
            self.assertTrue(void_form.active, "left on when its turn ends")
            self.assertIs(void_form.subject, self.player)
            self.assertTrue(is_ground_shadow(self.player))
            self.assertTrue(self.player.vitals.immobile)
            self.enemy.powers.cancel_all()
        self.assertFalse(is_ground_shadow(self.player))
        self.fight("WHITE", "RED", 20.0, ai_powers=True)
        self.enemy._ai_next_attack = 0.0
        self.teams.attack_tokens.holders.clear()
        move = next(move for move in MOVES["RED"] if move.ability_id == "radiation_blast")
        with mock.patch("characters.roster_character.choose_move", side_effect=[move] + [None] * 2000):
            self.seconds(10.0)
        blast = self.enemy.powers.abilities["radiation_blast"]
        self.assertGreaterEqual(blast.blasts, 3)
        self.assertFalse(blast.active, "its turn ended")
        self.assertGreater(self.player.vitals.damage_taken, 0.0)

    def test_two_ai_never_overlap_and_nobody_hits_their_own_side(self):
        self.fight("YELLOW", "BLACK", 40.0, ai_powers=True)
        second = self.teams.characters["WHITE"]
        self.teams.state.assignment["WHITE"] = ENEMY_TEAM
        self.teams._apply_roster()
        self.stand(second, 10.0, 40.0)
        self.tough(second, 1e7)
        for _ in range(round(50.0 / FRAME)):
            self.game.update(FRAME)
            self.assertFalse(self.combat.time_stopped)
            going = sum(1 for body in (self.enemy, second)
                        if getattr(getattr(body.motion, "ability", None), "ability_id", None) in CINEMATIC_IDS)
            self.assertLessEqual(going, 1)
        self.assertEqual(self.enemy.vitals.damage_taken, 0.0)
        self.assertEqual(second.vitals.damage_taken, 0.0)


class NothingGrowsTests(OverhaulCase):
    def test_repeating_each_one_builds_nothing_new(self):
        from ursina import scene
        for player, key in (("BLACK", "4"), ("YELLOW", "4")):
            self.fight(player, "WHITE")
            self.tap(key)
            self.run_through(self.player.motion)
            self.seconds(3.0)
            pools = sum(len(pool) for pool in self.teams._puppets.values())
            beams = len(self.combat._beams)
            before = sum(1 for entity in scene.entities if not entity.is_empty()
                         and entity not in scene._entities_marked_for_removal)
            for _ in range(2):
                self.stand(self.enemy, 0.0, 40.0)
                self.stand(self.player, 0.0, 0.0)
                self.tap(key)
                self.run_through(self.player.motion)
                self.seconds(3.0)
            after = sum(1 for entity in scene.entities if not entity.is_empty()
                        and entity not in scene._entities_marked_for_removal)
            self.assertEqual(sum(len(pool) for pool in self.teams._puppets.values()), pools)
            self.assertEqual(len(self.combat._beams), beams)
            self.assertLess(after - before, self.game.world.debris_budget.maximum_live_pieces + 60)


if __name__ == "__main__":
    unittest.main()
