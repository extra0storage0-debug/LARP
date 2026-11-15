"""Timed visual effects release their scene nodes when they expire."""

import unittest
from unittest.mock import patch

from game import effects
from movement.flight_physics import Vec3 as SimVec3


class FakeEntity:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.removed = False
        self.disabled = False

    def setQuat(self, _quaternion):
        pass

    def disable(self):
        self.disabled = True

    def removeNode(self):
        self.removed = True


class FakePlanet:
    def normal(self, _position):
        return SimVec3(0.0, 1.0, 0.0)

    def surface_plane_quaternion(self, _position):
        return None


class TimedEffectLifecycleTests(unittest.TestCase):
    def test_expired_effect_removes_its_entity_and_world_reference(self):
        world = type("FakeWorld", (), {"planet": FakePlanet(), "effects": []})()
        entity = FakeEntity()
        with patch.object(effects, "Entity", return_value=entity):
            timed_effect = effects.TimedEffect(
                world, SimVec3(0, 0, 0), None, "shockwave", lifetime=.1
            )
            timed_effect.step(.1)

        self.assertTrue(entity.disabled)
        self.assertTrue(entity.removed)
        self.assertEqual(world.effects, [])

    def test_nonpositive_lifetime_is_clamped(self):
        world = type("FakeWorld", (), {"planet": FakePlanet(), "effects": []})()
        with patch.object(effects, "Entity", return_value=FakeEntity()):
            timed_effect = effects.TimedEffect(
                world, SimVec3(0, 0, 0), None, "shockwave", lifetime=0
            )
        self.assertGreater(timed_effect.lifetime, 0.0)


if __name__ == "__main__":
    unittest.main()
