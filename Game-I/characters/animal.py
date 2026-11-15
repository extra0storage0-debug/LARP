"""Procedural wildlife/animals that populate Earth's green zones and open ground."""

from __future__ import annotations

from math import atan2, degrees, sin
from random import Random

from ursina import Entity, Vec3, color
from ursina.shaders import lit_with_shadows_shader

from ai.civilian_ai import CivilianBrain, CivilianState
from movement.flight_physics import Vec3 as SimVec3


class Animal:
    """A procedural 3D land animal (Deer, Dog, Cow, Sheep, Horse, etc.).
    Uses low-poly articulated body parts with shadow shader and wander/flee AI."""

    KINDS = ("deer", "dog", "cow", "sheep", "horse")

    def __init__(self, game, position, seed: int, kind: str | None = None):
        self.game = game
        self.random = Random(seed)
        rng = self.random
        self.kind = kind or rng.choice(self.KINDS)
        self.chart_x, self.chart_z = float(position[0]), float(position[2])
        mapped = game.planet.point_from_local(self.chart_x, self.chart_z)

        # Root entity
        self.entity = Entity(
            position=(mapped.x, mapped.y, mapped.z),
            model=None,
            collider="box",
            scale=(0.8, 1.2, 1.2),
            shader=lit_with_shadows_shader,
        )
        game.planet.orient_entity(self.entity, SimVec3(mapped.x, mapped.y, mapped.z))
        self.entity.animal_owner = self

        # Visual creation based on kind
        self._build_model(rng)

        # AI brain
        self.brain = CivilianBrain(SimVec3(self.chart_x, 0.0, self.chart_z))
        # Animals move slightly differently than humans
        if self.kind in ("deer", "horse"):
            self.brain.speed = rng.uniform(2.6, 3.8)
        elif self.kind == "dog":
            self.brain.speed = rng.uniform(2.2, 3.2)
        else: # cow, sheep
            self.brain.speed = rng.uniform(1.2, 1.8)

        self._walk_time = 0.0
        self._wander_time = rng.uniform(1.0, 4.0)

    def _build_model(self, rng: Random) -> None:
        """Procedural quadruped anatomy: torso, neck/head, snout/horns, 4 legs, tail."""
        if self.kind == "deer":
            coat = color.rgb32(165, 102, 53)
            snout_col = color.rgb32(230, 210, 185)
            horn_col = color.rgb32(220, 215, 195)
            torso_scale = (0.34, 0.45, 0.95)
            head_scale = (0.24, 0.28, 0.40)
            leg_scale = (0.09, 0.65, 0.09)
            leg_y = -0.32
            has_horns = True
        elif self.kind == "cow":
            coat = rng.choice((
                color.rgb32(40, 40, 40),   # black/white spots
                color.rgb32(185, 125, 80), # brown
                color.rgb32(235, 235, 235),# cream
            ))
            snout_col = color.rgb32(245, 185, 190)
            horn_col = color.rgb32(235, 230, 210)
            torso_scale = (0.55, 0.60, 1.15)
            head_scale = (0.36, 0.40, 0.48)
            leg_scale = (0.15, 0.55, 0.15)
            leg_y = -0.28
            has_horns = True
        elif self.kind == "sheep":
            coat = color.rgb32(235, 235, 230)
            snout_col = color.rgb32(50, 45, 45)
            horn_col = None
            torso_scale = (0.45, 0.50, 0.75)
            head_scale = (0.25, 0.26, 0.32)
            leg_scale = (0.10, 0.42, 0.10)
            leg_y = -0.21
            has_horns = False
        elif self.kind == "horse":
            coat = rng.choice((
                color.rgb32(65, 45, 30),   # dark bay
                color.rgb32(145, 85, 45),  # chestnut
                color.rgb32(220, 220, 220),# grey
                color.rgb32(25, 25, 25),   # black
            ))
            snout_col = color.rgb32(40, 35, 35)
            horn_col = None
            torso_scale = (0.42, 0.58, 1.25)
            head_scale = (0.26, 0.34, 0.55)
            leg_scale = (0.11, 0.75, 0.11)
            leg_y = -0.38
            has_horns = False
        else: # dog
            coat = rng.choice((
                color.rgb32(190, 140, 75), # golden
                color.rgb32(45, 45, 45),   # dark
                color.rgb32(130, 85, 50),  # chocolate
            ))
            snout_col = color.rgb32(30, 30, 30)
            horn_col = None
            torso_scale = (0.28, 0.30, 0.65)
            head_scale = (0.20, 0.22, 0.30)
            leg_scale = (0.08, 0.40, 0.08)
            leg_y = -0.20
            has_horns = False

        # 1. Torso
        self.torso = Entity(
            parent=self.entity,
            model="cube",
            position=(0, 0.4, 0),
            scale=torso_scale,
            color=coat,
            shader=lit_with_shadows_shader,
        )

        # 2. Neck & Head
        self.head_pivot = Entity(parent=self.entity, position=(0, 0.65, torso_scale[2] * 0.45))
        self.head = Entity(
            parent=self.head_pivot,
            model="cube",
            position=(0, 0.15, 0.15),
            scale=head_scale,
            color=coat,
            shader=lit_with_shadows_shader,
        )
        # Snout
        Entity(
            parent=self.head,
            model="cube",
            position=(0, -0.2, 0.6),
            scale=(0.65, 0.55, 0.6),
            color=snout_col,
            shader=lit_with_shadows_shader,
        )
        # Horns / Antlers if applicable
        if has_horns and horn_col:
            for side in (-1, 1):
                Entity(
                    parent=self.head,
                    model="cube",
                    position=(side * 0.35, 0.65, -0.1),
                    scale=(0.12, 0.55, 0.12),
                    rotation=(15, 0, side * 25),
                    color=horn_col,
                    shader=lit_with_shadows_shader,
                )
                if self.kind == "deer":
                    # Extra tines for majestic stag antlers
                    Entity(
                        parent=self.head,
                        model="cube",
                        position=(side * 0.50, 0.85, 0.05),
                        scale=(0.08, 0.30, 0.08),
                        rotation=(-20, 0, side * 40),
                        color=horn_col,
                        shader=lit_with_shadows_shader,
                    )

        # 3. Four Legs
        self.legs = []
        half_w = torso_scale[0] * 0.38
        half_l = torso_scale[2] * 0.38
        leg_positions = (
            (-half_w, half_l, "fl"),
            ( half_w, half_l, "fr"),
            (-half_w, -half_l, "rl"),
            ( half_w, -half_l, "rr"),
        )
        for lx, lz, name in leg_positions:
            pivot = Entity(parent=self.entity, position=(lx, 0.4 + leg_y, lz))
            leg = Entity(
                parent=pivot,
                model="cube",
                position=(0, -leg_scale[1] * 0.5, 0),
                scale=leg_scale,
                color=coat,
                shader=lit_with_shadows_shader,
            )
            # Hoof / paw
            Entity(
                parent=leg,
                model="cube",
                position=(0, -0.5, 0.1),
                scale=(1.1, 0.25, 1.3),
                color=color.rgb32(35, 30, 30),
                shader=lit_with_shadows_shader,
            )
            self.legs.append((pivot, name))

        # 4. Tail
        self.tail = Entity(
            parent=self.entity,
            model="cube",
            position=(0, 0.45, -torso_scale[2] * 0.52),
            scale=(0.08, 0.30, 0.08),
            rotation=(-35, 0, 0),
            color=coat,
            shader=lit_with_shadows_shader,
        )

    def react_to_danger(self, origin: SimVec3) -> None:
        self.brain.react_to_danger(origin, self.random)

    def step(self, dt: float, *, player_chart=None) -> None:
        self._walk_time += dt
        self._wander_time -= dt
        sentry = getattr(self.game, "sentry", None)
        danger = None
        if player_chart is not None:
            sentry_x, sentry_z = player_chart
            dx, dz = self.chart_x - sentry_x, self.chart_z - sentry_z
            threat_dist = 24.0 if self.kind in ("deer", "horse") else 16.0
            if dx * dx + dz * dz < threat_dist * threat_dist:
                danger = SimVec3(sentry_x, 0.0, sentry_z)
        elif sentry is not None:
            sentry_x, sentry_z = self.game.planet.local_coordinates(
                SimVec3(sentry.x, sentry.y, sentry.z)
            )
            dx, dz = self.chart_x - sentry_x, self.chart_z - sentry_z
            # Animals detect the player from farther away and flee faster
            threat_dist = 24.0 if self.kind in ("deer", "horse") else 16.0
            if dx * dx + dz * dz < threat_dist * threat_dist:
                danger = SimVec3(sentry_x, 0.0, sentry_z)

        if self.brain.target is None and self._wander_time <= 0.0:
            wander_radius = 18.0 if self.kind in ("deer", "horse") else 10.0
            self.brain.target = self.brain.position + SimVec3(
                self.random.uniform(-wander_radius, wander_radius),
                0,
                self.random.uniform(-wander_radius, wander_radius),
            )
            self._wander_time = self.random.uniform(3.0, 7.0)

        old_position = self.brain.position
        new_position = self.brain.step(dt, danger=danger, rng=self.random)

        # Repel away from nearby building footprints
        nearby_buildings = getattr(self.game.world, "nearby_buildings", None)
        obstacles = (nearby_buildings(new_position.x, new_position.z)
                     if nearby_buildings is not None
                     else getattr(self.game.world, "buildings", ()))
        for obstacle in obstacles:
            dx, dz = new_position.x - obstacle.chart_x, new_position.z - obstacle.chart_z
            clear_x = abs(obstacle.scale_x) * 0.5 + 0.6
            clear_z = abs(obstacle.scale_z) * 0.5 + 0.6
            if abs(dx) < clear_x and abs(dz) < clear_z:
                if clear_x - abs(dx) < clear_z - abs(dz):
                    new_position.x = obstacle.chart_x + (clear_x if dx >= 0 else -clear_x)
                else:
                    new_position.z = obstacle.chart_z + (clear_z if dz >= 0 else -clear_z)

        self.brain.position = new_position
        self.chart_x, self.chart_z = new_position.x, new_position.z
        mapped = self.game.planet.point_from_local(self.chart_x, self.chart_z, 0.45)
        self.entity.position = Vec3(mapped.x, mapped.y, mapped.z)

        direction = new_position - old_position
        moving = direction.length() > 0.001
        if moving:
            self.game.planet.orient_entity(
                self.entity,
                SimVec3(mapped.x, mapped.y, mapped.z),
                degrees(atan2(direction.x, direction.z)),
            )

        # Quadruped walk gait: diagonal pairs swing together (FL + RR vs FR + RL)
        speed_factor = 14.0 if self.brain.state is CivilianState.FLEE else 7.0
        phase = self._walk_time * speed_factor if moving else 0.0
        swing = sin(phase) * (32.0 if moving else 0.0)

        for pivot, name in self.legs:
            if name in ("fl", "rr"):
                pivot.rotation_x = swing
            else:
                pivot.rotation_x = -swing

        # Head bob and tail wag
        if moving:
            self.head_pivot.rotation_x = sin(self._walk_time * speed_factor * 0.5) * 8.0
            self.tail.rotation_y = sin(self._walk_time * speed_factor * 1.5) * 22.0

