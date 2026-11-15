"""Flat local coordinate frame that maps character physics onto the island."""

from __future__ import annotations

from math import cos, radians, sin
from panda3d.core import LQuaternionf
from movement.flight_physics import Vec3

def cross(a, b):
    return Vec3(a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x)

def dot(a, b) -> float:
    return float(a.x*b.x + a.y*b.y + a.z*b.z)

def rotate_about(vector, axis, degrees: float):
    angle = radians(degrees)
    axis = axis.normalized()
    return vector*cos(angle) + cross(axis,vector)*sin(angle) + axis*(dot(axis,vector)*(1-cos(angle)))

class IslandFrame:
    landable = True
    WATER_LEVEL = -1.8
    MAX_FLIGHT_ALTITUDE = 500.0
    BOUNDARY_MARGIN = 18.0
    radius = 5_000.0
    origin_latitude = 0.0

    def __init__(self, world):
        self.world = world
        self.gravity_multiplier = 1.0

    def height(self, x: float, z: float) -> float:
        if self.world.contains_position(x, z):
            return self.world.height_at(x, z)
        return self.WATER_LEVEL

    def point_from_local(self, east: float, north: float, altitude: float = 0.0) -> Vec3:
        return Vec3(float(east), self.height(east, north) + altitude, float(north))

    @staticmethod
    def local_coordinates(position) -> tuple[float, float]:
        return float(position.x), float(position.z)

    def normal(self, position) -> Vec3:
        return Vec3(0.0, 1.0, 0.0)

    def altitude(self, position) -> float:
        return float(position.y) - self.height(float(position.x), float(position.z))

    def is_ocean(self, position) -> bool:
        return not self.world.contains_position(float(position.x), float(position.z))

    @staticmethod
    def boundary_value(x: float, z: float) -> float:
        """Rounded-square island footprint that fits a 10 km world extent."""
        return (abs(float(x)) / 5000.0) ** 4 + (abs(float(z)) / 5000.0) ** 4

    def clamp_to_land(self, x: float, z: float, margin: float | None = None) -> tuple[float, float]:
        margin = self.BOUNDARY_MARGIN if margin is None else max(0.0, float(margin))
        limit = max(.01, 1.0 - margin / 5000.0)
        value = self.boundary_value(x, z)
        if value <= limit:
            return float(x), float(z)
        factor = (limit / max(value, 1e-9)) ** .25
        return float(x) * factor, float(z) * factor

    def clamp_flight_altitude(self, position, velocity=None):
        """Enforce the sea-level flight ceiling and cancel upward excess speed."""
        if float(position.y) <= self.MAX_FLIGHT_ALTITUDE:
            return position
        if velocity is not None and velocity.y > 0.0:
            velocity.y = 0.0
        return Vec3(float(position.x), self.MAX_FLIGHT_ALTITUDE, float(position.z))

    def project(self, position, altitude: float) -> Vec3:
        x, z = float(position.x), float(position.z)
        return Vec3(x, self.height(x, z) + float(altitude), z)

    def gravity(self, position=None) -> Vec3:
        return Vec3(0.0, -9.81 * self.gravity_multiplier, 0.0)

    @staticmethod
    def atmosphere_density(altitude: float) -> float:
        from math import exp
        return exp(-max(-1000.0, float(altitude)) / 8500.0)

    def tangent_move(self, position, displacement, altitude: float = .25) -> Vec3:
        x = float(position.x) + float(displacement.x)
        z = float(position.z) + float(displacement.z)
        return Vec3(x, self.height(x, z) + altitude, z)

    def heading(self, position, yaw: float, pitch: float = 0.0) -> Vec3:
        y, p = radians(yaw), radians(pitch)
        cp = cos(p)
        return Vec3(sin(y) * cp, sin(p), cos(y) * cp)

    def tangent_frame(self, position):
        return Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)

    def orient_entity(self, entity, position=None, yaw: float = 0.0) -> None:
        entity.rotation = (0, yaw, 0)

    def surface_plane_quaternion(self, position):
        return LQuaternionf.identQuat()

    def surface_quaternion(self, position, yaw: float = 0.0, pitch: float = 0.0):
        """Match the original flat-world camera orientation on island terrain."""
        from panda3d.core import LMatrix3f, LVector3f

        yaw_radians, pitch_radians = radians(yaw), radians(pitch)
        heading = Vec3(sin(yaw_radians), 0.0, cos(yaw_radians))
        right = Vec3(cos(yaw_radians), 0.0, -sin(yaw_radians))
        up = Vec3(0.0, 1.0, 0.0)
        forward = heading * cos(pitch_radians) - up * sin(pitch_radians)
        camera_up = up * cos(pitch_radians) + heading * sin(pitch_radians)
        basis = LMatrix3f()
        basis.setRow(0, LVector3f(right.x, right.y, right.z))
        basis.setRow(1, LVector3f(camera_up.x, camera_up.y, camera_up.z))
        basis.setRow(2, LVector3f(forward.x, forward.y, forward.z))
        result = LQuaternionf()
        result.setFromMatrix(basis)
        return result

    def update_render(self, dt: float, altitude: float = 0.0) -> None:
        return None
