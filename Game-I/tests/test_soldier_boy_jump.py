"""Soldier Boy's super jump, on the real game loop: height, control, collision, stability and AI."""

from __future__ import annotations

import unittest
from unittest import mock

from ursina import held_keys

from characters.roster import KITS
from characters.sentry import MAX_JUMP_SPEED
from config.character_roster import ENEMY_TEAM
from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from power_fixture import fresh_tree
from powers.soldier_boy_attacks import AerialGrabBlast, FlyingPunch, RadioactiveExecution
from test_gameplay_control_update import LiveCase


def height_of(game, body) -> float:
    return float(body.y) - game.world.height_at(body.x, body.z) - .25


class JumpCase(LiveCase):
    def start(self, enemy: str = "BLACK", distance: float = 800.0, ai_powers: bool = False):
        self.begin("RED", enemy, distance, ai_powers=ai_powers)
        self.tough(self.enemy)
        self.tough(self.player)
        self.enemy.vitals.add_status("frozen", 600.0)
        self.frames(1)

    def height(self) -> float:
        return height_of(self.game, self.player)

    def jump(self, hold_seconds: float = 0.0) -> float:
        """Press Space, keep it down this long, let go, and return the highest he got."""
        self.game.input("space")
        held_keys["space"] = 1
        self.seconds(hold_seconds) if hold_seconds else self.frames(1)
        held_keys["space"] = 0
        self.game.input("space up")
        return self.fall()

    def fall(self) -> float:
        highest = self.height()
        for _ in range(round(120.0 / FRAME)):
            self.game.update(FRAME)
            highest = max(highest, self.height())
            self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED, "this is never flight")
            if not self.player.keeps_own_height:
                return highest
        self.fail("he never came down")

    def tearDown(self) -> None:
        held_keys["space"] = 0


class HeightTests(JumpCase):
    def test_only_soldier_boy_has_it(self):
        self.assertTrue(KITS["RED"].super_jump)
        for character_id in ("YELLOW", "WHITE", "BLACK", "GREEN"):
            self.assertFalse(KITS[character_id].super_jump, character_id)

    def test_a_tap_is_a_short_hop(self):
        self.start()
        self.assertLess(self.jump(), 12.0)
        self.assertGreater(self.jump(), 2.0)

    def test_the_longer_the_key_is_held_the_higher_he_goes(self):
        self.start()
        tap = self.jump()
        short = self.jump(.2)
        long = self.jump(.8)
        self.assertLess(tap, short)
        self.assertLess(short, long)
        self.assertGreater(long, 800.0, "one press, held, goes a very long way")

    def test_holding_it_longer_than_a_press_gives_does_not_become_flying(self):
        self.start()
        self.game.input("space")
        held_keys["space"] = 1
        self.seconds(.8)
        fast = self.player.jump_velocity
        self.seconds(5.0)
        self.assertLess(self.player.jump_velocity, fast - 50.0, "gravity has it, even with the key down")
        held_keys["space"] = 0
        self.fall()

    def test_there_is_no_ceiling_and_pressing_again_in_the_air_goes_on_up(self):
        self.start()
        planet = self.game.planet
        for _ in range(6):
            self.game.input("space")
            held_keys["space"] = 1
            self.seconds(.8)
            held_keys["space"] = 0
            self.game.input("space up")
        self.seconds(5.0)
        self.assertGreater(float(self.player.y), planet.MAX_FLIGHT_ALTITUDE * 8.0, "far above where anyone can fly")
        self.fall()
        self.assertFalse(self.player.keeps_own_height)

    def test_the_power_setting_scales_it(self):
        self.start()
        self.game.profiles.set("my_sentry", "super_jump_power_pct", 20, notify=False)
        weak = self.jump(.8)
        self.game.profiles.set("my_sentry", "super_jump_power_pct", 100, notify=False)
        strong = self.jump(.8)
        self.assertLess(weak * 3.0, strong)

    def test_it_is_a_real_climb_with_no_teleporting(self):
        self.start()
        self.game.input("space")
        held_keys["space"] = 1
        last = float(self.player.y)
        worst = 0.0
        for _ in range(round(30.0 / FRAME)):
            self.game.update(FRAME)
            if self.player.jump_hold_left <= 0.0:
                held_keys["space"] = 0
            worst = max(worst, abs(float(self.player.y) - last))
            last = float(self.player.y)
            self.assertIs(self.player.flight.phase, FlightPhase.GROUNDED)
        self.assertLessEqual(worst, MAX_JUMP_SPEED * FRAME + 1.0)
        self.fall()

    def test_the_same_height_whatever_the_frame_rate(self):
        heights = []
        for dt in (1.0 / 30.0, 1.0 / 60.0, 1.0 / 144.0):
            self.start()
            self.player.leap(200.0, SimVec3())
            highest = 0.0
            for _ in range(round(30.0 / dt)):
                self.game.update(dt)
                highest = max(highest, self.height())
            heights.append(highest)
        self.assertLess(max(heights) - min(heights), max(heights) * .02, heights)

    def test_speed_is_bounded_and_nothing_overflows(self):
        self.start()
        self.player.leap(1e12, SimVec3())
        self.assertLessEqual(self.player.jump_velocity, MAX_JUMP_SPEED)
        self.frames(30)
        self.assertLessEqual(abs(self.player.jump_velocity), MAX_JUMP_SPEED)
        self.player.position = (float(self.player.x), 1e12, float(self.player.z))
        self.frames(2)
        self.assertLess(float(self.player.y), 1e6, "held at the safety limit")
        self.assertEqual(float(self.player.y), float(self.player.y), "not NaN")
        self.player.position = (float(self.player.x), 500.0, float(self.player.z))
        self.fall()


