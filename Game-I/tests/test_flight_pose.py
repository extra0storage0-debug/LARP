"""The flying poses, measured on the real rigs: where the hands actually end up."""

from __future__ import annotations

from math import acos, degrees
import unittest

from panda3d.core import NodePath, Point3
from ursina import held_keys, scene

from game_fixture import FRAME
from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from movement.flight_pose import (DESCENDING, ENTER_SPEED, HANDS_ON_HIPS, LEAVE_SPEED, POSES, REACHING, blend_amount,
                                  choose_pose)
from test_camera_aim_flight import AimCase, angle_between
from test_gameplay_control_update import FLYERS, LiveCase

FORWARD, UP = SimVec3(0.0, 0.0, 1.0), SimVec3(0.0, 1.0, 0.0)
HAND_BELOW_ELBOW = .46  # -.98 glove, less the elbow's -.52
HIP_HEIGHT = .95


def path_of(joint) -> NodePath:
    """A clone's joint wraps a node, and an entity is one."""
    return joint.node if isinstance(joint.node, NodePath) else joint


class ChoosingTests(unittest.TestCase):
    def test_direction_decides(self):
        for name, velocity, wanted in (("forward", SimVec3(0, 0, 40), REACHING), ("up", SimVec3(0, 40, 0), REACHING),
                                       ("down", SimVec3(0, -40, 0), REACHING), ("still", SimVec3(), HANDS_ON_HIPS),
                                       ("backward", SimVec3(0, 0, -40), HANDS_ON_HIPS),
                                       ("sideways", SimVec3(40, 0, 0), HANDS_ON_HIPS),
                                       ("up and ahead", SimVec3(0, 30, 30), REACHING)):
            with self.subTest(name):
                self.assertEqual(choose_pose(HANDS_ON_HIPS, velocity, FORWARD, UP), wanted)

    def test_a_speed_hovering_on_a_threshold_does_not_flicker(self):
        for start, low, high in ((HANDS_ON_HIPS, ENTER_SPEED - 1.0, ENTER_SPEED - .1),
                                 (REACHING, LEAVE_SPEED + .1, ENTER_SPEED - .1)):
            pose = start
            for frame in range(200):
                speed = low if frame % 2 else high
                pose = choose_pose(pose, SimVec3(0, 0, speed), FORWARD, UP)
                self.assertEqual(pose, start)

    def test_direction_on_a_threshold_does_not_flicker(self):
        pose = REACHING
        for frame in range(100):
            pose = choose_pose(pose, SimVec3(30.0, 0.0, 2.0 if frame % 2 else 4.0), FORWARD, UP)
            self.assertEqual(pose, REACHING)

    def test_blending_is_the_same_at_any_frame_rate(self):
        results = []
        for fps in (20, 60, 240):
            value = 0.0
            for _ in range(fps // 2):
                value += (100.0 - value) * blend_amount(1.0 / fps)
            results.append(value)
        self.assertAlmostEqual(results[0], results[1], delta=.5)
        self.assertAlmostEqual(results[1], results[2], delta=.5)


class RigTests(LiveCase):
    def hand_of(self, character, side: str) -> Point3:
        node = character.visual._controls[f"hand_{side[0]}"]
        return character.pose_root.getRelativePoint(node, Point3(0.0, 0.0, 0.0))

    def test_at_rest_every_hand_hangs_beside_the_thigh(self):
        for character_id in ("YELLOW", "WHITE", "GREEN", "BLACK", "RED"):
            with self.subTest(character_id):
                self.begin(character_id, enemy="RED" if character_id != "RED" else "BLACK", distance=3000.0)
                body = self.player
                body.left_arm.rotation_x = body.left_arm.rotation_z = 0.0
                body.left_elbow.rotation_x = body.left_elbow.rotation_z = 0.0
                hand = self.hand_of(body, "left")
                self.assertLess(abs(hand.x + .5), .3, "out at the side")
                self.assertLess(hand.y, 1.5, "below the hip")
                self.assertGreater(hand.y, .7, "above the knee")

    def test_every_forearm_really_moves_with_its_elbow(self):
        for character_id in ("YELLOW", "WHITE", "GREEN", "BLACK"):
            self.begin(character_id, enemy="RED", distance=3000.0)
            elbow = self.player.left_elbow
            node = path_of(elbow)
            self.assertGreater(node.getNumChildren(), 0, f"{character_id}: nothing hangs from the elbow")
            before = self.hand_of(self.player, "left")
            elbow.rotation_z = 60.0
            self.assertGreater((self.hand_of(self.player, "left") - before).length(), .2)
            elbow.rotation_z = 0.0


class PoseCase(AimCase):
    def settle_flying(self, yaw: float, pitch: float, *keys, seconds: float = 1.5):
        self.aim(yaw, pitch)
        for key in keys:
            held_keys[key] = 1
        self.seconds(seconds)

    def reach_error(self, character) -> float:
        """Degrees between where the left arm points and where the body is going."""
        root = scene
        elbow = path_of(character.left_elbow)
        arm = path_of(character.left_arm)
        shoulder = root.getRelativePoint(arm, Point3(0.0, 0.0, 0.0))
        hand = root.getRelativePoint(character.visual._controls["hand_l"], Point3(0.0, 0.0, 0.0))
        return angle_between(SimVec3(hand.x - shoulder.x, hand.y - shoulder.y, hand.z - shoulder.z),
                             character.flight.velocity)

    def assert_hands_on_hips(self, character) -> None:
        self.assertEqual(character.flight_pose, HANDS_ON_HIPS)
        scale = character.pose_root
        for side, sign in (("left", -1.0), ("right", 1.0)):
            elbow_node = path_of(getattr(character, f"{side}_elbow"))
            hand = scale.getRelativePoint(character.visual._controls[f"hand_{side[0]}"], Point3(0.0, 0.0, 0.0))
            elbow = scale.getRelativePoint(elbow_node, Point3(0.0, 0.0, 0.0))
            self.assertLess(abs(hand.x - sign * .3), .2, f"{side} hand is at the side of the hip: {hand}")
            self.assertLess(abs(hand.y - character.visual.rig["joints"]["pelvis"]["at"][1] - .12), .25, f"{side} hand is at hip height: {hand}")
            self.assertGreater(abs(elbow.x), .5, f"{side} elbow points outward: {elbow}")
            self.assertGreater(abs(elbow.x), abs(hand.x), side)
        self.assertLess(abs(character.pose_root.getP()), 8.0, "the torso is upright")

    def tearDown(self):
        for key in ("w", "s", "a", "d", "shift"):
            held_keys[key] = 0


class FlyingPoseTests(PoseCase):
    def test_forward_up_and_down_reach_along_the_travel(self):
        for character_id in FLYERS:
            for name, pitch in (("forward", 0.0), ("up", -85.0), ("down", 85.0), ("up diagonal", -40.0),
                                ("down diagonal", 40.0)):
                with self.subTest(f"{character_id} {name}"):
                    self.airborne(character_id, height=300.0)
                    self.settle_flying(0.0, pitch, "w", seconds=2.0)
                    self.assertEqual(self.player.flight_pose, REACHING)
                    self.assertLess(self.reach_error(self.player), 40.0)

    def test_forward_legs_trail_and_elbows_are_slightly_bent(self):
        for character_id in FLYERS:
            self.airborne(character_id)
            self.settle_flying(0.0, 0.0, "w")
            body = self.player
            self.assertAlmostEqual(body.left_elbow.rotation_x, POSES[REACHING].elbow_x, delta=2.0)
            self.assertLess(abs(body.left_leg.rotation_x), 12.0)
            held_keys["w"] = 0

    def test_hovering_is_hands_on_hips_for_all_four(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.airborne(character_id)
                self.seconds(2.0)
                self.assert_hands_on_hips(self.player)

    def test_flying_backward_is_hands_on_hips_for_all_four(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.airborne(character_id)
                self.settle_flying(0.0, 0.0, "s", seconds=2.5)
                self.assertGreater(self.player.flight.speed_mps, 20.0)
                self.assertLess(self.player.flight.velocity.z, 0.0)
                self.assert_hands_on_hips(self.player)
                held_keys["s"] = 0

    def test_coasting_with_the_key_up_is_hands_on_hips_at_once(self):
        self.airborne("WHITE")
        self.settle_flying(0.0, 0.0, "w")
        self.assertEqual(self.player.flight_pose, REACHING)
        held_keys["w"] = 0
        self.frames(10)
        self.assertGreater(self.player.flight.speed_mps, 10.0, "still coasting")
        self.assertEqual(self.player.flight_pose, HANDS_ON_HIPS)

    def test_rapid_changes_never_snap(self):
        self.airborne("BLACK", height=350.0)
        body = self.player
        largest = 0.0
        previous = (body.left_arm.rotation_x, body.left_elbow.rotation_z, body.left_leg.rotation_x)
        for step in range(240):
            if step % 40 == 0:
                held_keys["w"], held_keys["s"] = (1, 0) if step % 80 == 0 else (0, 1)
                self.aim(step * 2.0, -60.0 if step % 80 == 0 else 60.0)
            self.game.update(FRAME)
            current = (body.left_arm.rotation_x, body.left_elbow.rotation_z, body.left_leg.rotation_x)
            largest = max(largest, *(abs(a - b) for a, b in zip(current, previous)))
            previous = current
        # The full swing is 176 degrees; a frame's share at this rate is about 14% of it.
        self.assertLess(largest, 176.0 * blend_amount(FRAME) + 1.0)

    def test_boost_keeps_the_reaching_pose(self):
        for character_id in FLYERS:
            self.airborne(character_id, height=300.0)
            self.settle_flying(0.0, 0.0, "w", "shift", seconds=2.0)
            self.assertGreater(self.player.flight.speed_mps, 100.0)
            self.assertEqual(self.player.flight_pose, REACHING)
            held_keys["w"] = held_keys["shift"] = 0

    def test_target_lock_keeps_working_with_the_poses(self):
        self.airborne("GREEN", height=150.0, distance=1500.0)
        self.game.input("q")
        self.seconds(1.0)
        self.assert_hands_on_hips(self.player)
        held_keys["w"] = 1
        self.seconds(1.5)
        held_keys["w"] = 0
        self.assertEqual(self.player.flight_pose, REACHING)
        self.assertIs(self.combat.targets.manual, self.enemy)
        self.assertLess(self.reach_error(self.player), 45.0)

    def test_ai_flyers_use_the_same_poses(self):
        self.begin("WHITE", enemy="BLACK", distance=400.0)
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.enemy.position = (float(self.enemy.x), 150.0, float(self.enemy.z))
        self.seconds(2.0)
        self.assertIn(self.enemy.flight_pose, (REACHING, HANDS_ON_HIPS))
        pose = POSES[self.enemy.flight_pose]
        self.assertAlmostEqual(self.enemy.left_arm.rotation_x, pose.shoulder_x, delta=40.0)


class GroundAndCombatTests(PoseCase):
    def test_landing_returns_to_the_ground_pose_smoothly(self):
        for character_id in FLYERS:
            with self.subTest(character_id):
                self.airborne(character_id, height=25.0)
                self.settle_flying(0.0, 0.0, "w")
                held_keys["w"] = 0
                # F is a slam now, so this is the landing that Ctrl near the ground comes to.
                self.player.flight.toggle_flight(self.game.planet.normal(SimVec3(self.player.x, self.player.y, self.player.z)))
                self.assertEqual(self.player.flight.phase, FlightPhase.LANDING)
                self.frames(5)
                self.assertEqual(self.player.flight_pose, DESCENDING, "comes down standing, arms out for balance, not diving")
                for _ in range(1200):
                    self.game.update(FRAME)
                    if not self.player.flight.is_flying:
                        break
                self.assertFalse(self.player.flight.is_flying)
                before = self.player.left_arm.rotation_x
                self.frames(1)
                self.assertLess(abs(self.player.left_arm.rotation_x - before), 25.0, "no snap on touchdown")
                self.seconds(2.0)
                body = self.player
                self.assertLess(abs(body.left_arm.rotation_x), 2.0)
                self.assertLess(abs(body.left_arm.rotation_z), 2.0)
                self.assertLess(abs(body.left_elbow.rotation_z), 2.0)
                self.assertLess(abs(body.left_elbow.rotation_x), 2.0)
                held_keys["w"] = 1
                self.seconds(.5)
                held_keys["w"] = 0
                self.assertGreater(abs(body.left_leg.rotation_x) + abs(body.right_leg.rotation_x), .5, "walking")

    def test_soldier_boy_never_takes_a_flying_pose(self):
        self.begin("RED", enemy="BLACK", distance=3000.0)
        self.rig = self.game.camera
        self.game.input("f")
        held_keys["w"] = 1
        self.seconds(1.0)
        held_keys["w"] = 0
        self.assertFalse(self.player.flight.is_flying)
        self.assertAlmostEqual(self.player.left_elbow.rotation_z, 0.0)
        self.assertAlmostEqual(self.player.left_arm.rotation_z, 0.0)

    def test_a_punch_in_the_air_still_shows_and_the_pose_comes_back(self):
        self.airborne("WHITE", height=200.0, distance=4.0)
        self.tough(self.enemy)
        self.enemy.position = (float(self.player.x), float(self.player.y), float(self.player.z) + 4.0)
        self.enemy.flight.phase = FlightPhase.CRUISE
        self.seconds(1.5)
        self.game.input("=")
        self.game.input("= up")
        self.assertLess(self.player.right_arm.rotation_x, 0.0 + 8.0)
        self.game.update(FRAME)
        self.assertLess(self.player.right_arm.rotation_x, -60.0, "the swing wins while it lasts")
        self.seconds(1.0)
        self.assertGreater(self.enemy.vitals.damage_taken, 0.0)
        self.seconds(3.0)
        self.assert_hands_on_hips(self.player)

    def test_attacks_straighten_the_arm_from_a_flying_pose(self):
        self.airborne("GREEN", height=100.0, distance=300.0)
        self.tough(self.enemy)
        self.seconds(1.5)
        self.assertGreater(abs(self.player.left_elbow.rotation_z), 60.0)
        self.tap("3")
        self.seconds(.5)
        self.assertLess(abs(self.player.left_elbow.rotation_z), 15.0)
        for _ in range(600):
            self.game.update(FRAME)
            if self.player.motion is None:
                break
        self.assertIsNone(self.player.motion)


if __name__ == "__main__":
    unittest.main()
