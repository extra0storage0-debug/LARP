"""Physically based shading for the characters, cheap enough for an integrated GPU.

One sun with its shadow map, GGX highlights, a procedural sky standing in for image-based light, wrapped and
red-shifted diffuse on skin, and normal maps through a screen-space frame, so no tangents need to be stored.
It ends with the same grading and fog as the rest of the world, so characters sit in the same picture.
"""

from __future__ import annotations

from ursina import Shader
from game.art_style import HORIZON, SKY_MID, SKY_ZENITH


def _v(values) -> str:
    return f"vec3({values[0]}, {values[1]}, {values[2]})"


_LIGHT = """
uniform struct {
    vec4 position;
    vec3 color;
    vec3 attenuation;
    vec3 spotDirection;
    float spotCosCutoff;
    float spotExponent;
    sampler2DShadow shadowMap;
    mat4 shadowViewMatrix;
} p3d_LightSource[1];
"""

_SKINNED_VERTEX = "#version 150\n" + _LIGHT + """
uniform mat4 p3d_ProjectionMatrix;
uniform mat4 p3d_ModelViewMatrix;
uniform mat3 p3d_NormalMatrix;
uniform mat4 p3d_TransformTable[64];
in vec4 p3d_Vertex;
in vec3 p3d_Normal;
in vec2 p3d_MultiTexCoord0;
in vec4 p3d_Color;
in vec4 transform_weight;
in vec4 transform_index;
out vec3 v_view;
out vec3 v_normal;
out vec2 v_uv;
out vec4 v_color;
out vec4 v_shadow;
void main() {
    mat4 skin = p3d_TransformTable[int(transform_index.x)] * transform_weight.x
              + p3d_TransformTable[int(transform_index.y)] * transform_weight.y
              + p3d_TransformTable[int(transform_index.z)] * transform_weight.z
              + p3d_TransformTable[int(transform_index.w)] * transform_weight.w;
    vec4 view = p3d_ModelViewMatrix * (skin * p3d_Vertex);
    gl_Position = p3d_ProjectionMatrix * view;
    v_view = view.xyz;
    v_normal = p3d_NormalMatrix * mat3(skin) * p3d_Normal;
    v_uv = p3d_MultiTexCoord0;
    v_color = p3d_Color;
    v_shadow = p3d_LightSource[0].shadowViewMatrix * vec4(view.xyz, 1.0);
}
"""

_SHADE = _LIGHT + f"""
uniform mat4 p3d_ViewMatrixInverse;
uniform float u_fog_density;
uniform float u_character_light_floor;
uniform float shadow_bias;
uniform float shadow_blur;
in vec3 v_view;
in vec3 v_normal;
in vec2 v_uv;
in vec4 v_color;
in vec4 v_shadow;
out vec4 fragment_color;

float sun_shadow() {{
    vec4 coord = v_shadow;
    coord.z += shadow_bias;
    float sum = 0.0;
    for (int x = 0; x < 2; ++x) {{
        for (int y = 0; y < 2; ++y) {{
            vec4 c = coord;
            c.x += (float(x) - .5) * shadow_blur;
            c.y += (float(y) - .5) * shadow_blur;
            sum += textureProj(p3d_LightSource[0].shadowMap, c);
        }}
    }}
    return sum * .25;
}}

vec3 sky_light(vec3 world_dir, float blur) {{
    float up = world_dir.y;
    vec3 sky = mix({_v(HORIZON)}, mix({_v(SKY_MID)}, {_v(SKY_ZENITH)}, clamp(up * 1.2, 0.0, 1.0)), smoothstep(-.02, .35, up));
    vec3 ground = vec3(.20, .23, .13);
    return mix(ground, sky, smoothstep(-.28 - blur * .4, .05 + blur * .3, up));
}}

vec3 shade(vec3 albedo, float rough, float metal, float skin, float ao, vec3 n) {{
    vec3 v = normalize(-v_view);
    vec3 l = normalize(p3d_LightSource[0].position.xyz - v_view * p3d_LightSource[0].position.w);
    vec3 h = normalize(l + v);
    float raw_nl = dot(n, l);
    float nv = max(dot(n, v), .02);
    float nh = max(dot(n, h), 0.0);
    float vh = max(dot(v, h), 0.0);
    vec3 sun = p3d_LightSource[0].color.rgb;
    float shadow = sun_shadow();

    // Light passes a little way through skin: its terminator is soft, and warmer than the lit side.
    float wrap = mix(0.0, .34, skin);
    float nl = clamp((raw_nl + wrap) / (1.0 + wrap), 0.0, 1.0);
    vec3 scatter = mix(vec3(1.0), vec3(1.0, .72 + .28 * nl, .58 + .42 * nl), skin);

    float a = max(rough * rough, .02);
    float d = nh * nh * (a * a - 1.0) + 1.0;
    float ggx = a * a / (3.14159 * d * d);
    float k = (rough + 1.0) * (rough + 1.0) * .125;
    float vis = 1.0 / max((max(raw_nl, 0.0) * (1.0 - k) + k) * (nv * (1.0 - k) + k), .05) * .25;
    vec3 f0 = mix(vec3(mix(.04, .028, skin)), albedo, metal);
    vec3 fresnel = f0 + (1.0 - f0) * pow(1.0 - vh, 5.0);
    vec3 direct = (albedo * (1.0 - metal) * nl * scatter + fresnel * ggx * vis * max(raw_nl, 0.0)) * sun * shadow * 1.05;

    mat3 to_world = mat3(p3d_ViewMatrixInverse);
    vec3 world_n = to_world * n;
    vec3 world_r = to_world * reflect(-v, n);
    vec3 ambient = sky_light(world_n, 1.0);
    ambient = mix(ambient, vec3(dot(ambient, vec3(.33))), .55) * mix(.34, .78, clamp(dot(sun, vec3(.33)), 0.0, 1.0));
    ambient = max(ambient, vec3(u_character_light_floor * .55));
    vec3 grazing = f0 + (max(vec3(1.0 - rough), f0) - f0) * pow(1.0 - nv, 5.0);
    // Rough cloth scatters what would be a mirror image of the sky: without this, dark colours wash out to grey.
    vec3 reflection = sky_light(world_r, rough) * mix(.34, .95, clamp(dot(sun, vec3(.33)), 0.0, 1.0)) * grazing * (1.0 - rough * .85);
    vec3 color = direct + (albedo * (1.0 - metal) * ambient + reflection) * ao;

    float luminance = dot(color, vec3(.3, .59, .11));
    color = mix(color * vec3(.92, .97, 1.08), color * vec3(1.05, 1.01, .95), smoothstep(.12, .78, luminance));
    float fog = length(v_view) * u_fog_density;
    return mix({_v(HORIZON)}, color, exp(-fog * fog));
}}
"""

