"""Bodies that behave physically: planted feet, jump arcs, falls, blows, tumbles, trees and debris."""

from __future__ import annotations

from math import acos, degrees, pi
import unittest

from panda3d.core import LQuaternionf
from ursina import held_keys

from game_fixture import FRAME
from movement.flight_physics import Vec3 as SimVec3
from characters.sentry import JUMP_GRAVITY, TERMINAL_FALL_SPEED, fall_with_air
from movement.flight_pose import ASCENDING, DESCENDING, HANDS_ON_HIPS, POSES, REACHING
from powers.common import LAUNCH_TERMINAL, LaunchedMotion
from test_gameplay_control_update import LiveCase
from world.tree_destruction import LYING_ANGLE, FallingTree


class Case(LiveCase):
    def setUp(self):
        self.begin("WHITE", "RED", 400.0)
        self.addCleanup(lambda: [held_keys.__setitem__(key, 0) for key in ("w", "shift", "space")])

    def lowest_foot(self) -> float:
        visual = self.player.visual
        return min(visual._controls[name].getPos(visual.pose_root).y for name in ("foot_l", "foot_r"))


class GroundTests(Case):
    def test_a_foot_stays_on_the_ground_through_the_whole_stride(self):
        rest = self.lowest_foot()
        held_keys["w"] = 1
        self.seconds(.5)
        heights = []
        for _ in range(60):
            self.frames(1)
            heights.append(self.lowest_foot())
        self.assertLess(max(abs(height - rest) for height in heights), .09, "neither floating nor through the ground")

    def test_it_speeds_up_and_slows_down_it_does_not_jump_to_a_speed(self):
        held_keys["w"] = held_keys["shift"] = 1
        self.frames(1)
        first = self.player.ground.velocity.length()
        self.seconds(.3)
        later = self.player.ground.velocity.length()
        self.assertGreater(later, first)
        held_keys["w"] = held_keys["shift"] = 0
        self.frames(2)
        coasting = self.player.ground.velocity.length()
        self.assertGreater(coasting, 0.0, "momentum carries on")
        self.seconds(4.0)
        self.assertLess(self.player.ground.velocity.length(), coasting)

    def test_physics_comes_out_the_same_at_a_low_frame_rate(self):
        distances = []
        for dt in (FRAME, 1.0 / 20.0):
            self.begin("WHITE", "RED", 400.0)
            held_keys["w"] = 1
            start = float(self.player.z)
            for _ in range(round(2.0 / dt)):
                self.game.update(dt)
            distances.append(abs(float(self.player.z) - start))
            held_keys["w"] = 0
        self.assertLess(abs(distances[0] - distances[1]) / distances[0], .08, distances)


class JumpTests(Case):
    def peak(self, release_after: int | None) -> float:
        self.begin("WHITE", "RED", 400.0)
        self.game.input("space")
        best = 0.0
        for frame in range(180):
            if frame == release_after:
                self.game.input("space up")
            self.game.update(FRAME)
            best = max(best, self.player.jump_height)
        return best

    def test_a_tap_jumps_lower_than_a_press(self):
        self.assertLess(self.peak(2), self.peak(None) * .75)

    def test_a_fall_has_a_terminal_velocity(self):
        speed = 0.0
        for _ in range(4000):
            speed = fall_with_air(speed, JUMP_GRAVITY, FRAME)
        self.assertAlmostEqual(-speed, TERMINAL_FALL_SPEED, delta=2.0)

    def test_rising_feels_only_gravity(self):
        self.assertAlmostEqual(fall_with_air(100.0, JUMP_GRAVITY, FRAME), 100.0 - JUMP_GRAVITY * FRAME)

    def test_landing_bends_the_knees_and_they_straighten_again(self):
        self.game.input("space")
        self.frames(1)
        while self.player.jump_height > 0.0:
            self.frames(1)
        self.frames(3)
        visual = self.player.visual
        self.assertGreater(visual._squat, .05)
        self.seconds(2.0)
        self.assertLess(visual._squat, .02)

    def test_soldier_boy_keeps_his_super_jump_and_cannot_fly(self):
        self.begin("RED", "WHITE", 400.0)
        self.tap("f")
        self.seconds(.6)
        self.assertFalse(self.player.flight.is_flying)
        self.assertGreater(self.player.jump_height, 3.0)


