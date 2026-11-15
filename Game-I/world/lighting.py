"""Lighting correction for authored city surfaces and building facades."""

from game.material_light_shader import make_material_light_floor_shader


CITY_SURFACE_LIGHT_FLOOR = 0.55
CITY_SURFACE_SHADER = make_material_light_floor_shader(
    "city_surfaces_with_natural_shadow_fill", "u_city_light_floor",
    CITY_SURFACE_LIGHT_FLOOR)
