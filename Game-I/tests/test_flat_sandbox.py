"""Flat sandbox frame stays level and provides stable movement coordinates."""

import unittest

from movement.flight_physics import Vec3
from world.flat_sandbox import FlatSandboxFrame


class FlatSandboxFrameTests(unittest.TestCase):
    def setUp(self):
        self.frame = FlatSandboxFrame()

    def test_ground_projection_and_movement_keep_a_constant_height(self):
        position = Vec3(12.0, 7.0, -8.0)
        projected = self.frame.project(position, 0.25)
        moved = self.frame.tangent_move(position, Vec3(4.0, 0.0, 9.0), 0.25)

        self.assertEqual(projected, Vec3(12.0, 0.25, -8.0))
        self.assertEqual(moved, Vec3(16.0, 0.25, 1.0))
        self.assertEqual(self.frame.normal(position), Vec3(0.0, 1.0, 0.0))

    def test_heading_and_gravity_use_a_fixed_up_axis(self):
        forward = self.frame.heading(Vec3(), 0.0)
        east = self.frame.heading(Vec3(), 90.0)
        gravity = self.frame.gravity(Vec3())

        self.assertAlmostEqual(forward.z, 1.0)
        self.assertAlmostEqual(east.x, 1.0)
        self.assertEqual(gravity, Vec3(0.0, -9.80665, 0.0))

    def test_local_coordinates_do_not_curve_with_distance(self):
        point = self.frame.point_from_local(250_000.0, -125_000.0, 0.25)
        self.assertEqual(point, Vec3(250_000.0, 0.25, -125_000.0))
        self.assertEqual(self.frame.local_coordinates(point), (250_000.0, -125_000.0))


if __name__ == "__main__":
    unittest.main()
