"""The game's one art direction: a warm late-afternoon palette and its cheap shaders.

Sunlight on terrain is baked into vertex colours, so hills cost nothing per frame.
The sky is one dome, the sea is one quad, and fog, grading and wind are a few lines
added to Ursina's lit shader, so every lit object shares one look. Importing this
module installs that look, so it must be imported before anything compiles a shader.
"""

from __future__ import annotations

from math import cos, pi, sin
from random import Random

from panda3d.core import SamplerState, Texture
from ursina import Entity, Mesh, Shader, color
from ursina.shaders import lit_with_shadows_shader

SUN_DIRECTION = (-.46, .52, -.72)  # towards the sun, normalized in use
HORIZON = (.87, .80, .71)
SKY_MID = (.56, .73, .86)
SKY_ZENITH = (.21, .42, .69)
SUN_COLOR = (255, 243, 224)
FOG_DENSITY = {"low": .00026, "medium": .00023, "high": .00020, "ultra": .00018}
FOG_DEFAULT = FOG_DENSITY["low"]


def _vec3(values) -> str:
    return f"vec3({values[0]}, {values[1]}, {values[2]})"


# Exponential-squared fog hides the far clip; grading cools shade and warms light.
_FOG_AND_GRADE = f"""
    float luminance = dot(fragment_color.rgb, vec3(.3, .59, .11));
    fragment_color.rgb = mix(fragment_color.rgb * vec3(.90, .96, 1.10),
                             fragment_color.rgb * vec3(1.07, 1.01, .92),
                             smoothstep(.12, .78, luminance));
    float fog_amount = length(vertex_position) * u_fog_density;
    fragment_color.rgb = mix({_vec3(HORIZON)}, fragment_color.rgb,
                             exp(-fog_amount * fog_amount));
}}
"""
_FRAGMENT_TAIL = "    float distance_to_camera = length(vertex_world_position.xyz - camera_world_position);"


def _stylize(fragment: str) -> str:
    start = fragment.index(_FRAGMENT_TAIL)
    return (fragment[:start].replace("#version 150", "#version 150\nuniform float u_fog_density;", 1)
            + _FOG_AND_GRADE)


if _FRAGMENT_TAIL not in lit_with_shadows_shader.fragment and "u_fog_density" not in (
        lit_with_shadows_shader.fragment):
    raise RuntimeError("Ursina's lit shader changed; update game/art_style.py")
if "u_fog_density" not in lit_with_shadows_shader.fragment:
    lit_with_shadows_shader.fragment = _stylize(lit_with_shadows_shader.fragment)
    lit_with_shadows_shader.compiled = False
    # Only the old fog read the camera position. Ursina re-sent it to every lit entity
    # each frame, which cost more than all of the rendering put together.
    lit_with_shadows_shader.continuous_input = {}
    # Shadows are a soft neutral cool, so Medium and High match Low's colours.
    lit_with_shadows_shader.default_input["shadow_color"] = color.rgba(.10, .14, .30, .15)
    # 2x2 shadow samples instead of 4x4: a quarter of the texture reads on every lit pixel.
    lit_with_shadows_shader.default_input["shadow_samples"] = 2

_WIND_VERTEX = lit_with_shadows_shader.vertex.replace(
    "void main() {\n"
    "    gl_Position = p3d_ModelViewProjectionMatrix * vertex;\n"
    "    vertex_position = vec3(p3d_ModelViewMatrix * vertex);\n"
    "    vertex_world_position = (p3d_ModelMatrix * vertex).xyz;\n",
    # Vertex alpha below 1 carries how much a vertex moves; roots stay planted.
    "uniform float u_world_time;\n"
    "uniform vec4 u_blast_wave;\n"
    "uniform vec4 u_blast_power;\n"
    "void main() {\n"
    "    float wind = 1.0 - p3d_Color.a;\n"
    "    vec4 moved = vertex;\n"
    "    vec2 fromBlast = vertex.xz - u_blast_wave.xz;\n"
    "    float blastDistance = max(length(fromBlast), .01);\n"
    "    float front = exp(-pow((blastDistance - u_blast_wave.w) / (6.0 + u_blast_power.y * .08), 2.0));\n"
    "    moved.xz += fromBlast / blastDistance * front * u_blast_power.x * max(vertex.y - u_blast_wave.y, 0.0) * .09;\n"
    "    float gust = sin(u_world_time * 1.7 + vertex.x * .31 + vertex.z * .23)\n"
    "               + .5 * sin(u_world_time * 3.1 + vertex.x * .83 - vertex.z * .61);\n"
    "    moved.x += gust * wind * .34;\n"
    "    moved.z += gust * wind * .18;\n"
    "    gl_Position = p3d_ModelViewProjectionMatrix * moved;\n"
    "    vertex_position = vec3(p3d_ModelViewMatrix * moved);\n"
    "    vertex_world_position = (p3d_ModelMatrix * moved).xyz;\n",
    1)
if "u_world_time" not in _WIND_VERTEX:
    raise RuntimeError("Ursina's lit shader changed; update the vegetation wind")

