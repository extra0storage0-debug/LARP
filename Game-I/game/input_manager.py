"""Keyboard mapping kept independent from the scene and UI code."""

from __future__ import annotations

from ursina import held_keys

from game.controls import (CONTROL_BINDINGS, key_axis, signed_movement_axes,
                           vertical_axis)
from movement.flight_physics import Vec3, Vec3 as SimVec3


class InputManager:
    def __init__(self, game):
        self.game = game

    def turn_axis(self) -> float:
        return key_axis(held_keys, CONTROL_BINDINGS["move_right"], CONTROL_BINDINGS["move_left"])

    def movement(self, *, flying: bool = False) -> tuple[Vec3, float]:
        forward_axis, right_axis = signed_movement_axes(held_keys)
        sentry = self.game.sentry
        position = SimVec3(sentry.x, sentry.y, sentry.z)
        camera_yaw = self.game.camera.yaw
        if flying:
            up = self.game.planet.normal(position)
            forward = self.game.camera.aim_direction(position)
            forward_flat = self.game.planet.heading(position, self.game.camera.flight_yaw)
            from game.island_frame import cross
            right = cross(up, forward_flat).normalized()
            direction = (forward * forward_axis + right * right_axis).clamped(1.0)
            if forward_axis != 0.0:
                return direction, 0.0  # the aim decides the climb; Space and Ctrl never override it
        else:
            forward = self.game.planet.heading(position, camera_yaw)
            right, _, _ = self.game.planet.tangent_frame(position)
            direction = (forward * forward_axis + right * right_axis).clamped(1.0)
        vertical = vertical_axis(held_keys)
        return direction, vertical
