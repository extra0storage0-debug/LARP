"""The island's fixed late-afternoon light, sky and atmosphere."""

from __future__ import annotations

from math import exp, sqrt

from panda3d.core import LVecBase3f, PTAFloat, PTALVecBase3f
from ursina import DirectionalLight, Entity, Vec2, Vec3, camera, color, scene, window
from ursina.entity import Entity as UrsinaEntity

from characters.sentry_shader import GROUND_LIGHT_FLOOR
from game.art_style import (FOG_DEFAULT, FOG_DENSITY, HORIZON, SKY_SHADER, SUN_COLOR,
                            SUN_DIRECTION, cloud_noise_texture)

# Large enough that a frame-old camera position can't show the dome's facets.
SKY_DOME_SCALE = 4000.0


class SandboxLighting:
    """One directional light, one sky dome and the uniforms the art style shares."""

    def __init__(self, game):
        self.game = game
        self._quality = str(game.settings.quality).lower()
        self._set_atmosphere(game.settings.quality)
        self._shadow_resolution = self._resolution_for_quality(self._quality)
        self._shadows_enabled = self._shadows_for_quality(self._quality)
        self.light = DirectionalLight(shadows=self._shadows_enabled,
                                      shadow_map_resolution=self._shadow_resolution,
                                      color=color.rgb32(*SUN_COLOR))
        self.light.position = Vec3(-35.0, 65.0, -45.0)
        UrsinaEntity.look_at(self.light, Vec3(0.0, 0.0, 0.0))
        game.sentry.set_character_light_floor(GROUND_LIGHT_FLOOR)
        length = sqrt(sum(value * value for value in SUN_DIRECTION))
        self._sun = tuple(value / length for value in SUN_DIRECTION)
        self._time = 0.0
        # Shared arrays: writing one needs no scene-wide render state change, which
        # calling set_shader_input on the scene root every frame would force.
        self._world_time = PTAFloat.emptyArray(1)
        self._camera = PTALVecBase3f.emptyArray(1)
        scene.setShaderInput("u_sun", self._sun)
        scene.setShaderInput("u_world_time", self._world_time)
        scene.setShaderInput("u_camera", self._camera)
        self.sky = Entity(name="island-sky", model="sphere", scale=SKY_DOME_SCALE,
                          shader=SKY_SHADER, double_sided=True, collider=None,
                          add_to_scene_entities=False)
        self.sky.setShaderInput("u_sun", self._sun)
        self.sky.setShaderInput("u_cloud_noise", cloud_noise_texture())
        self.sky.setBin("background", 0)
        self.sky.setDepthWrite(False)
        self.sky.setDepthTest(False)

    def _set_atmosphere(self, quality: str) -> None:
        # The clear colour, fog and sky all meet at one horizon colour.
        window.color = color.rgba(*HORIZON, 1.0)
        scene.set_shader_input("u_fog_density",
                               FOG_DENSITY.get(str(quality).lower(), FOG_DEFAULT))
        # HUD entities built while the lit shader is the default sit outside the scene.
        camera.ui.set_shader_input("u_fog_density", 0.0)

    @staticmethod
    def _resolution_for_quality(quality: str) -> tuple[int, int]:
        return {"low": (256, 256), "medium": (512, 512),
                "high": (1024, 1024)}.get(str(quality).lower(), (256, 256))

    @staticmethod
    def _shadows_for_quality(quality: str) -> bool:
        return str(quality).lower() != "low"

    def update(self, world_dt: float) -> None:
        """Wind, waves and clouds run on world time, so a time stop freezes them too."""
        self._time += world_dt
        self._world_time[0] = self._time
        position = camera.world_position
        self._camera[0] = LVecBase3f(position.x, position.y, position.z)
        self.sky.position = position

    def set_quality(self, quality: str) -> None:
        self._quality = str(quality).lower()
        self._set_atmosphere(quality)
        resolution = self._resolution_for_quality(quality)
        shadows_enabled = self._shadows_for_quality(quality)
        if (resolution, shadows_enabled) == (self._shadow_resolution,
                                             self._shadows_enabled):
            return
        self._shadow_resolution = resolution
        self._shadows_enabled = shadows_enabled
        self.light.shadows = False
        self.light.shadow_map_resolution = Vec2(*resolution)
        self.light.shadows = shadows_enabled

    @staticmethod
    def air_density(altitude: float) -> float:
        return exp(-max(-1000.0, float(altitude)) / 8500.0)

    def reentry_heat(self, altitude: float, speed_mps: float,
                     vertical_speed: float) -> float:
        density = self.air_density(altitude)
        descending = _smoothstep(4.0, 120.0, -vertical_speed)
        speed = max(0.0, min(1.0, speed_mps / 520.0))
        return max(0.0, min(1.0,
                            density * speed * speed * (0.24 + 0.76 * descending)))


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    value = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return value * value * (3.0 - 2.0 * value)
