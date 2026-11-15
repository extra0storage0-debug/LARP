import unittest
from unittest.mock import patch

import game.world_raycast as world_raycast_module


class WorldRaycastTests(unittest.TestCase):
    def test_shared_ray_entity_is_reset_before_each_cast(self):
        calls = []

        class RayEntity:
            def setQuat(self, quaternion):
                calls.append("reset")

        sentinel = object()

        def cast(*args, **kwargs):
            calls.append("cast")
            return sentinel

        with patch.object(world_raycast_module, "_raycaster", RayEntity()), \
                patch.object(world_raycast_module, "raycast", side_effect=cast):
            result = world_raycast_module.world_raycast((0, 0, 0), (1, 0, 0))

        self.assertIs(result, sentinel)
        self.assertEqual(calls, ["reset", "cast"])


if __name__ == "__main__":
    unittest.main()
