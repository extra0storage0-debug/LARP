"""Health, resistances and status effects, with no engine dependency.

There is deliberately no energy, stamina or meter here: those are unlimited, so nothing
exists that could run out or block an ability. Healing runs all the time, in and out of
combat, and only stops while downed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DOWNED_SECONDS = 10.0
REVIVE_FRACTION = .5

PHYSICAL, HEAT, COLD, ENERGY, EXPLOSION, IMPACT, RADIATION = (
    "physical", "heat", "cold", "energy", "explosion", "impact", "radiation")
BLOCKABLE = {PHYSICAL, IMPACT, ENERGY, HEAT}


@dataclass(slots=True)
class Vitals:
    max_health: float = 1000.0
    health: float = 1000.0
    resistance: float = 0.0
    impact_resistance: float = 0.0
    knockback_resistance: float = 0.0
    radiation_resistance: float = 0.0
    regen: float = 0.0  # share of max_health restored per second
    regen_scale: float = 1.0
    statuses: dict[str, float] = field(default_factory=dict)  # name -> seconds left
    downed_for: float = 0.0
    damage_taken: float = 0.0

    @property
    def downed(self) -> bool:
        return self.downed_for > 0.0

    @property
    def nullified(self) -> bool:
        return self.has("nullified")

    @property
    def immobile(self) -> bool:
        return self.downed or self.has("frozen") or self.has("restrained") or self.has("held")

    @property
    def speed_scale(self) -> float:
        return .45 if self.has("slowed") else 1.0

    @property
    def fraction(self) -> float:
        return self.health / self.max_health if self.max_health > 0.0 else 0.0

    def has(self, status: str) -> bool:
        return self.statuses.get(status, 0.0) > 0.0

    def add_status(self, status: str, seconds: float) -> None:
        if seconds > 0.0:
            self.statuses[status] = max(self.statuses.get(status, 0.0), float(seconds))

    def clear_status(self, status: str) -> None:
        self.statuses.pop(status, None)

    def take(self, amount: float, kind: str = PHYSICAL) -> float:
        """Apply resistances and return the damage actually dealt."""
        if self.downed or amount <= 0.0:
            return 0.0
        resist = self.resistance
        scale = 1.0 - min(.95, max(0.0, resist) / 100.0)
        if kind == IMPACT:
            scale *= 1.0 - min(1.0, max(0.0, self.impact_resistance) / 100.0)
        elif kind == RADIATION:
            scale *= 1.0 - min(1.0, max(0.0, self.radiation_resistance) / 100.0)
        dealt = min(self.health, float(amount) * scale)
        self.health -= dealt
        self.damage_taken += dealt
        if self.health <= 0.0:
            self.health = 0.0
            self.downed_for = DOWNED_SECONDS
            for status in ("frozen", "restrained", "slowed", "held"):
                self.clear_status(status)
        return dealt

    def heal(self, amount: float) -> None:
        if not self.downed and amount > 0.0:
            self.health = min(self.max_health, self.health + amount)

    def knockback_scale(self) -> float:
        return 1.0 - min(1.0, max(0.0, self.knockback_resistance) / 100.0)

    def tick(self, dt: float) -> None:
        for status in tuple(self.statuses):
            self.statuses[status] -= dt
            if self.statuses[status] <= 0.0:
                del self.statuses[status]
        if self.downed:
            self.downed_for = max(0.0, self.downed_for - dt)
            if not self.downed:
                self.health = self.max_health * REVIVE_FRACTION
            return
        self.heal(self.regen * self.regen_scale * self.max_health * dt)

    def snapshot(self) -> dict:
        return {"health": round(self.health, 2),
                "nullified": round(self.statuses.get("nullified", 0.0), 2)}

    def restore(self, saved: dict) -> None:
        """Load saved values, keeping the current ones for anything missing or invalid."""
        def number(key, low, high, fallback):
            value = saved.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
                return fallback
            return max(low, min(high, float(value)))

        self.health = number("health", 1.0, self.max_health, self.health)
        left = number("nullified", 0.0, 86400.0, 0.0)
        if left > 0.0:
            self.add_status("nullified", left)