class BlowTests(Case):
    def launched(self, velocity: SimVec3) -> LaunchedMotion:
        body = self.teams.characters["RED"]
        self.tough(body)
        body.release_motion()
        body.motion = LaunchedMotion(None, body, velocity)
        return body.motion

    def test_a_moving_attacker_hits_harder_than_a_standing_one(self):
        knocks = []
        for speed in (0.0, 80.0):
            self.begin("WHITE", "RED", 2.0)
            enemy = self.teams.characters["RED"]
            self.tough(enemy)
            ability = self.player.powers.abilities["physical_combat"] if "physical_combat" in self.player.powers.abilities else None
            if ability is None:
                ability = next(item for item in self.player.powers.abilities.values() if hasattr(item, "land_blow"))
            self.player.flight.velocity = SimVec3()
            self.player.ground.velocity = SimVec3(0.0, 0.0, speed)
            enemy.knock = SimVec3()
            ability.land_blow(enemy)
            knocks.append(enemy.knock.length())
        self.assertGreater(knocks[1], knocks[0])

    def test_a_blow_rocks_the_body(self):
        enemy = self.teams.characters["RED"]
        self.tough(enemy)
        self.combat.hit_character(self.player, enemy, 1.0, "physical", SimVec3(0.0, 0.0, 1.0), 60.0)
        self.assertGreater(enemy.visual._flinch, .3)

    def test_a_thrown_body_falls_at_no_more_than_terminal_velocity_and_never_jumps(self):
        motion = self.launched(SimVec3(30.0, 500.0, 0.0))
        body = motion.owner
        previous, fastest = float(body.y), 0.0
        for _ in range(round(14.0 / FRAME)):
            if body.motion is not motion:
                break
            self.game.update(FRAME)
            step = abs(float(body.y) - previous) / FRAME
            previous = float(body.y)
            if motion.velocity.y < 0.0:
                fastest = max(fastest, -motion.velocity.y)
            self.assertLess(step, 520.0)
        self.assertLessEqual(fastest, LAUNCH_TERMINAL + 3.0)

    def test_it_ends_up_lying_flat_and_gets_up_gradually(self):
        motion = self.launched(SimVec3(20.0, 25.0, 0.0))
        body = motion.owner
        lying = 0.0
        for _ in range(round(14.0 / FRAME)):
            if body.motion is not motion:
                break
            self.game.update(FRAME)
            if motion.landed:
                lying = max(lying, abs(float(body.pose_root.getP())))
        self.assertGreater(lying, 40.0, "it went down")
        self.assertEqual(float(body.pose_root.getP()), 0.0, "what gameplay reads is upright at once")
        tipped = abs(float(body.visual.body_root.getP()))
        self.assertGreater(tipped, 5.0, "what you see is still getting up")
        self.seconds(1.5)
        self.assertLess(abs(float(body.visual.body_root.getP())), 1.0)


class FlightTests(Case):
    def fly(self):
        self.tap("f")
        self.frames(30)
        self.assertTrue(self.player.flight.is_flying)
        held_keys["w"] = 1
        self.seconds(2.0)

    def test_it_builds_up_speed_and_air_takes_it_away_again(self):
        self.tap("f")
        self.frames(30)
        held_keys["w"] = 1
        self.frames(3)
        early = self.player.flight.speed_mps
        self.seconds(1.5)
        fast = self.player.flight.speed_mps
        self.assertGreater(fast, early)
        held_keys["w"] = 0
        self.frames(2)
        self.assertGreater(self.player.flight.speed_mps, fast * .5, "momentum: it does not simply stop")
        self.seconds(3.0)
        self.assertLess(self.player.flight.speed_mps, fast * .5)

    def test_turning_at_speed_rolls_the_body_into_the_turn_and_it_levels_out(self):
        self.fly()

        def apart(a, b) -> float:  # degrees between two orientations; Euler angles mean little at this pitch
            return degrees(2.0 * acos(min(1.0, abs(a.getR() * b.getR() + a.getI() * b.getI() + a.getJ() * b.getJ() + a.getK() * b.getK()))))

        level = LQuaternionf(self.player.pose_root.getQuat())
        for _ in range(45):
            self.game.camera.yaw += 2.0
            self.game.update(FRAME)
        turning = LQuaternionf(self.player.pose_root.getQuat())
        self.assertGreater(apart(turning, level), 4.0, "banked")
        self.seconds(2.5)
        self.assertLess(apart(self.player.pose_root.getQuat(), level), apart(turning, level) * .5, "levels out")