VEGETATION_SHADER = Shader(name="sentry_vegetation", language=lit_with_shadows_shader.language,
                           vertex=_WIND_VERTEX, fragment=lit_with_shadows_shader.fragment,
                           default_input=dict(lit_with_shadows_shader.default_input),
                           continuous_input=dict(lit_with_shadows_shader.continuous_input))

SKY_SHADER = Shader(name="sentry_sky", language=lit_with_shadows_shader.language, vertex="""
#version 150
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 vertex;
out vec3 direction;
void main() {
    // z = w keeps the dome at the far plane, whatever the camera's clip distance.
    gl_Position = (p3d_ModelViewProjectionMatrix * vertex).xyww;
    direction = vertex.xyz;
}
""", fragment=f"""
#version 150
uniform float u_world_time;
uniform vec3 u_sun;
uniform sampler2D u_cloud_noise;
in vec3 direction;
out vec4 fragment_color;

void main() {{
    vec3 d = normalize(direction);
    float height = clamp(d.y, 0.0, 1.0);
    vec3 sky = mix({_vec3(HORIZON)}, {_vec3(SKY_MID)}, smoothstep(0.0, .24, height));
    sky = mix(sky, {_vec3(SKY_ZENITH)}, smoothstep(.18, .86, height));
    float toward_sun = max(dot(d, u_sun), 0.0);
    sky += vec3(1.0, .78, .52) * pow(toward_sun, 7.0) * .24;
    sky += vec3(1.0, .93, .78) * smoothstep(.9975, .9992, toward_sun);
    if (d.y > .008) {{
        // Flat cloud deck from a baked noise tile: two lookups, rotated so the tile never shows.
        vec2 p = d.xz / (d.y + .17) * .2 + vec2(u_world_time * .0011, u_world_time * .0004);
        float n = texture(u_cloud_noise, p).r * .72
                + texture(u_cloud_noise, vec2(p.x * .8 - p.y * .6, p.x * .6 + p.y * .8) * 2.3).r * .28;
        float cover = smoothstep(.50, .70, n) * smoothstep(.008, .15, d.y);
        vec3 cloud = mix(vec3(.70, .69, .79), vec3(1.0, .95, .87),
                         clamp(smoothstep(.50, .80, n) + toward_sun * .32, 0.0, 1.0));
        sky = mix(sky, cloud, cover * .9);
    }}
    fragment_color = vec4(sky, 1.0);
}}
""", default_input={"u_sun": (0.0, 1.0, 0.0)})

WATER_SHADER = Shader(name="sentry_water", language=lit_with_shadows_shader.language, vertex="""
#version 150
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelViewMatrix;
uniform mat4 p3d_ModelMatrix;
in vec4 vertex;
out vec3 world_position;
out float view_distance;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * vertex;
    world_position = (p3d_ModelMatrix * vertex).xyz;
    view_distance = length((p3d_ModelViewMatrix * vertex).xyz);
}
""", fragment=f"""
#version 150
uniform float u_world_time;
uniform float u_fog_density;
uniform vec3 u_sun;
uniform vec3 u_camera;
in vec3 world_position;
in float view_distance;
out vec4 fragment_color;

void main() {{
    vec2 p = world_position.xz;
    float t = u_world_time;
    // Summed sine slopes make a small, smooth normal with no texture lookup.
    float sx = .55 * cos(p.x * .061 + p.y * .021 + t * .73) + .28 * cos(p.x * .17 - p.y * .08 + t * 1.15);
    float sz = .55 * cos(p.y * .049 - p.x * .017 - t * .58) + .28 * cos(p.y * .15 + p.x * .11 + t * .97);
    float ripple = clamp(1.0 - view_distance * .00045, .12, 1.0);
    vec3 normal = normalize(vec3(-sx * .16 * ripple, 1.0, -sz * .16 * ripple));
    vec3 view = normalize(u_camera - world_position);

    // Same rounded-square footprint as IslandFrame.boundary_value, for the shallows.
    vec2 q = abs(p) / 5000.0;
    q = q * q;
    float footprint = dot(q, q);
    float shallow = 1.0 - smoothstep(1.0, 1.7, footprint);
    vec3 water = mix(vec3(.05, .27, .40), vec3(.17, .60, .60), shallow);
    water += (sx + sz) * .012;
    float foam = (1.0 - smoothstep(.985, 1.045 + .012 * sin(p.x * .05 + p.y * .04 + t * .6), footprint))
               * (.55 + .25 * sin(p.x * .31 + p.y * .23 + t));
    water = mix(water, vec3(.93, .96, .93), clamp(foam, 0.0, 1.0));

    float facing = max(dot(view, normal), 0.0);
    float fresnel = pow(1.0 - facing, 4.0);
    water = mix(water, {_vec3(SKY_MID)}, fresnel * .62);
    vec3 mirrored = reflect(-u_sun, normal);
    water += vec3(1.0, .90, .72) * pow(max(dot(mirrored, view), 0.0), 90.0) * .75 * ripple;

    float fog_amount = view_distance * u_fog_density;
    fragment_color = vec4(mix({_vec3(HORIZON)}, water, exp(-fog_amount * fog_amount)), 1.0);
}}
""", default_input={"u_sun": (0.0, 1.0, 0.0), "u_camera": (0.0, 0.0, 0.0)})


