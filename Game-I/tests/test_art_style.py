"""The art direction's rules: cheap per frame, frozen with time, and free of old artefacts."""

import unittest

from ursina.shaders import lit_with_shadows_shader

from game.art_style import (FOG_DENSITY, SKY_SHADER, SOFT_GLOW_SHADER, VEGETATION_SHADER,
                            WATER_SHADER, cloud_noise_texture, shade)
from characters.sentry_shader import SENTRY_LIGHT_SHADER
from ursina import color
from game_fixture import reset_game, run_frames

FRAME = 1.0 / 60.0


class StyleRuleTests(unittest.TestCase):
    def test_no_shader_makes_ursina_touch_every_entity_each_frame(self):
        for shader in (lit_with_shadows_shader, VEGETATION_SHADER, SENTRY_LIGHT_SHADER):
            self.assertEqual(dict(shader.continuous_input), {}, shader.name)

    def test_every_lit_shader_shares_the_fog(self):
        for shader in (lit_with_shadows_shader, VEGETATION_SHADER, SENTRY_LIGHT_SHADER):
            self.assertIn("u_fog_density", shader.fragment, shader.name)
        self.assertIn("u_fog_density", WATER_SHADER.fragment)

    def test_higher_quality_sees_further(self):
        self.assertGreater(FOG_DENSITY["low"], FOG_DENSITY["medium"])
        self.assertGreater(FOG_DENSITY["medium"], FOG_DENSITY["high"])

    def test_shade_carries_wind_in_alpha_and_never_overflows(self):
        tint = shade(color.rgb32(200, 240, 100), 2.0, .7)
        self.assertLessEqual(max(tint.r, tint.g, tint.b), 1.0)
        self.assertAlmostEqual(tint.a, .3)
        self.assertEqual(shade(color.rgb32(10, 10, 10), 1.0).a, 1.0)

    def test_cloud_tile_has_real_variation(self):
        texture = cloud_noise_texture(32)
        pixels = bytes(texture.getRamImage())
        self.assertEqual(len(pixels), 32 * 32)
        self.assertGreater(max(pixels) - min(pixels), 60)

    def test_soft_glow_is_unlit(self):
        self.assertNotIn("p3d_LightSource", SOFT_GLOW_SHADER.fragment)
        self.assertNotIn("sin(", SKY_SHADER.fragment.split("void main")[0])


class InGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = reset_game()

    def test_wind_waves_and_clouds_run_on_world_time(self):
        environment = self.game.environment
        run_frames(self.game, 1)
        before = environment._world_time[0]
        run_frames(self.game, 1)
        self.assertGreater(environment._world_time[0], before)

    def test_sky_follows_the_camera(self):
        from ursina import camera
        self.game.update(FRAME)
        offset = self.game.environment.sky.position - camera.world_position
        self.assertLess(offset.length(), 200.0)

    def test_terrain_paint_is_cached_and_lit_from_the_sun_side(self):
        world = self.game.world
        first = world._terrain_color(123.0, 456.0, world._base_height_at(123.0, 456.0))
        self.assertIs(world._terrain_color(123.0, 456.0, 0.0), first)

    def test_beach_is_warmer_than_grass(self):
        world = self.game.world
        grass = world._paint_terrain(100.0, 100.0, world._base_height_at(100.0, 100.0))
        beach_x = 4950.0
        beach = world._paint_terrain(beach_x, 0.0, world._base_height_at(beach_x, 0.0))
        self.assertGreater(beach.r, grass.r)
        self.assertGreater(beach.b, grass.b)

    def test_trees_and_grass_stay_planted_and_move_at_the_top(self):
        for chunk in self.game.world.chunks.values():
            if chunk.lod_colors:
                winds = {round(1.0 - c.a, 3) for c in chunk.lod_colors}
                self.assertIn(0.0, winds)
                self.assertGreater(max(winds), .2)
                return
        self.fail("no vegetation")


if __name__ == "__main__":
    unittest.main()
