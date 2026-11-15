"""Pooled power visuals. Everything is created once and capped, so use adds no entities."""

from __future__ import annotations

from math import cos, pi, sin

from panda3d.core import TransparencyAttrib
from ursina import Entity, Vec3, color
from ursina.shaders import unlit_shader

from game.art_style import soft_glow
from movement.flight_physics import Vec3 as SimVec3

PUFF_COUNT = {"low": 18, "medium": 28, "high": 40, "ultra": 56}
STREAK_SECONDS = .05
STREAK_METRES = 12.0


def _flat(model="cube", **options) -> Entity:
    return Entity(model=model, shader=unlit_shader, collider=None, unlit=True,
                  add_to_scene_entities=False, **options)


def _vec(point) -> Vec3:
    return Vec3(float(point.x), float(point.y), float(point.z))


class BeamVisual:
    """Two glowing eye beams, or one beam from a single point, and an impact flare."""

    def __init__(self) -> None:
        self.cores = [_flat(color=color.white, visible=False) for _ in range(2)]
        self.glows = [_flat(transparency=True, visible=False) for _ in range(2)]
        for glow in self.glows:
            glow.setDepthWrite(False)
        self.fire = color.rgba32(255, 150, 60, 220)
        self.flare = soft_glow(color=self.fire, visible=False)

    def show(self, starts, end, width: float, core, glow, flare=None) -> None:
        target = _vec(end)
        for index, (core_beam, glow_beam) in enumerate(zip(self.cores, self.glows)):
            if index >= len(starts):
                core_beam.visible = glow_beam.visible = False
                continue
            start = _vec(starts[index])
            middle, length = (start + target) * .5, max(.1, (target - start).length())
            for beam, scale, tint in ((core_beam, width * .45, core), (glow_beam, width * 1.5, glow)):
                beam.position = middle
                beam.look_at(target)
                beam.scale = (scale, scale, length)
                beam.color = tint
                beam.visible = True
        self.flare.color = self.fire if flare is None else flare
        self.flare.position = target
        self.flare.scale = max(.6, width * 7.0)
        self.flare.visible = True

    def hide(self) -> None:
        for entity in (*self.cores, *self.glows, self.flare):
            entity.visible = False


class LockReticle:
    """Four gold corner brackets around the manually locked target, drawn over everything."""

    ARM, THICK = .3, .05

    def __init__(self) -> None:
        self.root = Entity(model=None, collider=None, add_to_scene_entities=False, visible=False)
        self.root.setBillboardPointEye()
        self.root.setLightOff()
        tint = color.rgb32(255, 205, 60)
        for x_sign in (-1, 1):
            for y_sign in (-1, 1):
                for wide, tall, x, y in ((self.ARM, self.THICK, .5 - self.ARM * .5, .5),
                                         (self.THICK, self.ARM, .5, .5 - self.ARM * .5)):
                    part = _flat(model="quad", parent=self.root, color=tint, scale=(wide, tall),
                                 position=(x * x_sign, y * y_sign, 0))
                    part.setBin("fixed", 39)
                    part.setDepthTest(False)
                    part.setDepthWrite(False)

    def show(self, point, metres: float) -> None:
        self.root.position = _vec(point)
        self.root.scale = max(3.6, metres * .05)
        self.root.visible = True

    def hide(self) -> None:
        self.root.visible = False

    @property
    def showing(self) -> bool:
        return self.root.visible


class SpeedStreak:
    """A stretched bar of light behind something moving too fast to see, borrowed from the beam pool."""

    def __init__(self, combat, tint) -> None:
        self.combat = combat
        self.core = color.rgba32(255, 255, 255, 200)
        self.glow = color.rgba32(*tint)
        self.visual = None

    def show(self, end, velocity, width: float = .4) -> None:
        """Behind ``end``, against ``velocity``, and short enough not to reach through the camera."""
        if self.visual is None:
            self.visual = self.combat.acquire_beam()
        if self.visual is not None:
            speed = velocity.length()
            length = min(STREAK_METRES, speed * STREAK_SECONDS)
            start = end - velocity * (length / max(speed, 1e-3))
            self.visual.show((start,), end, width, self.core, self.glow)
            self.visual.flare.visible = False

    def release(self) -> None:
        if self.visual is not None:
            self.combat.release_beam(self.visual)
            self.visual = None


class PuffPool:
    """Soft particles for breath, frost, smoke and radiation."""

    def __init__(self, quality: str) -> None:
        self.free = [soft_glow(visible=False) for _ in range(PUFF_COUNT.get(quality, 18))]
        self.live: list[list] = []

    def emit(self, position, velocity, tint, *, size: float = 1.0, grow: float = 2.5,
             life: float = .7) -> None:
        if not self.free:
            return
        entity = self.free.pop()
        entity.position = _vec(position)
        entity.scale = size
        entity.color = color.rgba32(*tint)
        entity.visible = True
        # entity, velocity, age, life, size, grow, tint
        self.live.append([entity, velocity, 0.0, life, size, grow, tint])

    def step(self, dt: float) -> None:
        for puff in tuple(self.live):
            entity, velocity, age, life, size, grow, tint = puff
            age += dt
            puff[2] = age
            fade = 1.0 - age / life
            if fade <= 0.0:
                entity.visible = False
                self.live.remove(puff)
                self.free.append(entity)
                continue
            entity.position += Vec3(velocity.x * dt, velocity.y * dt, velocity.z * dt)
            entity.scale = size + grow * (1.0 - fade)
            entity.color = color.rgba32(tint[0], tint[1], tint[2], int(tint[3] * fade))


