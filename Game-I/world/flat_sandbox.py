"""Flat local frame used by the empty sandbox."""

from __future__ import annotations

from math import cos, exp, radians, sin

from movement.flight_physics import Vec3


class FlatSandboxFrame:
    """Earth-strength gravity and heading math over a genuinely flat XZ plane."""

    radius = 0.0
    gravity_strength = 9.80665
    gravity_multiplier = 1.0
    landable = True
    chart_east = Vec3(1.0, 0.0, 0.0)
    chart_up = Vec3(0.0, 1.0, 0.0)
    chart_north = Vec3(0.0, 0.0, 1.0)

    def normal(self, _position: Vec3) -> Vec3:
        return self.chart_up

    @staticmethod
    def altitude(position: Vec3) -> float:
        return float(position.y)

    @staticmethod
    def project(position: Vec3, altitude: float = 0.0) -> Vec3:
        return Vec3(position.x, altitude, position.z)

    def gravity(self, _position: Vec3) -> Vec3:
        return Vec3(0.0, -self.gravity_strength * self.gravity_multiplier, 0.0)

    @staticmethod
    def is_ocean(_position: Vec3) -> bool:
        return False

    @staticmethod
    def atmosphere_density(altitude: float) -> float:
        return exp(-max(-1000.0, float(altitude)) / 8500.0)

    def tangent_frame(self, _position: Vec3) -> tuple[Vec3, Vec3, Vec3]:
        return self.chart_east, self.chart_up, self.chart_north

    def heading(self, _position: Vec3, yaw_degrees: float,
                pitch_degrees: float = 0.0) -> Vec3:
        yaw = radians(yaw_degrees)
        pitch = radians(pitch_degrees)
        horizontal = Vec3(sin(yaw), 0.0, cos(yaw))
        return (horizontal * cos(pitch) + self.chart_up * sin(pitch)).normalized()

    @staticmethod
    def point_from_local(eastward: float, northward: float,
                         altitude: float = 0.0) -> Vec3:
        return Vec3(eastward, altitude, northward)

    @staticmethod
    def local_coordinates(position: Vec3) -> tuple[float, float]:
        return float(position.x), float(position.z)

    @staticmethod
    def tangent_move(position: Vec3, displacement: Vec3,
                     altitude: float | None = None) -> Vec3:
        target_height = position.y if altitude is None else altitude
        return Vec3(position.x + displacement.x, target_height,
                    position.z + displacement.z)

    def surface_quaternion(self, _position: Vec3, yaw_degrees: float = 0.0,
                           pitch_degrees: float = 0.0):
        from panda3d.core import LMatrix3f, LQuaternionf, LVector3f

        yaw = radians(yaw_degrees)
        pitch = radians(pitch_degrees)
        heading = Vec3(sin(yaw), 0.0, cos(yaw))
        right = Vec3(cos(yaw), 0.0, -sin(yaw))
        up = self.chart_up
        forward = heading * cos(pitch) - up * sin(pitch)
        camera_up = up * cos(pitch) + heading * sin(pitch)
        basis = LMatrix3f()
        basis.setRow(0, LVector3f(right.x, right.y, right.z))
        basis.setRow(1, LVector3f(camera_up.x, camera_up.y, camera_up.z))
        basis.setRow(2, LVector3f(forward.x, forward.y, forward.z))
        result = LQuaternionf()
        result.setFromMatrix(basis)
        return result

    def surface_plane_quaternion(self, _position: Vec3):
        from panda3d.core import LMatrix3f, LQuaternionf, LVector3f

        basis = LMatrix3f()
        basis.setRow(0, LVector3f(-1.0, 0.0, 0.0))
        basis.setRow(1, LVector3f(0.0, 0.0, 1.0))
        basis.setRow(2, LVector3f(0.0, 1.0, 0.0))
        result = LQuaternionf()
        result.setFromMatrix(basis)
        return result

    def orient_entity(self, entity, position: Vec3, yaw_degrees: float = 0.0,
                      pitch_degrees: float = 0.0) -> None:
        entity.setQuat(self.surface_quaternion(position, yaw_degrees, pitch_degrees))
