"""Procedural shader for the island atmospheric sky dome."""

from ursina import Shader


SKY_SHADER = Shader(
    name="sentry_island_atmosphere_sky",
    language=Shader.GLSL,
    vertex="""
#version 430
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
in vec4 p3d_Vertex;
out vec3 v_direction;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    v_direction = normalize(mat3(p3d_ModelMatrix) * p3d_Vertex.xyz);
}
""",
    fragment="""
#version 430
in vec3 v_direction;
out vec4 fragColor;
uniform vec3 u_planet_up;
uniform vec3 u_sun_direction;
uniform float u_atmosphere_density;
uniform float u_time;
uniform float u_quality;

void main() {
    vec3 ray = normalize(v_direction);
    vec3 up = normalize(u_planet_up);
    vec3 sun = normalize(u_sun_direction);
    float zenith = clamp(dot(ray, up), -1.0, 1.0);
    float sun_elevation = dot(up, sun);
    float horizon = pow(clamp(1.0 - abs(zenith), 0.0, 1.0), 2.0);
    float sun_scatter = pow(max(dot(ray, sun), 0.0), 18.0);

    // Low-cost Rayleigh blue with a broad, warm Mie band near sunrise/sunset.
    vec3 zenith_blue = vec3(0.035, 0.17, 0.52);
    vec3 horizon_blue = vec3(0.30, 0.56, 0.84);
    vec3 twilight = vec3(0.95, 0.32, 0.14);
    vec3 atmosphere = mix(zenith_blue, horizon_blue, horizon * 0.88);
    float dusk = 1.0 - smoothstep(-0.12, 0.24, sun_elevation);
    atmosphere = mix(atmosphere, twilight, dusk * horizon * 0.68);
    atmosphere += vec3(0.52, 0.36, 0.18) * sun_scatter * (0.12 + dusk * 0.32);
    float density = clamp(u_atmosphere_density, 0.0, 1.0);

    // Lightweight soft cloud banks for atmospheric views.
    float local_clouds = 0.0;
    if (u_quality <= 0.25) {
        float coarse_cloud = sin(dot(ray, vec3(5.1, 3.2, 7.4)) + u_time * 0.003)
                           * sin(dot(ray, vec3(-2.7, 8.0, 1.9)) - u_time * 0.002);
        local_clouds = smoothstep(0.52, 0.88, coarse_cloud)
                     * (1.0 - smoothstep(0.35, 0.82, abs(zenith)));
    } else {
        float cloud_field = sin(ray.x * 8.0 + sin(ray.z * 4.5 + u_time * 0.006)) * 0.46
                          + sin(ray.z * 7.0 - ray.y * 3.0 - u_time * 0.004) * 0.31
                          + sin(ray.y * 10.0 + ray.x * 5.0 + u_time * 0.003) * 0.23
                          + sin((ray.x + ray.z) * 21.0 + u_time * 0.008) * 0.07;
        local_clouds = smoothstep(0.28, 0.56, cloud_field)
                     * (1.0 - smoothstep(0.35, 0.82, abs(zenith)))
                     * smoothstep(0.12, 0.9, density);
    }
    atmosphere = mix(atmosphere, vec3(0.77, 0.84, 0.93), local_clouds * 0.36);

    float path = mix(0.68, 1.4, horizon);
    // Attenuate the sky color smoothly with the island atmosphere density.
    float scatter = pow(max(density, 0.000001), 0.32);
    fragColor = vec4(atmosphere * scatter, 1.0);
}
""",
)
