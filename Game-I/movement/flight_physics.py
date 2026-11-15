"""Small engine-independent flight model used by gameplay and unit tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from math import atan2, cos, degrees, exp, radians, sin, sqrt


AIM_TURN_RATE = 12.0  # how fast aimed flight swings momentum onto the aim, per second


def rotate_towards_degrees(current: float, target: float, max_delta: float) -> float:
    delta = (target - current + 180.0) % 360.0 - 180.0
    delta = max(-max_delta, min(max_delta, delta))
    return current + delta


@dataclass(slots=True)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def length(self) -> float:
        return sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalized(self) -> "Vec3":
        magnitude = self.length()
        return self * (1.0 / magnitude) if magnitude > 1e-8 else Vec3()

    def clamped(self, maximum: float) -> "Vec3":
        magnitude = self.length()
        return self * (maximum / magnitude) if magnitude > maximum > 0.0 else self


HOVER_BRAKE = 1.7  # per second, on top of inertia, with no direction input


class FlightPhase(Enum):
    GROUNDED = auto()
    TAKEOFF = auto()
    CRUISE = auto()
    LANDING = auto()
    GROUND_IMPACT = auto()


@dataclass(slots=True)
class FlightConfig:
    cruise_speed: float = 82.0       # metres per second
    boost_speed: float = 520.0
    ground_speed: float = 11.0
    acceleration: float = 42.0
    boost_acceleration: float = 95.0
    braking_deceleration: float = 100.0
    steering_rate: float = 125.0
    takeoff_seconds: float = 0.75
    landing_speed: float = 24.0
    ground_impact_speed: float = 95.0
    flight_inertia: float = 0.70
    vertical_ascent_speed: float = 25.0
    air_resistance: float = 0.000035
    atmospheric_drag: float = 1.0
    gravity_multiplier: float = 1.0
    maximum_falling_speed: float = 150.0
    takeoff_impulse: float = 7.5
    horizontal_speed_scale: float = 1.0


class FlightDynamics:
    """Stateful velocity integrator. World position integration remains with the caller."""

    def __init__(self, config: FlightConfig | None = None) -> None:
        self.config = config or FlightConfig()
        self.phase = FlightPhase.GROUNDED
        self.velocity = Vec3()
        self.phase_time = 0.0
        self.allowed = True  # a character without flight refuses it here

    @property
    def speed_mps(self) -> float:
        return self.velocity.length()

    @property
    def speed_kmh(self) -> float:
        return self.speed_mps * 3.6

    @property
    def is_flying(self) -> bool:
        return self.phase is not FlightPhase.GROUNDED

    def toggle_flight(self, up: Vec3 | None = None) -> None:
        if not self.allowed:
            return
        up = (up or Vec3(0.0, 1.0, 0.0)).normalized()
        if self.phase is FlightPhase.GROUNDED:
            self.phase = FlightPhase.TAKEOFF
            self.phase_time = 0.0
            outward_speed = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            self.velocity = self.velocity + up * max(0.0, self.config.takeoff_impulse - outward_speed)
        elif self.phase in (FlightPhase.LANDING, FlightPhase.GROUND_IMPACT):
            self.phase = FlightPhase.CRUISE
            self.phase_time = 0.0
        else:
            self.phase = FlightPhase.LANDING
            self.phase_time = 0.0

    def start_ground_impact(self) -> bool:
        if not self.is_flying or self.phase is FlightPhase.GROUND_IMPACT:
            return False
        self.phase = FlightPhase.GROUND_IMPACT
        self.phase_time = 0.0
        return True

    def step(self, direction: Vec3, vertical: float, dt: float, *, boost: bool = False,
             brake: bool = False, ground_distance: float | None = None,
             steering_direction: Vec3 | None = None, up: Vec3 | None = None,
             gravity: Vec3 | None = None, air_density: float = 0.0,
             aimed: bool = False) -> Vec3:
        """``aimed`` is the player's flight: ``direction`` is exact, in all three dimensions.

        AI leaves it off and keeps the gentler steering below, which only turns horizontally.
        """
        dt = max(0.0, min(dt, 0.1))
        up = (up or Vec3(0.0, 1.0, 0.0)).normalized()
        self.phase_time += dt
        direction = direction.clamped(1.0)
        hovering = (direction.length() < 1e-5 and abs(vertical) < 1e-5
                    and not brake)

        if self.phase is FlightPhase.GROUNDED:
            target = direction * self.config.ground_speed
            blend = min(1.0, dt * 9.0)
            self.velocity = self.velocity * (1.0 - blend) + target * blend
            self.velocity = self.velocity - up * (self.velocity.x * up.x
                                                     + self.velocity.y * up.y
                                                     + self.velocity.z * up.z)
            return self.velocity

        if self.phase is FlightPhase.TAKEOFF and self.phase_time >= self.config.takeoff_seconds:
            self.phase = FlightPhase.CRUISE

        if self.phase is FlightPhase.GROUND_IMPACT:
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            tangent = self.velocity - up * radial
            tangent = tangent * exp(-5.0 * dt)
            self.velocity = tangent - up * self.config.ground_impact_speed
            if ground_distance is not None and ground_distance <= 0.05:
                self.velocity = Vec3()
                self.phase = FlightPhase.GROUNDED
            return self.velocity

        if self.phase is FlightPhase.LANDING:
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            tangent = self.velocity - up * radial
            tangent = tangent * exp(-2.6 * dt)
            radial += (-self.config.landing_speed - radial) * min(1.0, dt * 2.0)
            self.velocity = tangent + up * radial
            if ground_distance is not None and ground_distance <= 0.05:
                self.velocity = Vec3()
                self.phase = FlightPhase.GROUNDED
            return self.velocity

        if aimed and not brake and direction.length() > 1e-5:
            return self._fly_along(direction, dt, boost, air_density)

        if gravity is not None and self.phase is FlightPhase.CRUISE:
            eff_gravity = gravity * self.config.gravity_multiplier
            if hovering:
                # Powered neutral flight holds altitude without inventing
                # horizontal thrust. Damp radial drift so existing vertical
                # velocity settles smoothly into a hands-off hover.
                radial_speed = (self.velocity.x * up.x + self.velocity.y * up.y
                                + self.velocity.z * up.z)
                radial_gravity = (eff_gravity.x * up.x + eff_gravity.y * up.y
                                  + eff_gravity.z * up.z)
                hover_acceleration = -radial_gravity - radial_speed * 3.0
                self.velocity = (self.velocity + eff_gravity * dt
                                 + up * (hover_acceleration * dt))
            else:
                radial_gravity = (eff_gravity.x * up.x + eff_gravity.y * up.y + eff_gravity.z * up.z)
                tangent_speed = (self.velocity - up * (self.velocity.x * up.x
                                                        + self.velocity.y * up.y
                                                        + self.velocity.z * up.z)).length()
                # Powered flight supplies lift while moving; vertical input
                # remains subject to the existing planetary gravity model.
                lift = -radial_gravity if tangent_speed > 5.0 else 0.0
                self.velocity = self.velocity + (eff_gravity + up * lift) * dt

        vertical = max(-1.0, min(1.0, vertical))
        vertical_scale = (self.config.vertical_ascent_speed / 25.0) if vertical > 0 else (self.config.landing_speed / 24.0)
        direction = (direction + up * (vertical * vertical_scale)).clamped(1.0)
        if brake:
            speed = max(0.0, self.speed_mps - self.config.braking_deceleration * dt)
            self.velocity = self.velocity.normalized() * speed
        else:
            steering = steering_direction if steering_direction is not None else direction
            radial_speed = (self.velocity.x * up.x + self.velocity.y * up.y
                            + self.velocity.z * up.z)
            tangent_velocity = self.velocity - up * radial_speed
            steering_tangent = steering - up * (steering.x * up.x + steering.y * up.y
                                                  + steering.z * up.z)
            horizontal_speed = tangent_velocity.length()
            if steering_tangent.length() > 1e-5 and horizontal_speed > 1.0:
                from game.island_frame import rotate_about
                current = tangent_velocity.normalized()
                target = steering_tangent.normalized()
                signed_angle = degrees(atan2(
                    up.x * (current.y * target.z - current.z * target.y)
                    + up.y * (current.z * target.x - current.x * target.z)
                    + up.z * (current.x * target.y - current.y * target.x),
                    current.x * target.x + current.y * target.y + current.z * target.z))
                turn = max(-self.config.steering_rate * dt,
                           min(self.config.steering_rate * dt, signed_angle))
                tangent_velocity = rotate_about(current * horizontal_speed, up, turn)
                self.velocity = tangent_velocity + up * radial_speed
            acceleration = self.config.boost_acceleration if boost else self.config.acceleration
            if direction.length() > 0.0:
                self.velocity = self.velocity + direction * acceleration * dt
            else:
                inertia_decay = (1.0 - max(0.0, min(1.0, self.config.flight_inertia))) * 2.3 + 0.01
                if aimed:  # the player's flyer stops itself to hover, instead of drifting on for seconds
                    inertia_decay += HOVER_BRAKE
                self.velocity = self.velocity * exp(-inertia_decay * dt)

        maximum = self.config.boost_speed if boost else self.config.cruise_speed
        if aimed:  # no input: coast down smoothly, whatever direction it was flying
            self._ease_to_limit(maximum, dt)
            return self._air_drag(dt, air_density)
        self.velocity = self.velocity.clamped(maximum)
        if self.config.horizontal_speed_scale != 1.0:
            radial = self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z
            tangent = self.velocity - up * radial
            self.velocity = (tangent.clamped(maximum * self.config.horizontal_speed_scale)
                             + up * radial)

        # Enforce maximum falling speed
        downward_speed = -(self.velocity.x * up.x + self.velocity.y * up.y + self.velocity.z * up.z)
        if downward_speed > self.config.maximum_falling_speed:
            excess = downward_speed - self.config.maximum_falling_speed
            self.velocity = self.velocity + up * excess

        return self._air_drag(dt, air_density)

    def _fly_along(self, direction: Vec3, dt: float, boost: bool, air_density: float) -> Vec3:
        """Powered flight along the aim: it supplies its own lift, so gravity plays no part."""
        aim = direction.normalized()
        # Momentum swings onto the aim instead of fighting it, losing speed only on a sharp reversal.
        self.velocity = self.velocity + (aim * self.speed_mps - self.velocity) * (1.0 - exp(-AIM_TURN_RATE * dt))
        acceleration = self.config.boost_acceleration if boost else self.config.acceleration
        before = self.speed_mps
        self.velocity = self.velocity + direction * (acceleration * dt)
        limit = self.config.boost_speed if boost else self.config.cruise_speed
        # Thrust takes it up to the limit and no further; easing down only deals with what it is over already.
        ceiling = max(limit, before)
        if self.speed_mps > ceiling:
            self.velocity = self.velocity * (ceiling / self.speed_mps)
        self._ease_to_limit(limit, dt)
        return self._air_drag(dt, air_density)

    def _ease_to_limit(self, maximum: float, dt: float) -> None:
        """Over the limit (a boost just let go): slow to it smoothly rather than snapping."""
        speed = self.speed_mps
        if speed > maximum:
            allowed = max(maximum, speed - self.config.braking_deceleration * dt)
            self.velocity = self.velocity * (allowed / speed)

    def _air_drag(self, dt: float, air_density: float) -> Vec3:
        speed = self.velocity.length()
        density = max(0.0, min(1.2, air_density))
        # Quadratic aerodynamic drag, scaled by the local atmospheric density.
        drag_fraction = min(.95, self.config.air_resistance * self.config.atmospheric_drag * density * speed * dt)
        self.velocity = self.velocity * (1.0 - drag_fraction)
        return self.velocity

    def resolve_landing(self) -> None:
        self.velocity = Vec3()
        self.phase = FlightPhase.GROUNDED
        self.phase_time = 0.0
