"""Small angle/vector helpers shared by flight steering and body orientation."""

from __future__ import annotations

from math import acos, atan2, cos, degrees, radians, sin, sqrt

from movement.flight_physics import Vec3, rotate_towards_degrees

DIVE_PITCH = 165.0  # head down, nearly along a straight dive


def direction_from_yaw_pitch(yaw: float, pitch: float, forward_axis: float = 1.0) -> Vec3:
    yaw_radians = radians(yaw)
    pitch_radians = radians(pitch)
    horizontal = cos(pitch_radians) * forward_axis
    return Vec3(sin(yaw_radians) * horizontal,
                sin(pitch_radians) * forward_axis,
                cos(yaw_radians) * horizontal)


def orientation_from_velocity(velocity: Vec3) -> tuple[float, float]:
    horizontal_speed = sqrt(velocity.x * velocity.x + velocity.z * velocity.z)
    if horizontal_speed < 1e-5:
        return 0.0, 0.0 if abs(velocity.y) < 1e-5 else (-65.0 if velocity.y > 0 else 65.0)
    yaw = degrees(atan2(velocity.x, velocity.z)) % 360.0
    pitch = max(-65.0, min(65.0, -degrees(atan2(velocity.y, horizontal_speed))))
    return yaw, pitch


def upright_flight_yaw(velocity: Vec3, current_yaw: float) -> float:
    """Face horizontal travel while leaving pitch and roll to the upright pose."""
    horizontal_speed = sqrt(velocity.x * velocity.x + velocity.z * velocity.z)
    if horizontal_speed < 1.0:
        return current_yaw
    target = degrees(atan2(velocity.x, velocity.z))
    return current_yaw + ((target - current_yaw + 180.0) % 360.0 - 180.0)


def flight_posture(velocity: Vec3, forward: Vec3, up: Vec3,
                   *, backward_intent: bool = False,
                   neutral_intent: bool = False) -> tuple[float, float]:
    """Return local pitch and bank targets without changing facing direction.

    Angles are degrees around the sentry's local X (pitch) and Z (bank) axes.
    Backward movement deliberately retains an upright posture.
    """
    def dot(a: Vec3, b: Vec3) -> float:
        return a.x * b.x + a.y * b.y + a.z * b.z

    def cross(a: Vec3, b: Vec3) -> Vec3:
        return Vec3(a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z,
                    a.x*b.y-a.y*b.x)

    up = up.normalized()
    forward = (forward - up * dot(forward, up)).normalized()
    if forward.length() < 1e-5:
        return 0.0, 0.0
    right = cross(up, forward).normalized()
    forward_speed = dot(velocity, forward)
    lateral_speed = dot(velocity, right)
    vertical_speed = dot(velocity, up)

    if (neutral_intent or backward_intent or forward_speed < -2.0
            or velocity.length() < 3.0):
        return 0.0, 0.0

    if abs(vertical_speed) < 2.0 and abs(forward_speed) < 2.0:
        pitch = 0.0
    elif abs(forward_speed) < 2.0 and vertical_speed > 0.0:
        pitch = -18.0
    elif abs(forward_speed) < 2.0 and vertical_speed < 0.0:
        pitch = DIVE_PITCH
    else:
        # Local +Y points along the travel vector: forward flight leans toward
        # horizontal while a descent rotates past horizontal into a dive.
        pitch = max(-22.0, min(DIVE_PITCH,
                               degrees(atan2(forward_speed, vertical_speed))))

    bank = max(-28.0, min(28.0, -lateral_speed * 0.32))
    return pitch, bank


def quaternion_slerp(start: tuple[float, float, float, float],
                     end: tuple[float, float, float, float],
                     amount: float) -> tuple[float, float, float, float]:
    """Shortest-arc spherical interpolation for (w, x, y, z) quaternions."""
    amount = max(0.0, min(1.0, amount))
    a = tuple(float(value) for value in start)
    b = tuple(float(value) for value in end)
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:
        b = tuple(-value for value in b)
        dot = -dot
    dot = max(-1.0, min(1.0, dot))
    if dot > 0.9995:
        result = tuple(x + (y - x) * amount for x, y in zip(a, b))
        length = sqrt(sum(value * value for value in result))
        return tuple(value / max(length, 1e-12) for value in result)
    angle = acos(dot)
    sine = sin(angle)
    first = sin((1.0 - amount) * angle) / sine
    second = sin(amount * angle) / sine
    return tuple(first * x + second * y for x, y in zip(a, b))
