"""Engine-independent camera yaw and flight steering input integration."""

from __future__ import annotations


def apply_flight_steering(yaw: float, pitch: float, mouse_dx: float, mouse_dy: float,
                          dt: float, steering_axis: float, *, turn_rate: float = 125.0,
                          pitch_rate: float = 90.0, min_pitch: float = -5.0,
                          max_pitch: float = 34.0) -> tuple[float, float]:
    """Legacy standalone helper; live gameplay uses the shared camera yaw/pitch."""
    dt = max(float(dt), 1e-4)
    steer_rate = max(-1.0, min(1.0, float(steering_axis))) * turn_rate
    # Keep an unwrapped angle so repeated turns never jump across 0/360.
    yaw = float(yaw) + float(mouse_dx) * turn_rate + steer_rate * dt
    pitch = float(pitch) - float(mouse_dy) * pitch_rate
    return yaw, pitch


def apply_camera_input(yaw: float, pitch: float, mouse_dx: float, mouse_dy: float,
                       dt: float, steering_axis: float, *, flying: bool,
                       turn_rate: float = 125.0, mouse_pitch_rate: float = 90.0,
                       min_pitch: float = -5.0, max_pitch: float = 34.0,
                       camera_x_axis: float = 0.0, camera_y_axis: float = 0.0,
                       arrow_turn_rate: float = 90.0, arrow_pitch_rate: float = 65.0
                       ) -> tuple[float, float, float]:
    """Integrate mouse and arrow camera controls, keeping player steering separate."""
    dt = max(float(dt), 1e-4)
    mouse_yaw_delta = float(mouse_dx) * turn_rate
    arrow_yaw_delta = float(camera_x_axis) * arrow_turn_rate * dt
    steer_rate = max(-1.0, min(1.0, float(steering_axis))) * turn_rate if flying else 0.0
    yaw = float(yaw) + mouse_yaw_delta + arrow_yaw_delta + steer_rate * dt
    pitch_delta = -float(mouse_dy) * mouse_pitch_rate - float(camera_y_axis) * arrow_pitch_rate * dt
    pitch = float(pitch) + pitch_delta
    mouse_yaw_rate = mouse_yaw_delta / dt
    turn_intent = max(-1.0, min(1.0,
                                (mouse_yaw_rate + arrow_yaw_delta / dt + steer_rate) / turn_rate)) if flying else 0.0
    return yaw, pitch, turn_intent