_BODY_FRAGMENT = "#version 150\n" + _SHADE + """
uniform sampler2D u_albedo;
uniform sampler2D u_material;
uniform sampler2D u_normal;
uniform vec4 p3d_ColorScale;

vec3 detail_normal(vec3 n, vec2 uv, vec3 map) {
    vec3 dp1 = dFdx(v_view), dp2 = dFdy(v_view);
    vec2 duv1 = dFdx(uv), duv2 = dFdy(uv);
    vec3 dp2perp = cross(dp2, n), dp1perp = cross(n, dp1);
    vec3 t = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 b = dp2perp * duv1.y + dp1perp * duv2.y;
    float scale = inversesqrt(max(max(dot(t, t), dot(b, b)), 1e-12));
    return normalize(t * scale * map.x + b * scale * map.y + n * map.z);
}

void main() {
    vec3 sampled = texture(u_normal, v_uv).rgb;
    vec3 map = vec3(sampled.xy * 2.0 - 1.0, 0.0);
    map.z = sqrt(max(1.0 - dot(map.xy, map.xy), .01));
    vec3 n = detail_normal(normalize(v_normal), v_uv, map);
    vec3 m = texture(u_material, v_uv).rgb;
    vec3 albedo = pow(texture(u_albedo, v_uv).rgb, vec3(2.2)) * p3d_ColorScale.rgb;
    vec3 color = shade(albedo, m.r, m.g, m.b, sampled.b, n);
    fragment_color = vec4(pow(max(color, vec3(0.0)), vec3(1.0 / 2.2)), p3d_ColorScale.a);
}
"""

_HAIR_FRAGMENT = "#version 150\n" + _SHADE + """
uniform sampler2D u_albedo;
uniform vec4 p3d_ColorScale;
void main() {
    vec4 sheet = texture(u_albedo, v_uv);
    if (sheet.a < .42) discard;
    vec3 tint = pow(v_color.rgb, vec3(2.2));
    vec3 albedo = tint * (.35 + 1.1 * sheet.r) * p3d_ColorScale.rgb;
    vec3 n = normalize(v_normal);  // the scalp's normal, either side of the card, so a head of hair shades as one form
    vec3 color = shade(albedo, .62, 0.0, .15, .92, n);
    fragment_color = vec4(pow(max(color, vec3(0.0)), vec3(1.0 / 2.2)), p3d_ColorScale.a);
}
"""

_GEAR_FRAGMENT = "#version 150\n" + _SHADE + """
uniform vec4 p3d_ColorScale;
void main() {
    // Each piece's colour is in its vertices, and its alpha says how much of it is metal.
    vec3 albedo = pow(v_color.rgb, vec3(2.2)) * p3d_ColorScale.rgb;
    float metal = v_color.a;
    vec3 color = shade(albedo, mix(.66, .27, metal), metal, 0.0, .96, normalize(v_normal));
    fragment_color = vec4(pow(max(color, vec3(0.0)), vec3(1.0 / 2.2)), p3d_ColorScale.a);
}
"""

