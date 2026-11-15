"""Walking and running as a body really does them. The measure is the foot itself, in the world, in the running game."""

from __future__ import annotations

import unittest

from panda3d.core import LVector3f
from ursina import held_keys, scene

from movement.flight_physics import Vec3 as SimVec3
from movement.gait import MIN_DUTY, foot_at, leg_angles, leg_shape, plan_for
from test_gameplay_control_update import LiveCase

SHAPE = leg_shape((-.18, 1.48, -.004), (-.24, .63, .05), (-.33, -.12, .013))
FEET = ("foot_l", "foot_r")
ROSTER = ("WHITE", "BLACK", "YELLOW", "GREEN", "RED")


class GaitMathsTests(unittest.TestCase):
    def test_standing_straight_needs_no_rotation(self):
        thigh, knee, foot = leg_angles(SHAPE, 0.0, 0.0, SHAPE.hip_z, SHAPE.hip_y * .995, 0.0)
        self.assertLess(abs(thigh), 6.0)
        self.assertLess(abs(knee), 9.0)
        self.assertLess(abs(foot + thigh + knee), 1e-6)

    def test_the_solved_leg_really_reaches_the_foot(self):
        from math import cos, radians, sin
        for ankle_z, ankle_y in ((.5, .0), (-.5, .1), (.0, .4), (.3, .25), (-.5, .6)):
            hip_y = SHAPE.hip_y - .1
            thigh, knee, _ = leg_angles(SHAPE, ankle_z, ankle_y, SHAPE.hip_z, hip_y, 0.0)
            upper = radians(thigh + SHAPE.thigh_rest)
            lower = radians(thigh + knee + SHAPE.shin_rest)
            z = SHAPE.hip_z - sin(upper) * SHAPE.thigh - sin(lower) * SHAPE.shin
            y = hip_y - cos(upper) * SHAPE.thigh - cos(lower) * SHAPE.shin
            self.assertAlmostEqual(z, ankle_z, 3)
            self.assertAlmostEqual(y, ankle_y, 3)
            self.assertGreaterEqual(knee + SHAPE.shin_rest - SHAPE.thigh_rest, -1e-6, "a knee only bends forward")

    def test_a_planted_foot_moves_back_at_exactly_the_speed_of_the_body(self):
        for speed in (1.5, 3.0, 8.0, 15.0):
            plan = plan_for(speed, SHAPE)
            self.assertGreater(plan.duty, MIN_DUTY, speed)
            step = 1e-3
            # In the flat part of the stance, the ankle is the contact.
            a = foot_at(plan.duty * .3, plan, SHAPE)[0]
            b = foot_at(plan.duty * .3 + step, plan, SHAPE)[0]
            self.assertAlmostEqual((a - b) / step * plan.frequency, speed, 2, f"at {speed} m/s")

    def test_the_foot_rolls_from_heel_to_ball(self):
        plan = plan_for(3.0, SHAPE)
        self.assertLess(foot_at(0.0, plan, SHAPE)[2], -10.0, "toes up as the heel lands")
        self.assertEqual(foot_at(plan.duty * .35, plan, SHAPE)[2], 0.0, "flat in the middle")
        self.assertGreater(foot_at(plan.duty * .99, plan, SHAPE)[2], 25.0, "heel up as it leaves")

    def test_there_is_no_jump_anywhere_in_the_cycle(self):
        for speed in (.8, 3.0, 5.0, 9.0, 20.0):
            plan = plan_for(speed, SHAPE)
            previous = foot_at(0.0, plan, SHAPE)
            for index in range(1, 2001):
                now = foot_at(index / 2000.0, plan, SHAPE)
                self.assertLess(abs(now[0] - previous[0]) + abs(now[1] - previous[1]), .03, f"{speed} m/s, {index}")
                previous = now

    def test_walking_and_running_are_different_cycles(self):
        walk, run = plan_for(3.0, SHAPE), plan_for(12.0, SHAPE)
        self.assertGreater(walk.duty, .5, "a walk always has a foot down")
        self.assertLess(run.duty, .5, "a run has moments with neither down")
        self.assertGreater(run.frequency, walk.frequency)
        self.assertGreater(run.clearance, walk.clearance * 2.0)


