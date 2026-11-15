import unittest

from world.destruction_math import (crater_height_delta, superhuman_impact_damage,
                                   sweep_point_aabb)


class DestructionMathTests(unittest.TestCase):
    def test_crater_has_a_bowl_ejecta_rim_and_flat_outer_edge(self):
        self.assertLess(crater_height_delta(0, 10, 2), 0)
        self.assertGreater(crater_height_delta(8.6, 10, 2), 0)
        self.assertEqual(crater_height_delta(13, 10, 2), 0)

    def test_segment_sweep_reports_entry_face_and_rejects_misses(self):
        hit = sweep_point_aabb((-5, 0, 0), (5, 0, 0), (-1, -1, -1), (1, 1, 1))
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit[0], .4)
        self.assertEqual(hit[1], (-1.0, 0.0, 0.0))
        self.assertIsNone(sweep_point_aabb((-5, 3, 0), (5, 3, 0),
                                            (-1, -1, -1), (1, 1, 1)))

    def test_impact_damage_scales_nonlinearly_with_normal_speed(self):
        low = superhuman_impact_damage(18)
        medium = superhuman_impact_damage(35)
        high = superhuman_impact_damage(70)
        extreme = superhuman_impact_damage(150)
        self.assertGreater(medium, low * 4)
        self.assertGreater(high, medium * 4)
        self.assertGreater(extreme, high)
        self.assertLessEqual(superhuman_impact_damage(100_000), 12_000)


if __name__ == "__main__":
    unittest.main()
