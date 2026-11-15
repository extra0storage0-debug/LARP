import unittest

from game.environment import _sun_rgb
from movement.flight_physics import Vec3


class SunSpectrumTests(unittest.TestCase):
    def test_space_sun_stays_neutral_independent_of_surface_elevation(self):
        high_noon = _sun_rgb(Vec3(0, 1, 0), Vec3(0, 1, 0), 0.0)
        horizon = _sun_rgb(Vec3(0, 1, 0), Vec3(1, 0, 0), 0.0)
        below_horizon = _sun_rgb(Vec3(0, 1, 0), Vec3(0, -1, 0), 0.0)

        self.assertEqual(high_noon, (255, 255, 255))
        self.assertEqual(horizon, (255, 255, 255))
        self.assertEqual(below_horizon, (255, 255, 255))

    def test_dense_atmosphere_warms_horizon_sun_without_darkening_it(self):
        horizon = _sun_rgb(Vec3(0, 1, 0), Vec3(1, 0, 0), 1.0)
        overhead = _sun_rgb(Vec3(0, 1, 0), Vec3(0, 1, 0), 1.0)

        self.assertEqual(horizon[0], 255)
        self.assertLess(horizon[2], horizon[1])
        self.assertEqual(overhead, (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
