"""Renderer-independent pedestrian state, navigation, and damage model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from random import Random

from movement.flight_physics import Vec3


class CivilianState(Enum):
    IDLE = auto()
    WALKING = auto()
    RUNNING = auto()
    TALKING = auto()
    CROSSING_ROAD = auto()
    EXPLORING = auto()
    SCARED = auto()
    FLEEING = auto()
    INJURED = auto()
    DEAD = auto()

    # Compatibility aliases used by the original AI and tests.
    WANDER = WALKING
    FLEE = FLEEING


@dataclass(slots=True)
class CivilianBrain:
    position: Vec3
    state: CivilianState = CivilianState.WALKING
    target: Vec3 | None = None
    reaction_time: float = 0.0
    speed: float = 1.8
    health: float = 100.0
    maximum_health: float = 100.0
    fear_time: float = 0.0
    injury_time: float = 0.0

    @property
    def alive(self) -> bool:
        return self.state is not CivilianState.DEAD and self.health > 0.0

    def react_to_danger(self, origin: Vec3, rng: Random | None = None) -> None:
        if not self.alive:
            return
        rng = rng or Random()
        away = Vec3(self.position.x - origin.x, 0.0,
                    self.position.z - origin.z).normalized()
        if away.length() == 0.0:
            away = Vec3(rng.uniform(-1, 1), 0.0,
                        rng.uniform(-1, 1)).normalized()
        self.target = self.position + away * rng.uniform(14.0, 24.0)
        # Preserve the original immediate flee response when the player or a
        # damaging event enters the danger radius. The SCARED state remains
        # available for lower intensity damage reactions.
        self.state = CivilianState.FLEEING
        self.fear_time = 0.0
        self.reaction_time = rng.uniform(3.0, 5.0)

    def apply_damage(self, amount: float) -> float:
        """Apply fictional, non-graphic damage once and enter injured/dead states."""
        if not self.alive or amount <= 0.0:
            return 0.0
        actual = min(self.health, float(amount))
        self.health = max(0.0, self.health - actual)
        if self.health <= 0.0:
            self.state = CivilianState.DEAD
            self.target = None
            self.reaction_time = 0.0
            return actual
        if self.health <= self.maximum_health * .4:
            self.state = CivilianState.INJURED
            self.injury_time = max(self.injury_time, 2.5)
        else:
            self.state = CivilianState.SCARED
            self.fear_time = .3
            self.reaction_time = max(self.reaction_time, 2.0)
        return actual

    def step(self, dt: float, *, danger: Vec3 | None = None,
             rng: Random | None = None) -> Vec3:
        dt = max(0.0, min(dt, 0.1))
        if not self.alive:
            return self.position
        if danger is not None:
            dx, dz = self.position.x - danger.x, self.position.z - danger.z
            if dx * dx + dz * dz < 20.0 * 20.0:
                self.react_to_danger(danger, rng)

        if self.fear_time > 0.0:
            self.fear_time = max(0.0, self.fear_time - dt)
            if self.fear_time == 0.0 and self.state is CivilianState.SCARED:
                self.state = CivilianState.FLEEING
        if self.reaction_time > 0.0:
            self.reaction_time = max(0.0, self.reaction_time - dt)
        if (self.reaction_time == 0.0 and self.state in
                (CivilianState.FLEEING, CivilianState.RUNNING)):
            self.state = CivilianState.WALKING
            self.target = None
        if self.injury_time > 0.0:
            self.injury_time = max(0.0, self.injury_time - dt)
            if self.injury_time == 0.0 and self.health > self.maximum_health * .4:
                self.state = CivilianState.WALKING

        if self.state in (CivilianState.IDLE, CivilianState.TALKING):
            self.reaction_time = max(0.0, self.reaction_time - dt)
            if self.reaction_time == 0.0:
                self.state = CivilianState.WALKING
            else:
                return self.position
        if self.target is None:
            return self.position
        delta = self.target - self.position
        distance = Vec3(delta.x, 0.0, delta.z).length()
        if distance < 0.5:
            self.target = None
            return self.position
        if self.state in (CivilianState.FLEEING, CivilianState.RUNNING):
            speed = 5.5
        elif self.state is CivilianState.INJURED:
            speed = .65
        elif self.state is CivilianState.CROSSING_ROAD:
            speed = 3.1
        else:
            speed = self.speed
        direction = Vec3(delta.x, 0.0, delta.z).normalized()
        self.position = self.position + direction * min(distance, speed * dt)
        return self.position