class FootTests(LiveCase):
    def setUp(self):
        self.begin("WHITE", "RED", 400.0)
        self.addCleanup(lambda: [held_keys.__setitem__(key, 0) for key in ("w", "a", "s", "d", "shift")])

    def speed_of(self, pace: float, run: bool = False) -> None:
        ground = self.player.ground
        if run:
            ground.walk_speed = pace
            ground.sprint_multiplier = 1.0
            ground.max_running_speed = pace
        else:
            ground.walk_pace = pace

    def feet(self):
        visual = self.player.visual
        return [visual._controls[name].getPos(scene) for name in FEET]

    def height(self, point) -> float:
        return float(point.y) - self.game.world.height_at(float(point.x), float(point.z))

    def contacts(self):
        """The heel and the ball of each foot: what really touches the ground. The ankle above them moves as the foot rolls."""
        visual, shape = self.player.visual, self.player.visual._leg_shape
        points = []
        for name in FEET:
            node = visual._controls[name]
            points.append(scene.getRelativePoint(node, LVector3f(0.0, -shape.sole, -shape.heel)))
            points.append(scene.getRelativePoint(node, LVector3f(0.0, -shape.sole, shape.ball)))
        return points

    def worst_slide(self, seconds: float) -> tuple[float, int]:
        """The furthest a heel or ball travels over the ground, while it is down."""
        worst, contacts = 0.0, 0
        planted = [None] * 4
        floor = min(self.height(point) for point in self.contacts())
        for _ in range(int(seconds * 60)):
            self.frames(1)
            points = self.contacts()
            floor = min(floor, min(self.height(point) for point in points))
            for index, point in enumerate(points):
                down = self.height(point) < floor + .035 and self.player.visual.foot_is_planted(index // 2)
                if not down:
                    planted[index] = None
                elif planted[index] is None:
                    planted[index] = (float(point.x), float(point.z))
                    contacts += 1
                else:
                    dx, dz = float(point.x) - planted[index][0], float(point.z) - planted[index][1]
                    worst = max(worst, (dx * dx + dz * dz) ** .5)
        return worst, contacts

    def test_every_character_walks_without_sliding(self):
        for character_id in ROSTER:
            with self.subTest(character_id):
                self.begin(character_id, "RED" if character_id != "RED" else "WHITE", 400.0)
                self.speed_of(3.0)
                held_keys["w"] = 1
                self.seconds(1.5)
                slide, contacts = self.worst_slide(3.0)
                held_keys["w"] = 0
                self.assertGreaterEqual(contacts, 3)
                self.assertLess(slide, .07, f"{slide:.3f} m in {contacts} contacts")

    def test_a_jog_does_not_slide_either(self):
        self.speed_of(9.0, run=True)
        held_keys["w"] = held_keys["shift"] = 1
        self.seconds(1.5)
        slide, contacts = self.worst_slide(3.0)
        self.assertGreaterEqual(contacts, 3)
        self.assertLess(slide, .12, f"{slide:.3f} m in {contacts} contacts")

    def test_sideways_and_backward_steps_do_not_slide(self):
        for key in ("a", "d", "s"):
            with self.subTest(key):
                self.begin("WHITE", "RED", 400.0)
                self.speed_of(2.5)
                held_keys[key] = 1
                self.seconds(1.2)
                slide, contacts = self.worst_slide(2.5)
                held_keys[key] = 0
                self.assertGreaterEqual(contacts, 2)
                self.assertLess(slide, .12, f"{key}: {slide:.3f} m in {contacts} contacts")

    def test_a_foot_is_always_near_the_ground_at_a_walk(self):
        self.speed_of(3.0)
        held_keys["w"] = 1
        self.seconds(1.2)
        lows = []
        for _ in range(180):
            self.frames(1)
            lows.append(min(self.height(point) for point in self.feet()))
        self.assertLess(max(lows) - min(lows), .14, "no floating, and nothing through the ground")

    def test_the_rate_follows_the_real_speed(self):
        rates = []
        for pace in (1.5, 3.0):
            self.begin("WHITE", "RED", 400.0)
            self.speed_of(pace)
            held_keys["w"] = 1
            self.seconds(1.5)
            start = self.player._stride_phase
            self.seconds(2.0)
            rates.append((self.player._stride_phase - start) / 2.0)
            held_keys["w"] = 0
        self.assertGreater(rates[1], rates[0])

    def test_standing_is_still_and_the_walk_builds_up_and_dies_away(self):
        self.seconds(.5)
        self.assertEqual(self.player.visual._gait, 0.0)
        held_keys["w"] = 1
        speeds = []
        for _ in range(40):
            self.frames(1)
            speeds.append(self.player.ground.velocity.length())
        self.assertLess(speeds[4], 1.0, "not at full walking pace at once")
        self.assertGreater(speeds[-1], 2.0)
        held_keys["w"] = 0
        self.seconds(1.5)
        self.assertEqual(self.player.visual._gait, 0.0)
        self.assertLess(abs(self.player.left_leg.rotation_x), 2.0, "back to a standing leg")

    def test_w_walks_and_shift_is_as_fast_as_it_ever_was(self):
        self.assertEqual(self.player.ground.walk_pace, 3.0)
        held_keys["w"] = 1
        self.seconds(1.5)
        self.assertLess(self.player.ground.velocity.length(), 3.1)
        held_keys["shift"] = 1
        self.seconds(4.0)
        self.assertGreater(self.player.ground.velocity.length(), self.player.own_run_speed * .95)

    def test_ai_does_not_walk_it_still_gets_there(self):
        self.assertIsNone(self.game.teams.characters["RED"].ground.walk_pace)

    def test_the_hips_and_shoulders_turn_against_each_other(self):
        visual = self.player.visual
        self.speed_of(3.0)
        held_keys["w"] = 1
        self.seconds(1.2)
        for _ in range(60):
            self.frames(1)
            if abs(visual._pelvis.rotation_y) > 2.0:
                self.assertLess(visual._pelvis.rotation_y * visual._spine.rotation_y, 0.0)
                return
        self.fail("the hips never turned")

    def test_the_left_hip_goes_forward_with_the_left_foot(self):
        visual = self.player.visual
        self.speed_of(3.0)
        held_keys["w"] = 1
        self.seconds(1.2)
        checked = 0
        for _ in range(90):
            self.frames(1)
            if abs(visual._pelvis.rotation_y) > 3.0:
                left = visual._controls["thigh_l"].getPos(visual.pose_root).z
                right = visual._controls["thigh_r"].getPos(visual.pose_root).z
                foot_left = visual._controls["foot_l"].getPos(visual.pose_root).z
                foot_right = visual._controls["foot_r"].getPos(visual.pose_root).z
                self.assertGreater((left - right) * (foot_left - foot_right), 0.0)
                checked += 1
        self.assertGreater(checked, 5)

    def test_a_turn_on_the_spot_takes_steps(self):
        self.seconds(.3)
        before = self.player._stride_phase
        for index in range(60):
            self.game.camera.yaw += 3.0
            self.frames(1)
        self.assertGreater(self.player._stride_phase, before + .5)
        self.seconds(1.0)
        self.assertEqual(self.player.visual._gait, 0.0)

    def test_a_running_take_off_leaves_the_walk_behind(self):
        held_keys["w"] = held_keys["shift"] = 1
        self.seconds(1.0)
        held_keys["w"] = held_keys["shift"] = 0
        self.game.input("f")
        self.seconds(1.5)
        self.assertEqual(self.player.visual._gait, 0.0)
        self.assertLess(self.player.visual.left_knee.rotation_x, 20.0)


class CameraTests(LiveCase):
    def test_something_passing_the_lens_does_not_jerk_the_view(self):
        from game import camera_manager
        from unittest import mock
        self.begin("WHITE", "RED", 400.0)
        self.seconds(1.0)
        from ursina import camera
        steady = (camera.world_position - self.player.position).length()
        real = camera_manager.world_raycast

        class Hit:
            hit, distance = True, 2.0

        with mock.patch.object(camera_manager, "world_raycast", lambda *a, **k: Hit()):
            self.frames(2)
            self.assertLess(abs((camera.world_position - self.player.position).length() - steady), .5, "two frames of debris")
            self.frames(6)
            self.assertLess((camera.world_position - self.player.position).length(), steady - 2.0, "a wall still brings it in")
        self.assertIs(camera_manager.world_raycast, real)


if __name__ == "__main__":
    unittest.main()
