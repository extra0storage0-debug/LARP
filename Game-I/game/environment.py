"""Island sunlight, an atmospheric sky, and a continuous day/night cycle."""

from __future__ import annotations

from math import cos, pi, radians, sin, sqrt
from random import Random

from ursina import (DirectionalLight, Entity, Mesh, Vec2, Vec3, camera, color, scene,
                    window)
from ursina.entity import Entity as UrsinaEntity

from characters.sentry_shader import character_light_floor
from game.environment_shaders import SKY_SHADER
from movement.flight_physics import Vec3 as SimVec3


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    value = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return value * value * (3.0 - 2.0 * value)


def _rotate_about_axis(vector: Vec3, axis: Vec3, angle: float) -> Vec3:
    """Rotate a world direction around its fixed day/night axis."""
    axis = axis.normalized()
    value = (vector * cos(angle) + axis.cross(vector) * sin(angle)
             + axis * (axis.dot(vector) * (1.0 - cos(angle))))
    return value.normalized()


def _sun_rgb(up: Vec3, sun: Vec3, density: float) -> tuple[int, int, int]:
    """Return the Sun's atmospheric spectrum without scaling its energy.

    The atmosphere warms direct sunlight near a surface horizon. That tint fades
    away with atmospheric density, while the distant Sun itself stays bright.
    """
    elevation = up.x * sun.x + up.y * sun.y + up.z * sun.z
    atmospheric_weight = _smoothstep(.01, .45, density)
    warm = (1.0 - _smoothstep(.03, .42, elevation)) * atmospheric_weight
    return (255, round(255 - 71 * warm), round(255 - 150 * warm))