class ControlTests(JumpCase):
    def test_he_steers_in_the_air_and_keeps_going_without_input(self):
        self.start()
        self.player.leap(120.0, SimVec3())
        self.frames(5)
        z = float(self.player.z)
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertGreater(float(self.player.z) - z, 10.0, "steered")
        moving = self.player.ground.velocity.z
        self.assertGreater(moving, 5.0)
        self.seconds(.5)
        self.assertAlmostEqual(self.player.ground.velocity.z, moving, delta=.01, msg="and no ground to slow him")
        self.fall()

    def test_turning_the_camera_does_not_bend_the_jump(self):
        self.start()
        self.player.leap(120.0, SimVec3(0.0, 0.0, 30.0))
        self.frames(2)
        z = float(self.player.z)
        x = float(self.player.x)
        for _ in range(120):
            self.game.camera.yaw += 3.0
            self.game.update(FRAME)
        self.assertAlmostEqual(float(self.player.x), x, delta=.01)
        self.assertAlmostEqual(float(self.player.z) - z, 60.0, delta=1.5)
        self.fall()

    def test_it_is_space_and_the_ability_keys_are_unchanged(self):
        self.start()
        keys = {key: ability.ability_id for key, ability in self.player.powers.slots.items()}
        self.assertEqual(keys, {"1": "radiation_blast", "2": "flying_punch", "3": "aerial_grab_blast",
                                "4": "radioactive_execution", "t": "world_stop"})
        self.player.leap(60.0, SimVec3())
        self.frames(5)
        self.tap("1")
        self.assertTrue(self.player.powers.abilities["radiation_blast"].active, "key 1 works up there")
        self.tap("1")
        self.fall()

    def test_his_stats_are_not_touched(self):
        self.start()
        before = (self.player.powers.strength, self.player.vitals.max_health, self.player.vitals.resistance,
                  self.player.vitals.regen)
        self.jump(.8)
        self.assertEqual(before, (self.player.powers.strength, self.player.vitals.max_health,
                                  self.player.vitals.resistance, self.player.vitals.regen))
        self.assertEqual(self.player.vitals.damage_taken, 0.0, "and a landing never hurts him")


