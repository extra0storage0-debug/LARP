import unittest
from random import Random

from ai.civilian_ai import CivilianBrain, CivilianState
from movement.flight_physics import Vec3


class CivilianAITests(unittest.TestCase):
    def test_nearby_danger_causes_flee_state(self):
        npc = CivilianBrain(Vec3(4, 0, 0))
        npc.step(0.05, danger=Vec3(), rng=Random(4))
        self.assertEqual(npc.state, CivilianState.FLEE)
        self.assertGreater(npc.position.x, 4)

    def test_flee_state_returns_to_wander(self):
        npc = CivilianBrain(Vec3(10, 0, 0))
        npc.react_to_danger(Vec3(), Random(1))
        for _ in range(50):
            npc.step(0.1, rng=Random(1))
        self.assertEqual(npc.state, CivilianState.WANDER)


if __name__ == "__main__":
    unittest.main()
