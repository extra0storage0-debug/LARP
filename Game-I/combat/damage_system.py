"""Shared health and damage thresholds for props, vehicles, and towers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Damageable:
    maximum_health: float
    health: float | None = None
    broken: bool = False

    def __post_init__(self) -> None:
        self.maximum_health = max(1.0, float(self.maximum_health))
        if self.health is None:
            self.health = self.maximum_health
        self.health = max(0.0, min(self.maximum_health, float(self.health)))
        self.broken = self.health <= 0.0

    @property
    def health_fraction(self) -> float:
        return float(self.health or 0.0) / self.maximum_health

    def apply(self, amount: float) -> float:
        if self.broken or amount <= 0.0:
            return 0.0
        actual = min(float(amount), float(self.health or 0.0))
        self.health = max(0.0, float(self.health or 0.0) - actual)
        self.broken = self.health <= 0.0
        return actual


def impact_damage(speed_mps: float, threshold_mps: float = 18.0, scale: float = 2.5,
                  maximum: float = 300.0) -> float:
    """Convert relative collision speed into capped damage."""
    if speed_mps <= threshold_mps:
        return 0.0
    return min(maximum, max(1.0, (speed_mps - threshold_mps) * scale))