# Fades a sphere's rim instead of drawing a hard edge, so one low-cost sphere reads as a soft glow or puff of
# smoke. The normal comes from the position, so the sphere's facets never show, and rolling noise breaks the
# surface up like fire or smoke. It is unlit and needs no particles or textures.
SOFT_GLOW_SHADER = Shader(name="sentry_soft_glow", language=lit_with_shadows_shader.language, vertex="""
#version 150
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat3 p3d_NormalMatrix;
in vec4 vertex;
in vec3 normal;
out vec3 view_normal;
out vec3 local;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * vertex;
    view_normal = p3d_NormalMatrix * vertex.xyz;
    local = vertex.xyz;
}
""", fragment="""
#version 150
uniform vec4 p3d_ColorScale;
uniform float osg_FrameTime;
in vec3 view_normal;
in vec3 local;
out vec4 fragment_color;
float wave(vec3 p) {
    return sin(p.x) * sin(p.y * 1.3 + 1.7) * sin(p.z * .9 + 2.9);
}
void main() {
    float centre = abs(normalize(view_normal).z);
    vec3 p = local * 9.0 + vec3(0.0, osg_FrameTime * -1.7, osg_FrameTime * .6);
    float rolling = wave(p) * .5 + wave(p * 2.1 + 4.0) * .3 + wave(p * 4.3 + 9.0) * .2;
    float body = centre * centre * (1.0 + rolling * .55);
    vec3 hot = p3d_ColorScale.rgb + vec3(.32) * centre * centre * centre * centre * p3d_ColorScale.a;
    fragment_color = vec4(hot, clamp(p3d_ColorScale.a * body, 0.0, 1.0));
}
""")


def soft_glow(**options):
    """A transparent, depth-friendly sphere using the soft shader."""
    glow = Entity(model="sphere", shader=SOFT_GLOW_SHADER, transparency=True, collider=None,
                  add_to_scene_entities=False, **options)
    glow.setDepthWrite(False)
    return glow


_ring_geometry = None


def shockwave_ring_mesh() -> Mesh:
    """A flat ring, bright at its leading edge and fading inward, for one pooled burst."""
    global _ring_geometry
    if _ring_geometry is None:
        vertices, colors, triangles = [], [], []
        segments = 40
        bands = ((.30, 0.0), (.47, 1.0), (.50, 0.0))  # (radius, opacity); unit diameter
        for index in range(segments):
            angle = 2.0 * pi * index / segments
            for radius, opacity in bands:
                vertices.append((cos(angle) * radius, sin(angle) * radius, 0.0))
                colors.append(color.rgba(1.0, 1.0, 1.0, opacity))
        for index in range(segments):
            following = (index + 1) % segments
            for band in range(len(bands) - 1):
                a, b = index * len(bands) + band, following * len(bands) + band
                triangles.extend((a, b, b + 1, a, b + 1, a + 1))
        _ring_geometry = (vertices, colors, triangles)
    vertices, colors, triangles = _ring_geometry
    return Mesh(vertices=vertices, colors=colors, triangles=triangles, static=True)


def cloud_noise_texture(size: int = 256) -> Texture:
    """A soft noise tile that wraps on both axes, baked once at startup."""
    rng = Random(2026)
    octaves = []
    for cells, weight in ((5, .5), (10, .27), (20, .15), (40, .08)):
        grid = [[rng.random() for _ in range(cells)] for _ in range(cells)]
        octaves.append((cells, weight, grid))
    pixels = bytearray(size * size)
    for y in range(size):
        for x in range(size):
            total = 0.0
            for cells, weight, grid in octaves:
                fx, fy = x * cells / size, y * cells / size
                ix, iy = int(fx), int(fy)
                tx, ty = fx - ix, fy - iy
                tx, ty = tx * tx * (3.0 - 2.0 * tx), ty * ty * (3.0 - 2.0 * ty)
                right, down = (ix + 1) % cells, (iy + 1) % cells
                top = grid[iy][ix] + (grid[iy][right] - grid[iy][ix]) * tx
                bottom = grid[down][ix] + (grid[down][right] - grid[down][ix]) * tx
                total += (top + (bottom - top) * ty) * weight
            pixels[y * size + x] = min(255, int(total * 255.0))
    texture = Texture("sky-cloud-noise")
    texture.setup2dTexture(size, size, Texture.T_unsigned_byte, Texture.F_luminance)
    texture.setRamImage(bytes(pixels))
    texture.setWrapU(SamplerState.WM_repeat)
    texture.setWrapV(SamplerState.WM_repeat)
    texture.setMinfilter(SamplerState.FT_linear_mipmap_linear)
    texture.setMagfilter(SamplerState.FT_linear)
    return texture


def shade(tint, factor: float, wind: float = 0.0):
    """A tint lit by a baked factor, carrying how far the wind moves this vertex."""
    return color.rgba(min(1.0, tint.r * factor), min(1.0, tint.g * factor),
                      min(1.0, tint.b * factor), 1.0 - wind)