class SunCycle:
    """One Sun and a configurable day/night cycle over the island."""

    SUN_BASE = Vec3(1.0, 0.0, 0.08).normalized()

    def __init__(self, game):
        self.game = game
        self.elapsed = 0.0
        self.day_seconds = float(getattr(game.settings, "day_length_seconds", 720.0))
        self._light_update_timer = 1.0
        self._night_windows_timer = 1.0
        self._daylight = 1.0
        self._quality = str(game.settings.quality).lower()
        self._sun_direction = Vec3(0.0, 1.0, 0.08).normalized()
        self._world_polar_axis = Vec3(0.0, 0.0, 1.0)
        self._shadow_resolution = self._resolution_for_quality(game.settings.quality)
        self._shadows_enabled = self._shadows_for_quality(game.settings.quality)

        # Keep the shadow frustum local to the sentry instead of fitting it around
        # the entire globe. The orthographic lens is configured directly so no
        # visible proxy geometry is needed.
        self.light = DirectionalLight(shadow_map_resolution=self._shadow_resolution,
                                      shadows=self._shadows_enabled, color=color.white)
        self._set_shadow_lens()
        self._aim_light(Vec3(0, 0, 0), Vec3(0, 1, 0))

        self.sky = Entity(parent=scene, model="sphere", scale=700,
                          color=color.white, shader=SKY_SHADER, unlit=True,
                          double_sided=True, collider=None, name="atmospheric-sky-dome")
        self.sky.setDepthWrite(False)
        self.sky.set_shader_input("u_planet_up", Vec3(0, 1, 0))
        self.sky.set_shader_input("u_sun_direction", self._sun_direction)
        self.sky.set_shader_input("u_atmosphere_density", 1.0)
        self.sky.set_shader_input("u_time", 0.0)
        self.sky.set_shader_input("u_quality", self._sky_quality_value())

        self.stars = Entity(parent=scene, model=self._make_star_mesh(240),
                            scale=1, color=color.rgba32(220, 233, 255, 0),
                            unlit=True, transparency=True, double_sided=True,
                            collider=None, name="night-sky-stars")
        self.sun_disc = Entity(parent=scene, model="sphere", scale=3.2,
                               color=color.rgb32(255, 247, 224), unlit=True,
                               collider=None, name="visible-sun-disc")
        self.sun_glow = Entity(parent=scene, model="sphere", scale=6.4,
                               color=color.rgba32(255, 183, 91, 30), unlit=True,
                               transparency=True, collider=None, name="sun-corona")

        self._set_island_inputs(force=True)
        self.update(0.0)

    @staticmethod
    def _resolution_for_quality(quality: str) -> tuple[int, int]:
        return {"low": (256, 256), "medium": (512, 512),
                "high": (1024, 1024), "ultra": (2048, 2048)}.get(str(quality).lower(), (256, 256))

    @staticmethod
    def _shadows_for_quality(quality: str) -> bool:
        # Dynamic shadows are the largest avoidable render cost on Low and the
        # laptop-class baseline. Keep them for the two higher quality presets.
        return str(quality).lower() != "low"

    @staticmethod
    def _make_star_mesh(count: int) -> Mesh:
        rng = Random(4107)
        vertices, triangles, colors = [], [], []
        for _ in range(count):
            y = rng.uniform(-.97, .97)
            angle = rng.uniform(0.0, 2.0 * pi)
            ring = sqrt(1.0 - y * y)
            direction = Vec3(ring * cos(angle), y, ring * sin(angle))
            center = direction
            tangent = Vec3(-direction.z, 0.0, direction.x)
            if tangent.length() < .01:
                tangent = Vec3(1, 0, 0)
            tangent = tangent.normalized() * rng.uniform(.0014, .0023)
            vertical = direction.cross(tangent).normalized() * rng.uniform(.0014, .0023)
            first = len(vertices)
            vertices.extend((center - tangent - vertical, center + tangent - vertical,
                             center + tangent + vertical, center - tangent + vertical))
            tint = color.rgba32(213, 229, 255, rng.randrange(175, 256))
            colors.extend((tint,) * 4)
            triangles.extend((first, first + 1, first + 2, first, first + 2, first + 3))
        return Mesh(vertices=vertices, triangles=triangles, colors=colors, static=True)

    def _set_island_inputs(self, *, force: bool = False) -> None:
        camera_position = camera.world_position
        world_pos = SimVec3(camera_position.x, camera_position.y, camera_position.z)
        altitude = max(0.0, self.game.planet.altitude(world_pos))
        density = self.game.planet.atmosphere_density(altitude)
        up = self.game.planet.normal(world_pos)
        phase = 2.0 * pi * self.elapsed / max(1.0, self.day_seconds) - pi * .5
        sun = _rotate_about_axis(self.SUN_BASE, self._world_polar_axis, phase)
        daylight = _smoothstep(-.14, .17, up.x * sun.x + up.y * sun.y + up.z * sun.z)
        self._daylight = daylight
        self._sun_direction = sun
        self.game.sentry.set_character_light_floor(character_light_floor(density))

        self.sky.position = camera_position
        render_distance = float(self.game.settings.render_distance)
        far_plane = max(render_distance,
                        min(altitude * 2.5 + render_distance,
                            altitude + self.game.planet.radius * 3.5))
        # Ursina's built-in sphere has a half-unit radius.
        self.sky.scale = far_plane * 1.94
        self.stars.scale = far_plane * .985
        self.sky.set_shader_input("u_planet_up", Vec3(up.x, up.y, up.z))
        self.sky.set_shader_input("u_sun_direction", sun)
        self.sky.set_shader_input("u_atmosphere_density", density)
        self.sky.set_shader_input("u_time", self.elapsed)
        self.stars.position = camera_position

        self.sun_disc.position = camera_position + sun * (far_plane * .94)
        self.sun_glow.position = self.sun_disc.position
        self.sun_disc.scale = max(1.0, far_plane * .94 * .0093)
        self.sun_glow.scale = self.sun_disc.scale * 2.0
        sun_rgb = _sun_rgb(up, sun, density)
        self.sun_disc.color = color.rgb32(*sun_rgb)
        self.sun_glow.color = color.rgba32(255, 171, 82,
                                           round(12 + daylight * 36))
        night = 1.0 - daylight
        star_alpha = night * .16
        self.stars.color = color.rgba32(220, 233, 255, round(238 * star_alpha))
        if force or self._night_windows_timer >= .25:
            self._night_windows_timer = 0.0
            window_alpha = round(178 * (1.0 - daylight) ** 1.35)
            for building in self.game.world.buildings:
                building.night_windows.color = color.rgba32(255, 184, 91, window_alpha)

        if force:
            self._update_sunlight(sun, daylight, up, density, force=True)

    def _update_sunlight(self, direction: Vec3, daylight: float,
                         up: Vec3, density: float,
                         *, force: bool = False) -> None:
        if not force and self._light_update_timer < .25:
            return
        self._light_update_timer = 0.0
        sun_rgb = _sun_rgb(up, direction, density)
        strength = .012 + .988 * daylight
        self.light.color = color.rgb32(*(round(channel * strength)
                                         for channel in sun_rgb))
        sentry_position = self.game.sentry.position
        self._aim_light(sentry_position, direction)

    def _set_shadow_lens(self) -> None:
        lens = self.light._light.get_lens()
        lens.set_film_size((620.0, 620.0))
        lens.set_film_offset((0.0, 0.0))
        lens.set_near_far(1.0, 1450.0)

    def _aim_light(self, target, direction: Vec3) -> None:
        target = Vec3(*target)
        self.light.position = target + direction * 720.0
        UrsinaEntity.look_at(self.light, target)
        self._set_shadow_lens()

    def set_quality(self, quality: str) -> None:
        self._quality = str(quality).lower()
        self.sky.set_shader_input("u_quality", self._sky_quality_value())
        resolution = self._resolution_for_quality(quality)
        shadows_enabled = self._shadows_for_quality(quality)
        if (resolution == self._shadow_resolution
                and shadows_enabled == self._shadows_enabled):
            return
        self._shadow_resolution = resolution
        self._shadows_enabled = shadows_enabled
        self.light.shadows = False
        self.light.shadow_map_resolution = Vec2(*resolution)
        self.light.shadows = shadows_enabled
        self._set_shadow_lens()
        self.stars.model = self._make_star_mesh({"low": 240, "medium": 360,
                                                "high": 520, "ultra": 720}.get(quality, 240))

    def _sky_quality_value(self) -> float:
        return {"low": 0.0, "medium": 0.5, "high": 1.0, "ultra": 1.0}.get(self._quality, 0.0)

    def update(self, dt: float) -> None:
        self.elapsed += max(0.0, min(float(dt), .05))
        self._light_update_timer += max(0.0, min(float(dt), .05))
        self._night_windows_timer += max(0.0, min(float(dt), .05))
        window.color = color.rgb32(0, 0, 0)
        self._set_island_inputs()
        camera_position = SimVec3(camera.world_x, camera.world_y, camera.world_z)
        self._update_sunlight(self._sun_direction, self._daylight,
                              self.game.planet.normal(camera_position),
                              self.game.planet.atmosphere_density(
                                  self.game.planet.altitude(camera_position)))

    def air_density(self, altitude: float) -> float:
        return self.game.planet.atmosphere_density(altitude)

    def reentry_heat(self, altitude: float, speed_mps: float, vertical_speed: float) -> float:
        density = self.air_density(altitude)
        descending = _smoothstep(4.0, 120.0, -vertical_speed)
        speed = max(0.0, min(1.0, speed_mps / 520.0))
        return max(0.0, min(1.0, density * speed * speed * (0.24 + .76 * descending)))