class Bolt:
    """One glowing projectile body; the shield uses its own model on the character."""

    def __init__(self) -> None:
        self.core = soft_glow(visible=False)
        self.solid = _flat(model="sphere", visible=False)

    def show(self, position, size: float, tint) -> None:
        point = _vec(position)
        self.core.position = point
        self.solid.position = point
        self.core.scale = size * 2.6
        self.solid.scale = size
        self.core.color = color.rgba32(*tint)
        self.solid.color = color.rgb32(255, 248, 215)
        self.core.visible = self.solid.visible = True

    def hide(self) -> None:
        self.core.visible = self.solid.visible = False


class Bubble:
    """A translucent sphere around a character: energy shield, ice shell or Void aura."""

    def __init__(self, parent, tint, center=1.4) -> None:
        self.entity = soft_glow(parent=parent, position=(0, center, 0), color=color.rgba32(*tint),
                                visible=False)

    def show(self, scale, tint=None) -> None:
        self.entity.scale = scale
        if tint is not None:
            self.entity.color = color.rgba32(*tint)
        self.entity.visible = True

    def hide(self) -> None:
        self.entity.visible = False


class TendrilVisual:
    """A dark jointed line from one point to another, wavering along its length."""

    SEGMENTS = 5

    def __init__(self) -> None:
        tint = color.rgb32(30, 12, 52)
        self.segments = [_flat(color=tint, visible=False) for _ in range(self.SEGMENTS)]

    def show(self, start, end, phase: float, thickness: float = .22) -> None:
        a, b = _vec(start), _vec(end)
        previous = a
        offset = b - a
        length = max(.1, offset.length())
        side = Vec3(offset.z, 0, -offset.x).normalized() if abs(offset.x) + abs(offset.z) > .01 \
            else Vec3(1, 0, 0)
        for index, segment in enumerate(self.segments):
            fraction = (index + 1) / self.SEGMENTS
            wave = 0.0 if index == self.SEGMENTS - 1 else sin(phase * 7.0 + index * 1.8) * .05 * length
            following = a + offset * fraction + side * wave + Vec3(0, cos(phase * 5.0 + index) * .03 * length, 0)
            segment.position = (previous + following) * .5
            segment.look_at(following)
            segment.scale = (thickness, thickness, max(.1, (following - previous).length()))
            segment.visible = True
            previous = following

    def hide(self) -> None:
        for segment in self.segments:
            segment.visible = False


class MarkerPool:
    """Bright through-wall diamonds for X-ray, infrared and Enhanced Senses."""

    def __init__(self, count: int = 8) -> None:
        self.markers = []
        for _ in range(count):
            marker = _flat(model="quad", visible=False, transparency=True)
            marker.setBillboardPointEye()
            marker.setBin("fixed", 40)
            marker.setDepthTest(False)
            marker.setDepthWrite(False)
            marker.setLightOff()
            self.markers.append(marker)
        self.showing = 0

    def show(self, points, tint, scale_for) -> None:
        self.showing = min(len(points), len(self.markers))
        for index, marker in enumerate(self.markers):
            if index < self.showing:
                marker.position = _vec(points[index])
                marker.scale = scale_for(points[index])
                marker.color = color.rgba32(*tint)
                marker.visible = True
            else:
                marker.visible = False

    def hide(self) -> None:
        self.showing = 0
        for marker in self.markers:
            marker.visible = False


MAX_CRACK_LENGTH, MAX_CRACK_WIDTH = 16.0, .42


class GroundCracks:
    """Radial cracks for heavy ground hits; recycled so there is never more than a few."""

    COUNT = 6
    ARMS = 7

    def __init__(self) -> None:
        self.sets = []
        for _ in range(self.COUNT):
            arms = [_flat(color=color.rgba32(30, 24, 20, 165), transparency=True, visible=False) for _ in range(self.ARMS)]
            self.sets.append(arms)
        self.cursor = 0

    def place(self, world, center, radius: float, seed: float = 0.0) -> None:
        arms = self.sets[self.cursor % self.COUNT]
        self.cursor += 1
        for index, arm in enumerate(arms):
            angle = 2.0 * pi * index / self.ARMS + seed + sin(index * 3.1 + seed) * .4
            length = min(MAX_CRACK_LENGTH, radius * (.55 + .35 * abs(sin(index * 1.7 + seed))))
            x = center.x + sin(angle) * length * .5
            z = center.z + cos(angle) * length * .5
            arm.position = Vec3(x, world.height_at(x, z) + .1, z)
            arm.rotation = (0, angle * 57.2958, 0)
            arm.scale = (min(MAX_CRACK_WIDTH, max(.1, radius * .02)), .05, length)  # cracks, however large the blast: not roads
            arm.visible = True

    def hide_all(self) -> None:
        for arms in self.sets:
            for arm in arms:
                arm.visible = False


def make_transparent(node) -> None:
    node.setTransparency(TransparencyAttrib.MAlpha)


__all__ = ["BeamVisual", "Bolt", "Bubble", "GroundCracks", "LockReticle", "MarkerPool", "PuffPool",
           "SimVec3", "SpeedStreak", "TendrilVisual", "make_transparent"]
