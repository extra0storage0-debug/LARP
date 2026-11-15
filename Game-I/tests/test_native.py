"""The compiled maths must give the game's own answers, and the game must run without it."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest import mock

from game_fixture import reset_game
from world import native_bridge as native
from world.island_generator import IslandWorld

ROOT = Path(__file__).resolve().parent.parent
CLOSE = 1e-8
AROUND_THE_ISLAND = 6000.0


@unittest.skipUnless(native.available, "the compiled module is not in use here")
class SameAnswersTests(unittest.TestCase):
    def setUp(self):
        self.game = reset_game()
        self.world = self.game.world
        self.rng = random.Random(2026)

    def points(self, count: int = 4000) -> list:
        spread = [(self.rng.uniform(-AROUND_THE_ISLAND, AROUND_THE_ISLAND),
                   self.rng.uniform(-AROUND_THE_ISLAND, AROUND_THE_ISLAND)) for _ in range(count)]
        return spread + [(0.0, 0.0), (5000.0, 0.0), (-5000.0, 5000.0), (500.0, -500.0), (1450.0, 2900.0)]

    def python_height(self, x: float, z: float) -> float:
        """The original, all the way down, with the Python base height too."""
        with mock.patch.object(self.world, "_base_height_at",
                               lambda a, b: IslandWorld._base_height_at(self.world, a, b)):
            return IslandWorld.height_at(self.world, x, z)

    def test_base_height(self):
        for x, z in self.points():
            self.assertAlmostEqual(self.world._base_height_at(x, z),
                                   IslandWorld._base_height_at(self.world, x, z), delta=CLOSE)

    def test_height_with_no_craters(self):
        for x, z in self.points(1500):
            self.assertAlmostEqual(self.world.height_at(x, z), self.python_height(x, z), delta=CLOSE)

    def test_height_with_many_overlapping_craters_across_chunks(self):
        for _ in range(60):
            x, z = self.rng.uniform(-900.0, 900.0), self.rng.uniform(-900.0, 900.0)
            self.world.deform_terrain(type("P", (), {"x": x, "z": z})(), radius=self.rng.uniform(2.0, 80.0),
                                      depth=self.rng.uniform(.1, 7.0))
        self.world.deform_terrain(type("P", (), {"x": 100.0, "z": 100.0})(), radius=30.0, depth=2.0)
        self.world.deform_terrain(type("P", (), {"x": 100.0, "z": 100.0})(), radius=50.0, depth=2.0)  # grows it
        checked = 0
        for _ in range(2500):
            x, z = self.rng.uniform(-1100.0, 1100.0), self.rng.uniform(-1100.0, 1100.0)
            self.assertAlmostEqual(self.world.height_at(x, z), self.python_height(x, z), delta=CLOSE)
            checked += abs(self.world.height_at(x, z) - self.world._base_height_at(x, z)) > .001
        self.assertGreater(checked, 100, "the test did reach the craters")

    def test_the_oldest_crater_being_forgotten_is_reflected(self):
        with mock.patch.object(self.world, "MAX_TERRAIN_IMPACTS", 3):
            for index in range(8):
                self.world.deform_terrain(type("P", (), {"x": 40.0 * index, "z": 0.0})(), radius=10.0, depth=3.0)
        self.assertEqual(len(self.world.terrain_impacts), 3)
        self.world._sync_native_craters()
        for index in range(8):
            self.assertAlmostEqual(self.world.height_at(40.0 * index, 0.0),
                                   self.python_height(40.0 * index, 0.0), delta=CLOSE)

    def test_surface_height(self):
        self.world.deform_terrain(type("P", (), {"x": 50.0, "z": 50.0})(), radius=40.0, depth=4.0)
        for x, z in self.points(800):
            compiled = self.world._terrain_surface_height(x, z)
            with mock.patch.object(native, "available", False), \
                    mock.patch.object(self.world, "_base_height_at",
                                      lambda a, b: IslandWorld._base_height_at(self.world, a, b)), \
                    mock.patch.object(self.world, "height_at", self.python_height):
                original = self.world._terrain_surface_height(x, z)
            self.assertAlmostEqual(compiled, original, delta=1e-6)

    def test_painted_colour(self):
        for x, z in self.points(2500):
            height = self.world._base_height_at(x, z)
            compiled = self.world._paint_terrain(x, z, height)
            with mock.patch.object(native, "available", False), \
                    mock.patch.object(self.world, "_base_height_at",
                                      lambda a, b: IslandWorld._base_height_at(self.world, a, b)):
                original = self.world._paint_terrain(x, z, IslandWorld._base_height_at(self.world, x, z))
            for channel in range(3):
                self.assertAlmostEqual(compiled[channel], original[channel], delta=1.01 / 255.0, msg=(x, z))

    def test_batch_equals_one_at_a_time_on_either_side_of_the_thread_threshold(self):
        self.world.deform_terrain(type("P", (), {"x": 10.0, "z": 10.0})(), radius=30.0, depth=4.0)
        for count in (5, 1999, 2000, 2001, 9000):
            points = [(self.rng.uniform(-5500.0, 5500.0), self.rng.uniform(-5500.0, 5500.0)) for _ in range(count)]
            self.assertEqual(native.heights(points), [self.world.height_at(x, z) for x, z in points], count)
            self.assertEqual(native.paint_many(points),
                             [native.paint(x, z, self.world._base_height_at(x, z)) for x, z in points], count)

    def test_cape(self):
        player = self.game.teams.characters["YELLOW"]
        if player.uses_skinned_body:
            self.skipTest("the skinned bodies' capes deform on the GPU; this grid is only the fallback body's")
        for time, speed, forward, right in ((0.0, 0.0, 0.0, 0.0), (3.7, 40.0, 300.0, -90.0), (91.0, 900.0, -900.0, 900.0)):
            player._animation_time = time
            player._airflow_forward, player._airflow_right = forward, right
            wind = min(1.0, speed / 150.0)
            grid = native.CapeGrid(player._cape_rows, player._cape_cols, player._cape_vertices)
            moved, trim = grid.deform(time, wind, forward, right)
            original_trim, _triangles = player._cape_trim_geometry(moved)
            self.assertEqual(len(moved), len(player._cape_vertices))
            self.assertEqual(len(trim), len(original_trim))
            for a, b in zip(trim, original_trim):
                for one, two in zip(a, b):
                    self.assertAlmostEqual(one, two, delta=CLOSE)
            rows = player._cape_rows
            for row in range(rows):
                row_alpha = row / max(1, rows - 1)
                for col in range(player._cape_cols):
                    from math import sin
                    x, y, z = player._cape_vertices[row * player._cape_cols + col]
                    wave = sin(time * 7.0 + col * .72 + row * .55)
                    expected = (x + wave * .055 * wind * row_alpha, y,
                                z + max(-.34, min(.34, forward / 520.0)) * row_alpha
                                + max(-.22, min(.22, right / 520.0)) * row_alpha
                                - abs(wave) * .34 * wind * row_alpha - max(0.0, wave) * .045 * wind * row_alpha)
                    for one, two in zip(moved[row * player._cape_cols + col], expected):
                        self.assertAlmostEqual(one, two, delta=CLOSE)


class FallbackTests(unittest.TestCase):
    def test_a_missing_dll_just_means_no_compiled_maths(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("SENTRY_NO_NATIVE", None)
            with mock.patch.object(Path, "resolve", lambda self: Path("C:/nowhere/at/all/x.py")):
                reloaded = importlib.reload(native)
                self.assertFalse(reloaded.available)
        importlib.reload(native)

    def test_the_whole_game_starts_without_it(self):
        result = subprocess.run([sys.executable, str(ROOT / "main.py"), "--smoke-test"], cwd=ROOT,
                                env=dict(os.environ, SENTRY_NO_NATIVE="1"), capture_output=True, timeout=240)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
