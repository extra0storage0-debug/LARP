"""Player-only flight trail and motion blur, which cost nothing while set to zero."""

from __future__ import annotations

from ursina import Entity, Shader, Vec3, application, camera, color
from ursina.shaders import unlit_shader

_MOTION_BLUR = Shader(name="sentry_motion_blur", fragment="""
#version 430
uniform sampler2D tex;
uniform float blur_amount;
in vec2 uv;
out vec4 out_color;

void main() {
    vec2 toward_center = (vec2(.5, .5) - uv) * blur_amount;
    vec4 total = texture(tex, uv);
    for (int step_index = 1; step_index < 6; step_index++) {
        total += texture(tex, uv + toward_center * (float(step_index) / 5.0));
    }
    out_color = total / 6.0;
}
""", default_input={"blur_amount": 0.0})

BLUR_FULL_SPEED = 400.0
TRAIL_START_SPEED = 40.0


class PlayerVisualEffects:
    def __init__(self, game) -> None:
        self.game = game
        self.trail = None
        self.blur_active = False

    def _has_window(self) -> bool:
        return getattr(application.base, "win", None) is not None

    def apply(self) -> None:
        """Install or remove the blur filter so a zero setting leaves rendering untouched."""
        wanted = self.game.tuning.fraction("motion_blur_pct") > 0.0 and self._has_window()
        if wanted and not self.blur_active:
            camera.shader = _MOTION_BLUR
            self.blur_active = True
        elif not wanted and self.blur_active:
            camera.filter_manager.cleanup()
            camera.filter_manager = None
            camera.filter_quad.removeNode()
            camera.filter_quad = None
            camera._shader = None
            self.blur_active = False

    def update(self, _dt: float) -> None:
        sentry = self.game.sentry
        speed = sentry.flight.speed_mps if sentry.flight.is_flying else getattr(sentry.motion, "blur_speed", 0.0)
        if self.blur_active:
            amount = self.game.tuning.fraction("motion_blur_pct") * .08
            camera.set_shader_input("blur_amount", amount * min(1.0, speed / BLUR_FULL_SPEED))
        self._update_trail(sentry, speed)

    def _update_trail(self, sentry, speed: float) -> None:
        intensity = self.game.tuning.fraction("flight_trail_pct")
        if intensity <= 0.0 or speed < TRAIL_START_SPEED:
            if self.trail is not None:
                self.trail.enabled = False
            return
        if self.trail is None:
            self.trail = Entity(model="cube", shader=unlit_shader, transparency=True, collider=None,
                                name="player-flight-trail", add_to_scene_entities=False)
        velocity = sentry.flight.velocity
        direction = Vec3(velocity.x, velocity.y, velocity.z).normalized()
        length = min(60.0, speed * .12) * max(.2, min(2.0, intensity))
        center = Vec3(sentry.x, sentry.y + 1.4, sentry.z) - direction * (length * .5 + 1.0)
        self.trail.enabled = True
        self.trail.position = center
        self.trail.look_at(center + direction)
        self.trail.scale = (.35, .35, length)
        self.trail.color = color.rgba32(255, 228, 150, min(200, round(90 * intensity)))
