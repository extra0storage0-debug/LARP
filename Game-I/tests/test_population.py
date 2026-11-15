import unittest

from ai.civilian_ai import CivilianBrain, CivilianState
from movement.flight_physics import Vec3
from world.population import (
    civilian_capacity,
    civilians_per_chunk,
    traffic_capacity,
    traffic_per_chunk,
)


class PopulationSettingsTests(unittest.TestCase):
    def test_density_is_district_aware_and_scales(self):
        self.assertGreater(civilians_per_chunk("downtown", "high"),
                           civilians_per_chunk("rural", "high"))
        self.assertGreater(civilians_per_chunk("downtown", "ultra"),
                           civilians_per_chunk("downtown", "medium"))
        self.assertEqual(civilians_per_chunk("forest", "low"), 0)
        self.assertGreater(traffic_per_chunk("downtown", "medium"),
                           traffic_per_chunk("rural", "medium"))

    def test_population_caps_respect_quality_and_density(self):
        self.assertLessEqual(civilian_capacity("low", "ultra", 30), 32)
        self.assertLess(civilian_capacity("low", "ultra", 30),
                        civilian_capacity("high", "ultra", 30))
        self.assertLessEqual(traffic_capacity("low", "ultra"), 12)
        self.assertLess(traffic_capacity("low", "high"),
                        traffic_capacity("high", "high"))


class CivilianCombatTests(unittest.TestCase):
    def test_danger_causes_fleeing_and_ends_in_walking(self):
        npc = CivilianBrain(Vec3(4, 0, 0))
        npc.step(.05, danger=Vec3())
        self.assertEqual(npc.state, CivilianState.FLEEING)
        self.assertGreater(npc.position.x, 4)
        for _ in range(60):
            npc.step(.1)
        self.assertEqual(npc.state, CivilianState.WALKING)

    def test_damage_transitions_through_injured_to_permanent_dead(self):
        npc = CivilianBrain(Vec3())
        self.assertEqual(npc.apply_damage(65), 65)
        self.assertEqual(npc.state, CivilianState.INJURED)
        self.assertTrue(npc.alive)
        self.assertEqual(npc.apply_damage(40), 35)
        self.assertEqual(npc.state, CivilianState.DEAD)
        self.assertFalse(npc.alive)
        self.assertEqual(npc.apply_damage(100), 0)


if __name__ == "__main__":
    unittest.main()
