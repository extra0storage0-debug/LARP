"""Neutral, geometry-free reference frame for character movement and flight."""

from __future__ import annotations

from math import cos, radians, sin

from movement.flight_physics import Vec3


def dot(a: Vec3, b: Vec3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def cross(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.y * b.z - a.z * b.y,
                a.z * b.x - a.x * b.z,
                a.x * b.y - a.y * b.x)


def rotate_about(vector: Vec3, axis: Vec3, degrees: float) -> Vec3:
    """Rodrigues rotation retained for flight steering."""
    from math import radians as to_radians
    axis = axis.normalized()
    angle = to_radians(degrees)
    return (vector * cos(angle) + cross(axis, vector) * sin(angle)
            + axis * (dot(axis, vector) * (1.0 - cos(angle))))


class NeutralFrame:
    """Flat physics reference with no rendered surface or world geometry."""

    landable = True
    radius = 0.0

    def __init__(self):
        self.gravity_multiplier = 1.0

    def normal(self, position: Vec3) -> Vec3:
        return Vec3(0.0, 1.0, 0.0)

    def altitude(self, position: Vec3) -> float:
        return float(position.y)

    radial_altitude = altitude

    def project(self, position: Vec3, altitude: float = 0.0) -> Vec3:
        return Vec3(position.x, altitude, position.z)

    def gravity(self, position: Vec3) -> Vec3:
        return Vec3(0.0, -9.80665 * self.gravity_multiplier, 0.0)

    def tangent_frame(self, position: Vec3) -> tuple[Vec3, Vec3, Vec3]:
        return Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)

    def heading(self, position: Vec3, yaw_degrees: float,
                pitch_degrees: float = 0.0) -> Vec3:
        yaw, pitch = radians(yaw_degrees), radians(pitch_degrees)
        return Vec3(sin(yaw) * cos(pitch), sin(pitch), cos(yaw) * cos(pitch))

    def point_from_local(self, eastward: float, northward: float,
                         altitude: float = 0.0) -> Vec3:
        return Vec3(eastward, altitude, northward)

    def local_coordinates(self, position: Vec3) -> tuple[float, float]:
        return float(position.x), float(position.z)

    def tangent_move(self, position: Vec3, displacement: Vec3,
                     altitude: float | None = None) -> Vec3:
        y = position.y if altitude is None else altitude
        return Vec3(position.x + displacement.x, y,
                    position.z + displacement.z)

    @staticmethod
    def surface_quaternion(position: Vec3, yaw_degrees: float = 0.0,
                           pitch_degrees: float = 0.0):
        from panda3d.core import LQuaternionf, LVector3f
        yaw = LQuaternionf()
        yaw.setFromAxisAngle(float(yaw_degrees), LVector3f(0, 1, 0))
        pitch = LQuaternionf()
        pitch.setFromAxisAngle(-float(pitch_degrees), LVector3f(1, 0, 0))
        return yaw * pitch

    def orient_entity(self, entity, position: Vec3, yaw_degrees: float = 0.0,
                      pitch_degrees: float = 0.0) -> None:
        entity.setQuat(self.surface_quaternion(position, yaw_degrees, pitch_degrees))

    @staticmethod
    def surface_plane_quaternion(position: Vec3):
        from panda3d.core import LQuaternionf, LVector3f
        result = LQuaternionf()
        result.setFromAxisAngle(90.0, LVector3f(1, 0, 0))
        return result
