"""Renderer-independent prop state and debris budget."""

from __future__ import annotations

from dataclasses import dataclass, field

from combat.damage_system import Damageable
from movement.flight_physics import Vec3


@dataclass(slots=True)
class DebrisBudget:
    maximum_live_pieces: int = 240
    live_pieces: int = 0
    quantity_scale: float = 1.0

    def reserve(self, requested: int) -> int:
        requested = round(requested * self.quantity_scale)
        allowed = min(max(0, requested), max(0, self.maximum_live_pieces - self.live_pieces))
        self.live_pieces += allowed
        return allowed

    def release(self, count: int) -> None:
        self.live_pieces = max(0, self.live_pieces - max(0, count))


@dataclass(slots=True)
class DestructibleState:
    name: str
    health: Damageable
    position: Vec3
    velocity: Vec3 = field(default_factory=Vec3)
    dynamic: bool = False

    def take_damage(self, amount: float, impulse: Vec3 | None = None) -> bool:
        self.health.apply(amount)
        if impulse is not None:
            self.velocity = self.velocity + impulse
        if self.health.broken:
            self.dynamic = True
        return self.health.broken
