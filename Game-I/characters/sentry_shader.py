"""Character-only lighting that preserves color at low solar intensity.

The world Sun still dims naturally through the day/night cycle. A restrained
minimum on Sentry's shader keeps its authored material colors readable in
twilight and orbit without adding another light or disabling shadows.
"""

from game.material_light_shader import make_material_light_floor_shader


GROUND_LIGHT_FLOOR = 0.42
SPACE_LIGHT_FLOOR = 0.55


def character_light_floor(atmosphere_density: float) -> float:
    """Fade a small character fill upward as atmospheric density falls."""
    density = max(0.0, min(1.0, float(atmosphere_density)))
    return GROUND_LIGHT_FLOOR + (SPACE_LIGHT_FLOOR - GROUND_LIGHT_FLOOR) * (1.0 - density)


SENTRY_LIGHT_SHADER = make_material_light_floor_shader(
    "sentry_lit_with_shadows_color_floor", "u_character_light_floor",
    GROUND_LIGHT_FLOOR)
