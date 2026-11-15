"""Minimal local atmosphere used by flight effects over the island."""

from __future__ import annotations
from math import exp

class IslandEnvironment:
    def __init__(self):
        self.quality = "low"

    @staticmethod
    def air_density(altitude: float) -> float:
        return exp(-max(0.0, altitude) / 8500.0)

    @staticmethod
    def reentry_heat(altitude: float, speed: float, radial_speed: float) -> float:
        speed_factor = max(0.0, min(1.0, (speed - 120.0) / 650.0))
        descent_factor = max(0.0, min(1.0, -radial_speed / 180.0))
        density = exp(-max(0.0, altitude) / 11_000.0)
        return max(0.0, min(1.0, speed_factor * descent_factor * density))

    def set_quality(self, quality: str) -> None:
        self.quality = quality

    def update(self, dt: float) -> None:
        return None
