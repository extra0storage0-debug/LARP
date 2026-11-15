"""Flight boost timing. The combat rules that used to live here are gone with the powers."""

from __future__ import annotations


class BoostGate:
    """Boost duration and cooldown; a zero duration means unlimited, as originally."""

    def __init__(self) -> None:
        self.used = 0.0
        self.cooling = 0.0

    def allow(self, wanted: bool, dt: float, duration: float, cooldown: float) -> bool:
        dt = max(0.0, float(dt))
        if self.cooling > 0.0:
            self.cooling = max(0.0, self.cooling - dt)
            return False
        if not wanted:
            self.used = 0.0
            return False
        if duration <= 0.0:
            return True
        self.used += dt
        if self.used >= duration:
            self.used = 0.0
            self.cooling = max(0.0, float(cooldown))
            return False
        return True
