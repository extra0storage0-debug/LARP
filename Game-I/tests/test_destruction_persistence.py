import json
import tempfile
import unittest
from pathlib import Path

from world.island_generator import IslandWorld


class DestructionPersistenceTests(unittest.TestCase):
    def make_world(self, path):
        world = IslandWorld.__new__(IslandWorld)
        world.damage_save_path = Path(path)
        world.object_states = {}
        world.terrain_impacts = {}
        world._terrain_impacts_by_chunk = {}
        world.tree_states = {}
        world._damage_state_dirty = False
        world._damage_save_timer = 0.0
        return world

    def test_legacy_object_save_and_new_terrain_records_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "island_destruction.json"
            legacy = {
                "building:0:0:0": {"health": 47.5, "destroyed": False},
                IslandWorld.TERRAIN_SAVE_KEY: {
                    "0:0": {"x": 0.0, "z": 0.0, "radius": 8.0,
                            "depth": 1.5, "surface": "impact"}
                },
            }
            path.write_text(json.dumps(legacy), encoding="utf-8")
            world = self.make_world(path)
            world._load_damage_state()

            self.assertEqual(world.object_states["building:0:0:0"]["health"], 47.5)
            self.assertNotIn(IslandWorld.TERRAIN_SAVE_KEY, world.object_states)
            self.assertAlmostEqual(world.terrain_impacts["0:0"]["depth"], 1.5)
            self.assertIn((0, 0), world._terrain_impacts_by_chunk)

            world._damage_state_dirty = True
            world.save_damage_state()
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["building:0:0:0"]["health"], 47.5)
            self.assertEqual(saved[IslandWorld.TERRAIN_SAVE_KEY]["0:0"]["depth"], 1.5)
            self.assertFalse(world._damage_state_dirty)

    def test_old_object_only_save_remains_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "island_destruction.json"
            path.write_text(json.dumps({"prop:1:2:3": {
                "health": 0.0, "destroyed": True}}), encoding="utf-8")
            world = self.make_world(path)
            world._load_damage_state()
            self.assertEqual(world.object_states["prop:1:2:3"],
                             {"health": 0.0, "destroyed": True})
            self.assertEqual(world.terrain_impacts, {})

    def test_tree_health_and_destroyed_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "island_destruction.json"
            path.write_text(json.dumps({IslandWorld.TREE_SAVE_KEY: {
                "tree:0:0:1": {"health": 30.0, "destroyed": False},
                "tree:0:0:2": {"health": 0.0, "destroyed": True},
                "invalid": {"health": -40.0},
            }}), encoding="utf-8")
            world = self.make_world(path)
            world._load_damage_state()
            self.assertEqual(world.tree_states["tree:0:0:1"],
                             {"health": 30.0, "destroyed": False})
            self.assertEqual(world.tree_states["tree:0:0:2"],
                             {"health": 0.0, "destroyed": True})
            self.assertNotIn("invalid", world.tree_states)

            world._damage_state_dirty = True
            world.save_damage_state()
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved[IslandWorld.TREE_SAVE_KEY]["tree:0:0:1"]["health"], 30.0)
            self.assertTrue(saved[IslandWorld.TREE_SAVE_KEY]["tree:0:0:2"]["destroyed"])


if __name__ == "__main__":
    unittest.main()
