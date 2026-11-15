"""Build material-scoped light floors on top of Ursina's shadow shader.

The floor is applied after direct lighting and shadowing. This preserves the
single directional Sun and its shadow map while preventing authored materials
from collapsing to black at night or in shadow.
"""

from __future__ import annotations

import game.art_style  # noqa: F401  (styles the lit shader this module builds on)
from ursina import Shader
from ursina.shaders import lit_with_shadows_shader


_BASE_COLOR_LINE = (
    "fragment_color = texture(p3d_Texture0, texcoords) * p3d_ColorScale * vertex_color;"
)
_SHADOW_LINE = "fragment_color = cast_shadows(fragment_color);"


def make_material_light_floor_shader(name: str, uniform_name: str,
                                     default_floor: float) -> Shader:
    """Return the standard shadow shader with a final albedo-relative floor."""
    fragment = lit_with_shadows_shader.fragment.replace(
        "#version 150", f"#version 150\nuniform float {uniform_name};", 1)
    if _BASE_COLOR_LINE not in fragment or _SHADOW_LINE not in fragment:
        raise RuntimeError("Ursina's shadow shader changed; update material lighting safely")

    fragment = fragment.replace(
        _BASE_COLOR_LINE,
        f"vec4 material_color = {_BASE_COLOR_LINE.removeprefix('fragment_color = ').removesuffix(';')};\n"
        "    fragment_color = material_color;",
        1,
    )
    fragment = fragment.replace(
        _SHADOW_LINE,
        _SHADOW_LINE + f"\n    fragment_color.rgb = max(fragment_color.rgb, "
        f"material_color.rgb * {uniform_name});",
        1,
    )
    return Shader(
        name=name,
        language=lit_with_shadows_shader.language,
        vertex=lit_with_shadows_shader.vertex,
        fragment=fragment,
        default_input={uniform_name: float(default_floor),
                       **lit_with_shadows_shader.default_input},
        continuous_input=dict(lit_with_shadows_shader.continuous_input),
    )