class CollisionTests(JumpCase):
    def building(self):
        return next(obj for obj in self.game.world.objects
                    if obj.anchored and not obj.health.broken and not getattr(obj, "is_traffic", False)
                    and abs(obj.scale_y) > 6.0 and abs(obj.scale_x) > 6.0 and abs(obj.scale_z) > 6.0)

    def test_falling_at_top_speed_he_stops_on_a_roof_rather_than_going_through(self):
        self.start()
        building = self.building()
        x, z = float(building.x), float(building.z)
        top = float(building.y) + abs(building.scale_y) * .5
        self.stand(self.player, x, z)
        self.player.position = (x, top + 2000.0, z)
        self.player.jump_height = 2000.0
        self.player.leap(-MAX_JUMP_SPEED, SimVec3())
        lowest = float(self.player.y)
        for _ in range(round(6.0 / FRAME)):
            self.game.update(FRAME)
            lowest = min(lowest, float(self.player.y))
        self.assertGreater(lowest, top - 1.0, "never inside it")
        self.assertGreater(float(self.player.y), top - 1.0)

    def test_jumping_up_under_nothing_and_landing_on_rough_ground_ends_on_the_ground(self):
        self.start()
        self.jump(.3)
        self.assertEqual(self.player.jump_height, 0.0)
        self.assertAlmostEqual(self.height(), 0.0, delta=.6)

    def at_a_wall(self, speed: float):
        self.start()
        building = self.building()
        x, z = float(building.x), float(building.z)
        depth = abs(building.scale_z) * .5
        height = float(building.y)
        floor = self.game.world.height_at(x, z - depth - 40.0) + .25
        self.stand(self.player, x, z - depth - 40.0)
        self.player.position = (x, height, z - depth - 40.0)
        self.player.jump_height = height - floor
        self.player.leap(10.0, SimVec3(0.0, 0.0, speed))
        return building, z

    def test_going_sideways_into_a_wall_stops_him_there(self):
        building, z = self.at_a_wall(30.0)
        self.seconds(3.0)
        self.assertFalse(building.health.broken)
        self.assertLess(float(self.player.z), z, "stopped at the wall")

    def test_at_extreme_speed_he_goes_through_a_wall_only_by_breaking_it(self):
        building, z = self.at_a_wall(600.0)
        before = building.health.health
        with mock.patch.object(building, "take_damage", wraps=building.take_damage) as hit:
            self.frames(30)
        self.assertGreater(hit.call_count, 0, "it was struck, not missed")
        self.assertLess(building.health.health, before)
        if float(self.player.z) > z:
            self.assertTrue(building.health.broken, "the only way to be on the far side of it")

    def test_a_tree_is_not_gone_through_at_speed_either(self):
        self.start()
        tree = fresh_tree(self.game, minimum=8.0)
        floor = self.game.world.height_at(tree.x, tree.z)
        self.stand(self.player, float(tree.x), float(tree.z) - 60.0)
        self.player.position = (float(tree.x), floor + 2.0, float(tree.z) - 60.0)
        self.player.jump_height = 2.0
        self.player.leap(4.0, SimVec3(0.0, 0.0, 700.0))
        self.frames(12)
        self.assertLess(float(self.player.z), float(tree.z) + 1.0)

    def test_a_hard_landing_marks_the_ground_without_hurting_him(self):
        self.start()
        craters = len(self.game.world.terrain_impacts)
        self.player.position = (float(self.player.x), float(self.player.y) + 400.0, float(self.player.z))
        self.player.jump_height = 400.0
        self.player.leap(-300.0, SimVec3())
        self.fall()
        self.assertGreater(len(self.game.world.terrain_impacts), craters)
        self.assertEqual(self.player.vitals.damage_taken, 0.0)
        self.assertAlmostEqual(self.height(), 0.0, delta=.6)

    def test_the_island_edge_still_holds(self):
        self.start()
        planet = self.game.planet
        x, z = planet.clamp_to_land(4900.0, 0.0)
        self.stand(self.player, x, z)
        self.player.leap(100.0, SimVec3(800.0, 0.0, 0.0))
        self.seconds(3.0)
        self.assertTrue(self.game.world.contains_position(float(self.player.x), float(self.player.z)))
        self.fall()