_CAPE_VERTEX = "#version 150\n" + _LIGHT + """
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelViewMatrix;
uniform mat3 p3d_NormalMatrix;
uniform float osg_FrameTime;
uniform vec3 u_chain[6];     // the cape's centre line, from the neck down
uniform vec4 u_cape_shape;   // half width at the shoulders, half width at the hem, wind 0 to 1, slack 0 to 1
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
in vec4 p3d_Color;
out vec3 v_view;
out vec3 v_normal;
out vec2 v_uv;
out vec4 v_color;
out vec4 v_shadow;

vec3 along(float t) {
    float f = clamp(t, 0.0, 1.0) * 5.0;
    int i = min(int(f), 4);
    float s = f - float(i);
    vec3 a = u_chain[max(i - 1, 0)], b = u_chain[i], c = u_chain[i + 1], d = u_chain[min(i + 2, 5)];
    return .5 * (2.0 * b + (c - a) * s + (2.0 * a - 5.0 * b + 4.0 * c - d) * s * s + (3.0 * b - a - 3.0 * c + d) * s * s * s);
}

vec3 place(float u, float t) {
    vec3 middle = along(t);
    float across = u * 2.0 - 1.0;
    float spread = smoothstep(0.0, .3, t);
    float half_width = mix(u_cape_shape.x, u_cape_shape.y, spread);
    float wind = u_cape_shape.z;
    float slack = u_cape_shape.w;
    // Hanging cloth gathers into soft pleats; streaming cloth pulls flat and ripples.
    float pleat = cos(u * 15.7 + sin(t * 3.0) * .8) * (.018 + .05 * t) * slack * spread;
    float time = osg_FrameTime;
    float ripple = sin(t * 11.0 - time * (3.0 + wind * 11.0) + u * 5.0) * (.008 + wind * .055) * t;
    float flutter = sin(t * 23.0 - time * (6.0 + wind * 17.0) + u * 13.0) * wind * .018 * t * abs(across);
    vec3 here = middle + vec3(across * half_width * (1.0 - .10 * slack * t), 0.0, 0.0);
    here.z += pleat - ripple - flutter;
    here.y += ripple * .35;
    // At the top it wraps forward over the shoulders and follows their slope, so it is worn, not stuck on.
    float top = 1.0 - smoothstep(0.0, .14, t);
    here.z += across * across * top * .03;
    here.y -= across * across * top * .035;
    return here;
}

void main() {
    float u = p3d_MultiTexCoord0.x, t = p3d_MultiTexCoord0.y;
    vec3 here = place(u, t);
    vec3 across = place(u + .02, t) - here;
    vec3 down = place(u, t + .02) - here;
    vec4 view = p3d_ModelViewMatrix * vec4(here, 1.0);
    gl_Position = p3d_ModelViewProjectionMatrix * vec4(here, 1.0);
    v_view = view.xyz;
    v_normal = p3d_NormalMatrix * normalize(cross(down, across));
    v_uv = p3d_MultiTexCoord0;
    v_color = p3d_Color;
    v_shadow = p3d_LightSource[0].shadowViewMatrix * vec4(view.xyz, 1.0);
}
"""

_CAPE_FRAGMENT = "#version 150\n" + _SHADE + """
uniform sampler2D u_albedo;
uniform vec4 p3d_ColorScale;
void main() {
    vec3 albedo = pow(texture(u_albedo, vec2(v_uv.x, 1.0 - v_uv.y)).rgb, vec3(2.2)) * p3d_ColorScale.rgb;
    vec3 n = normalize(v_normal);
    if (!gl_FrontFacing) {  // the lining: the same cloth, duller and in its own shade
        n = -n;
        albedo *= .62;
    }
    // Thick cloth: its edges catch less light, and a hem shows.
    float edge = min(min(v_uv.x, 1.0 - v_uv.x), 1.0 - v_uv.y);
    albedo *= .78 + .22 * smoothstep(.0, .022, edge);
    vec3 color = shade(albedo, .88, 0.0, .2, 1.0, n);
    fragment_color = vec4(pow(max(color, vec3(0.0)), vec3(1.0 / 2.2)), p3d_ColorScale.a);
}
"""

_DEFAULTS = {"u_character_light_floor": .42, "shadow_bias": .001, "shadow_blur": .002}

SKIN_SHADER = Shader(name="character_skin_pbr", language=Shader.GLSL, vertex=_SKINNED_VERTEX, fragment=_BODY_FRAGMENT,
                     default_input=dict(_DEFAULTS))
HAIR_SHADER = Shader(name="character_hair", language=Shader.GLSL, vertex=_SKINNED_VERTEX, fragment=_HAIR_FRAGMENT,
                     default_input=dict(_DEFAULTS))
GEAR_SHADER = Shader(name="character_gear", language=Shader.GLSL, vertex=_SKINNED_VERTEX, fragment=_GEAR_FRAGMENT,
                     default_input=dict(_DEFAULTS))
CAPE_PBR_SHADER = Shader(name="character_cape_pbr", language=Shader.GLSL, vertex=_CAPE_VERTEX, fragment=_CAPE_FRAGMENT,
                         default_input=dict(_DEFAULTS))
