import unittest

from characters.sentry_shader import (GROUND_LIGHT_FLOOR, SENTRY_LIGHT_SHADER,
                                    SPACE_LIGHT_FLOOR, character_light_floor)
from world.lighting import CITY_SURFACE_LIGHT_FLOOR, CITY_SURFACE_SHADER


class CharacterLightingTests(unittest.TestCase):
    def test_character_light_floor_preserves_some_shading(self):
        ground = character_light_floor(1.0)
        space = character_light_floor(0.0)
        self.assertEqual(ground, GROUND_LIGHT_FLOOR)
        self.assertEqual(space, SPACE_LIGHT_FLOOR)
        self.assertGreater(ground, 0.0)
        self.assertLess(space, 1.0)
        self.assertLess(ground, space)
        self.assertIn("uniform float u_character_light_floor;",
                      SENTRY_LIGHT_SHADER.fragment)
        shadow_pass = SENTRY_LIGHT_SHADER.fragment.index(
            "fragment_color = cast_shadows(fragment_color);")
        light_floor = SENTRY_LIGHT_SHADER.fragment.index(
            "material_color.rgb * u_character_light_floor")
        self.assertGreater(light_floor, shadow_pass)

    def test_character_fill_changes_smoothly_with_atmospheric_density(self):
        values = [character_light_floor(density)
                  for density in (1.0, .75, .5, .25, 0.0)]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(0.0 < value < 1.0 for value in values))

    def test_character_shader_keeps_the_sun_shadow_map(self):
        self.assertIn("textureProj(p3d_LightSource[i].shadowMap, coord)",
                      SENTRY_LIGHT_SHADER.fragment)

    def test_city_material_floor_is_applied_after_sun_shadows(self):
        fragment = CITY_SURFACE_SHADER.fragment
        self.assertGreater(CITY_SURFACE_LIGHT_FLOOR, 0.0)
        shadow_pass = fragment.index("fragment_color = cast_shadows(fragment_color);")
        light_floor = fragment.index("material_color.rgb * u_city_light_floor")
        self.assertGreater(light_floor, shadow_pass)


if __name__ == "__main__":
    unittest.main()