class AerialCombatTests(JumpCase):
    def test_all_three_cinematics_reach_a_flyer_and_bring_him_home(self):
        for key, sequence in (("2", FlyingPunch), ("3", AerialGrabBlast), ("4", RadioactiveExecution)):
            with self.subTest(key):
                self.start(distance=100.0)
                floor = self.game.world.height_at(self.enemy.x, self.enemy.z)
                self.enemy.position = (float(self.enemy.x), floor + 300.0, float(self.enemy.z))
                self.enemy.flight.phase = FlightPhase.CRUISE
                self.game.input(key)
                self.game.input(f"{key} up")
                self.assertIsInstance(self.player.motion, sequence)
                while self.player.motion is not None:
                    self.game.update(FRAME)
                self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
                self.assertFalse(self.combat.time_stopped)
                for _ in range(round(30.0 / FRAME)):  # the punch leaves him where it found him, and he falls from there
                    if self.height() < 1.0:
                        break
                    self.game.update(FRAME)
                self.assertLess(self.height(), 1.0, "and he comes back down")
                self.assertFalse(self.player.flight.is_flying)

    def test_they_work_from_up_in_a_jump_too_and_do_not_snap_him_to_the_ceiling(self):
        self.start(distance=100.0)
        self.player.position = (float(self.player.x), 1500.0, float(self.player.z))
        self.player.jump_height = 1500.0 - float(self.game.world.height_at(self.player.x, self.player.z))
        self.player.jump_velocity = -1.0
        self.frames(1)
        y = float(self.player.y)
        self.game.input("2")
        self.game.input("2 up")
        self.frames(1)
        self.assertGreater(float(self.player.y), y - 100.0, "no sudden drop to 500 metres")
        while self.player.motion is not None:
            self.game.update(FRAME)
        self.assertFalse(self.combat.time_stopped)
        for _ in range(round(30.0 / FRAME)):  # the punch leaves him where it found him, and he falls from there
            if self.height() < 1.0:
                break
            self.game.update(FRAME)
        self.assertLess(self.height(), 1.0)

    def test_being_thrown_up_there_does_not_snap_him_down_either(self):
        self.start(distance=100.0)
        from powers.common import launch_character
        self.player.position = (float(self.player.x), 1500.0, float(self.player.z))
        launch_character(self.enemy, self.player, SimVec3(0.0, 0.0, 20.0))
        self.frames(2)
        self.assertGreater(float(self.player.y), 1490.0)
        self.player.release_motion()
        self.fall()