class FlightPostureTests(Case):
    FLYERS = ("WHITE", "BLACK", "YELLOW", "GREEN")

    def feet_apart(self) -> float:
        visual = self.player.visual
        a = visual._controls["foot_l"].getPos(visual.pose_root)
        b = visual._controls["foot_r"].getPos(visual.pose_root)
        return (a - b).length()

    def take_off(self, character_id: str) -> None:
        self.begin(character_id, "RED" if character_id != "RED" else "WHITE", 900.0)
        self.teams.characters["RED"].vitals.add_status("frozen", 600.0)
        self.tap("f")
        self.seconds(1.5)

    def test_every_flyer_hovers_upright_hands_on_hips_with_the_legs_together(self):
        for character_id in self.FLYERS:
            with self.subTest(character_id):
                self.take_off(character_id)
                self.assertEqual(self.player.flight_pose, HANDS_ON_HIPS)
                self.assertLess(abs(self.player.pose_root.getP()), 8.0)
                self.assertLess(self.feet_apart(), .34)
                self.assertEqual(self.player.left_leg.rotation_x, self.player.right_leg.rotation_x, "neither leg walks on its own")

    def test_w_reaches_forward_and_letting_go_comes_back_smoothly(self):
        for character_id in self.FLYERS:
            with self.subTest(character_id):
                self.take_off(character_id)
                self.game.camera.pitch = -2.0
                held_keys["w"] = 1
                self.seconds(1.0)
                self.assertEqual(self.player.flight_pose, REACHING)
                self.assertLess(self.feet_apart(), .34)
                before = self.player.left_arm.rotation_x
                held_keys["w"] = 0
                self.frames(1)
                self.assertEqual(self.player.flight_pose, HANDS_ON_HIPS, "the key is what decides, at once")
                self.assertLess(abs(self.player.left_arm.rotation_x - before), 40.0, "and the body eases there")
                self.seconds(1.2)
                self.assertLess(abs(self.player.left_arm.rotation_x - POSES[HANDS_ON_HIPS].shoulder_x), 12.0)
                self.game.camera.pitch = self.game.camera.DEFAULT_PITCH

    def test_sideways_or_straight_up_is_not_moving_forward(self):
        self.take_off("WHITE")
        for key, pose in (("a", HANDS_ON_HIPS), ("d", HANDS_ON_HIPS), ("space", ASCENDING), ("control", DESCENDING)):
            held_keys[key] = 1
            self.seconds(.5)
            self.assertEqual(self.player.flight_pose, pose, key)
            held_keys[key] = 0
            self.assertLess(self.feet_apart(), .34, key)
            self.seconds(.6)

    def test_landing_gives_the_legs_back(self):
        self.take_off("WHITE")
        self.tap("f")
        self.seconds(5.0)
        self.assertFalse(self.player.flight.is_flying)
        self.seconds(1.0)
        self.assertLess(self.player.visual._together, .4, "a standing stance again, not pressed together")

    def test_a_rush_tips_the_body_into_the_move_instead_of_arms_up_on_a_standing_body(self):
        self.begin("GREEN", "RED", 200.0)
        self.tough(self.teams.characters["RED"])
        body = self.player
        self.tap("2")
        leaning = 0.0
        for _ in range(60):
            if body.motion is None:
                break
            self.game.update(FRAME)
            leaning = max(leaning, abs(body.pose_root.getP()))
        self.assertGreater(leaning, 20.0)

    def test_every_body_stands_with_its_own_proportions_and_a_full_skeleton(self):
        for character_id in ("YELLOW", "WHITE", "GREEN", "BLACK", "RED"):
            visual = self.teams.characters[character_id].visual
            self.assertEqual(len(visual.rig["joints"]), 18, character_id)

    def test_soldier_boy_never_takes_a_flying_pose(self):
        self.begin("RED", "WHITE", 900.0)
        self.tap("f")
        self.seconds(.5)
        self.assertFalse(self.player.flight.is_flying)
        self.assertLess(self.player.visual._gait, .01, "not striding in the air")


class WorldTests(Case):
    def tree(self) -> FallingTree:
        world = self.game.world
        x, z = float(self.player.x) + 30.0, float(self.player.z)
        tree = FallingTree(world, "test-tree", (x, world.height_at(x, z), z), 1.0, (.2, .4, .2, 1.0), SimVec3(1.0, 0.0, 0.0))
        world.effects.append(tree)
        self.addCleanup(lambda: world.effects.remove(tree) if tree in world.effects else None)
        return tree

    def test_a_tree_tips_slowly_then_falls_fast_and_stops_lying_down(self):
        tree = self.tree()
        tree.step(.5)
        slow = tree.angular_velocity
        speeds = [slow]
        for _ in range(240):
            tree.step(FRAME)
            speeds.append(abs(tree.angular_velocity))
        self.assertGreater(max(speeds), slow * 2.5, "gravity's pull grows as it tips")
        self.assertTrue(tree.impacted)
        self.assertLessEqual(tree.angle, LYING_ANGLE + 1e-6)
        self.assertEqual(tree.angular_velocity, 0.0, "it comes to rest")

    def test_debris_never_goes_through_the_ground_and_comes_to_rest(self):
        world, combat = self.game.world, self.combat
        x, z = float(self.player.x) + 20.0, float(self.player.z) + 20.0
        for index in range(20):
            world.spawn_debris(SimVec3(x + index, world.height_at(x + index, z) + 5.0, z), SimVec3(index - 10.0, 12.0, -6.0),
                               (.5, .4, .3, 1.0), .3, 7.0)
        lowest = 1e9
        for _ in range(round(4.0 / FRAME)):
            self.game.update(FRAME)
            for piece in world.debris:
                lowest = min(lowest, float(piece.y) - world.height_at(float(piece.x), float(piece.z)))
        self.assertGreater(lowest, -.5)

    def test_a_blast_sends_a_wave_out_that_dies_away(self):
        x, z = float(self.player.x) + 60.0, float(self.player.z)
        self.combat.blast(None, SimVec3(x, self.game.world.height_at(x, z), z), 40.0, 10.0, 60.0)
        self.assertIsNotNone(self.combat._wave)
        self.seconds(3.0)
        self.assertIsNone(self.combat._wave)


if __name__ == "__main__":
    unittest.main()
