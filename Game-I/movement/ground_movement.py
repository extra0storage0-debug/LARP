"""Ground movement with acceleration, braking, top-speed caps, and burst dash."""

from __future__ import annotations

from math import exp

from movement.flight_physics import Vec3


class GroundMovement:
    def __init__(self, walk_speed: float = 11.0, sprint_multiplier: float = 2.5,
                 acceleration: float = 48.0, deceleration: float = 9.0,
                 max_running_speed: float = 40.0, dash_speed: float = 80.0,
                 dash_duration: float = 0.25, dash_cooldown: float = 1.0) -> None:
        self.walk_speed = walk_speed
        self.sprint_multiplier = sprint_multiplier
        self.acceleration = acceleration
        self.air_acceleration = None  # the same as on the ground, unless a character says otherwise
        self.deceleration = deceleration
        self.max_running_speed = max_running_speed
        self.dash_speed = dash_speed
        self.dash_duration = dash_duration
        self.dash_cooldown = dash_cooldown
        self.dash_timer = 0.0
        self.dash_cooldown_timer = 0.0
        self.walk_pace = None          # W alone, for the player. Unset, W moves at walk_speed, which is what AI wants
        self.walk_acceleration = 6.5   # from standing into a walk takes a moment, as it does for anyone
        self.velocity = Vec3()

    def trigger_dash(self) -> bool:
        if self.dash_cooldown_timer <= 0.0:
            self.dash_timer = self.dash_duration
            self.dash_cooldown_timer = self.dash_cooldown
            return True
        return False

    @property
    def is_dashing(self) -> bool:
        return self.dash_timer > 0.0

    def step(self, direction: Vec3, dt: float, *, sprint: bool = False, coast: bool = False) -> Vec3:
        """``coast`` is the air: with no input there is no ground to slow down against."""
        dt = max(0.0, min(dt, 0.1))
        direction = direction.clamped(1.0)

        # Update dash timers
        if self.dash_timer > 0.0:
            self.dash_timer = max(0.0, self.dash_timer - dt)
        if self.dash_cooldown_timer > 0.0:
            self.dash_cooldown_timer = max(0.0, self.dash_cooldown_timer - dt)

        if self.dash_timer > 0.0:
            speed = self.dash_speed
        else:
            base_speed = self.walk_speed * (self.sprint_multiplier if sprint else 1.0)
            speed = min(self.max_running_speed, base_speed)
        walking = self.walk_pace is not None and not sprint and self.dash_timer <= 0.0 and not coast
        if walking:
            speed = self.walk_pace

        target = direction * speed
        if direction.length() > 0:
            rate = self.air_acceleration if coast and self.air_acceleration is not None else self.acceleration
            if walking and self.velocity.length() <= speed * 1.1:
                rate = self.walk_acceleration
            blend = min(1.0, rate * dt / max(speed, 1.0))
            self.velocity = self.velocity * (1.0 - blend) + target * blend
        elif not coast:
            self.velocity = self.velocity * exp(-self.deceleration * dt)
        return self.velocity