class AITests(JumpCase):
    def fight(self, flying_at: float | None, distance: float, seconds: float, moving: bool = False):
        self.begin("YELLOW", "RED", distance, ai_powers=True)
        self.tough(self.player)
        self.tough(self.enemy)
        self.ai = self.enemy
        self.teams._next_cinematic = 1e12  # this is about his movement; the sequences are tested elsewhere
        if flying_at is not None:
            floor = self.game.world.height_at(self.player.x, self.player.z)
            self.player.position = (float(self.player.x), floor + flying_at, float(self.player.z))
            self.player.flight.phase = FlightPhase.CRUISE
        leaps = []
        real = self.ai.leap

        def spy(upward, across, real=real):
            leaps.append((upward, across, self.game.elapsed))
            return real(upward, across)

        highest = 0.0
        closest = 1e9
        with mock.patch.object(self.ai, "leap", spy):
            for _ in range(round(seconds / FRAME)):
                self.game.update(FRAME)
                self.player.vitals.health = self.player.vitals.max_health
                self.assertFalse(self.ai.flight.is_flying, "never flight")
                highest = max(highest, height_of(self.game, self.ai))
                gap = ((float(self.ai.x) - float(self.player.x)) ** 2 + (float(self.ai.y) - float(self.player.y)) ** 2
                       + (float(self.ai.z) - float(self.player.z)) ** 2) ** .5
                closest = min(closest, gap)
        return leaps, highest, closest

    def test_it_leaps_up_at_a_flying_enemy_and_gets_there(self):
        leaps, highest, closest = self.fight(120.0, 30.0, 12.0)
        self.assertGreaterEqual(len(leaps), 2, "and keeps at it")
        self.assertGreater(highest, 80.0)
        self.assertLess(closest, 15.0, "right up to them")

    def test_it_leaps_across_a_long_gap(self):
        leaps, _highest, closest = self.fight(None, 400.0, 10.0)
        self.assertGreaterEqual(len(leaps), 1)
        self.assertLess(closest, 150.0)

    def test_it_stays_on_the_ground_when_that_is_the_better_place(self):
        leaps, highest, _closest = self.fight(None, 25.0, 6.0)
        self.assertEqual(leaps, [])
        self.assertLess(highest, 5.0)

    def test_it_aims_ahead_of_someone_moving(self):
        self.begin("YELLOW", "RED", 60.0, ai_powers=True)
        self.tough(self.player)
        self.tough(self.enemy)
        floor = self.game.world.height_at(self.player.x, self.player.z)
        self.player.position = (float(self.player.x), floor + 100.0, float(self.player.z))
        self.player.flight.phase = FlightPhase.CRUISE
        self.enemy._next_leap = 0.0
        self.player.flight.velocity = SimVec3(0.0, 0.0, 0.0)
        with mock.patch.object(self.enemy, "leap") as still:
            self.enemy._think_about_leaping()
        self.enemy._next_leap = 0.0
        self.player.flight.velocity = SimVec3(60.0, 0.0, 0.0)
        with mock.patch.object(self.enemy, "leap") as moving:
            self.enemy._think_about_leaping()
        self.assertGreater(moving.call_args.args[1].x, still.call_args.args[1].x + 20.0)

    def test_up_there_it_punches_and_grapples(self):
        self.begin("YELLOW", "RED", 3.0, ai_powers=True)
        self.tough(self.player)
        self.tough(self.enemy)
        self.teams._next_cinematic = 1e12
        floor = self.game.world.height_at(self.player.x, self.player.z)
        for body in (self.player, self.enemy):
            body.position = (float(body.x), floor + 80.0, float(body.z))
        self.player.flight.phase = FlightPhase.CRUISE
        self.enemy.jump_height = 80.0
        self.enemy.jump_velocity = 1.0
        used = set()
        for ability_id in ("shield_combat", "grab"):
            ability = self.enemy.powers.abilities[ability_id]

            def spy(ability=ability, real=ability.press):
                used.add(ability.ability_id)
                return real()
            ability.press = spy
        for attempt in range(40):
            self.enemy.position = (float(self.player.x), float(self.player.y), float(self.player.z) + 3.0)
            self.enemy.jump_height = 80.0
            self.enemy.jump_velocity = 1.0
            self.enemy._ai_next_attack = 0.0
            self.enemy._end_ai_move()
            self.teams.attack_tokens.holders.clear()
            self.frames(2)
        for ability_id in ("shield_combat", "grab"):
            self.enemy.powers.abilities[ability_id].__dict__.pop("press", None)
        self.assertEqual(used, {"shield_combat", "grab"})
        self.assertGreater(self.player.vitals.damage_taken, 0.0)

    def test_with_ai_powers_off_it_does_not_jump_about(self):
        self.begin("YELLOW", "RED", 400.0, ai_powers=False)
        self.tough(self.enemy)
        self.seconds(5.0)
        self.assertFalse(self.enemy.keeps_own_height)

    def test_never_any_flight_in_a_long_fight(self):
        self.begin("YELLOW", "RED", 100.0, ai_powers=True)
        self.tough(self.player)
        self.tough(self.enemy)
        floor = self.game.world.height_at(self.player.x, self.player.z)
        self.player.position = (float(self.player.x), floor + 150.0, float(self.player.z))
        self.player.flight.phase = FlightPhase.CRUISE
        for _ in range(round(30.0 / FRAME)):
            self.game.update(FRAME)
            self.player.vitals.health = self.player.vitals.max_health
            self.assertFalse(self.enemy.flight.is_flying)
            self.assertEqual(self.enemy.flight.velocity.length(), 0.0)


class OthersUnchangedTests(LiveCase):
    def test_everyone_elses_jump_is_exactly_what_it_was(self):
        for character_id in ("YELLOW", "WHITE", "BLACK", "GREEN"):
            with self.subTest(character_id):
                self.begin(character_id, "RED", 800.0)
                self.assertFalse(self.player.keeps_own_height)
                self.game.input("space")
                self.game.input("space up")
                self.assertEqual(self.player.jump_velocity, 7.0)
                self.assertEqual(self.player.jump_hold_left, 0.0)
                self.frames(1)
                self.game.input("space")
                self.assertLess(self.player.jump_velocity, 7.0, "no second jump in the air")
                self.seconds(2.0)
                self.assertEqual(self.player.jump_height, 0.0)


if __name__ == "__main__":
    unittest.main()
