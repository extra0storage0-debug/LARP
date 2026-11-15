"""Fire and ice in the world: burning and frozen trees, fire patches, ice and scorch marks.

Everything draws from small fixed pools, so no amount of beam or breath use adds entities.
"""

from __future__ import annotations

from ursina import Entity, Vec3, color
from ursina.shaders import unlit_shader

from game.art_style import soft_glow
from movement.flight_physics import Vec3 as SimVec3
from powers.vitals import COLD, HEAT

MAX_BURNING = 12
MAX_FROZEN = 10
MAX_FIRES = 8
MAX_ICE = 10
MAX_SCORCH = 16
BURN_SECONDS = 9.0
BURN_DPS = 14.0
FIRE_SECONDS = 6.0
FIRE_RADIUS = 3.0
FIRE_DPS = 22.0
ICE_SECONDS = 18.0
ICE_RADIUS = 3.5
SCORCH_SECONDS = 25.0
FROZEN_DAMAGE_SCALE = 2.0


def _is_gone(tree) -> bool:
    return tree.is_empty() or getattr(tree, "tree_health", 0.0) <= 0.0


class WorldElements:
    def __init__(self, game) -> None:
        self.game = game
        self.burning: dict = {}
        self.frozen: dict = {}
        self.fires: list[list] = []
        self.ice: list[list] = []
        self.scorches: list[list] = []
        self._flames = [soft_glow(color=color.rgba32(255, 120, 30, 200), visible=False)
                        for _ in range(MAX_BURNING + MAX_FIRES)]
        self._shells = [Entity(model="sphere", color=color.rgba32(170, 225, 255, 120),
                               shader=unlit_shader, transparency=True, collider=None, visible=False,
                               add_to_scene_entities=False) for _ in range(MAX_FROZEN)]
        self._ice_bodies = [self._make_ice() for _ in range(MAX_ICE)]
        self._scorch_marks = [Entity(model="circle", color=color.rgba32(18, 12, 8, 200),
                                     shader=unlit_shader, transparency=True, double_sided=True,
                                     collider=None, visible=False, rotation_x=90,
                                     add_to_scene_entities=False) for _ in range(MAX_SCORCH)]
        self._scorch_cursor = 0

    @staticmethod
    def _make_ice() -> Entity:
        root = Entity(model=None, collider=None, visible=False, add_to_scene_entities=False)
        tint = color.rgb32(175, 225, 248)
        for x, z, height, lean in ((0, 0, 3.0, 0), (.9, .3, 1.9, 18), (-.8, .5, 2.2, -14),
                                   (.2, -.9, 1.6, 10), (-.4, -.6, 1.3, -20)):
            Entity(parent=root, model="cube", position=(x, height * .4, z), rotation=(lean, 45, -lean),
                   scale=(.55, height, .55), color=tint, shader=unlit_shader, collider=None,
                   add_to_scene_entities=False)
        Entity(parent=root, name="ice-floe", model="circle", rotation_x=90, position=(0, .05, 0),
               scale=7.0, color=color.rgba32(205, 238, 250, 215), shader=unlit_shader,
               transparency=True, double_sided=True, collider=None, add_to_scene_entities=False)
        return root

    # -- starting and stopping -------------------------------------------
    def ignite_tree(self, tree) -> bool:
        if _is_gone(tree):  # the same blow that brought the heat can have felled it
            return False
        if tree in self.frozen:  # heat melts the ice first
            self._thaw(tree)
            return False
        if tree in self.burning:
            self.burning[tree][0] = BURN_SECONDS
            return True
        if len(self.burning) >= MAX_BURNING or not self._flames:
            return False
        flame = self._flames.pop()
        flame.position = Vec3(tree.x, tree.y + tree.scale_y * .35, tree.z)
        flame.scale = (2.8, 4.4, 2.8)
        flame.visible = True
        self.burning[tree] = [BURN_SECONDS, flame]
        return True

    def extinguish_tree(self, tree) -> None:
        entry = self.burning.pop(tree, None)
        if entry is not None:
            entry[1].visible = False
            self._flames.append(entry[1])

    def freeze_tree(self, tree, seconds: float) -> bool:
        self.extinguish_tree(tree)
        if _is_gone(tree):
            return False
        if tree in self.frozen:
            self.frozen[tree][0] = max(self.frozen[tree][0], seconds)
            return True
        if len(self.frozen) >= MAX_FROZEN or not self._shells:
            return False
        shell = self._shells.pop()
        shell.position = Vec3(tree.x, tree.y + tree.scale_y * .15, tree.z)
        shell.scale = (4.2, tree.scale_y * 1.7, 4.2)
        shell.visible = True
        self.frozen[tree] = [seconds, shell]
        return True

    def _thaw(self, tree) -> None:
        entry = self.frozen.pop(tree, None)
        if entry is not None:
            entry[1].visible = False
            self._shells.append(entry[1])

    def damage_scale_for(self, tree, kind: str) -> float:
        """Frozen trees shatter easily under physical force."""
        return FROZEN_DAMAGE_SCALE if tree in self.frozen and kind != HEAT else 1.0

    def start_fire(self, point: SimVec3, source) -> bool:
        for fire in self.fires:
            if (fire[0] - point).length() < FIRE_RADIUS:
                fire[1] = FIRE_SECONDS
                return True
        if len(self.fires) >= MAX_FIRES or not self._flames:
            return False
        flame = self._flames.pop()
        flame.position = Vec3(point.x, point.y + .8, point.z)
        flame.scale = (FIRE_RADIUS, 2.6, FIRE_RADIUS)
        flame.visible = True
        self.fires.append([point, FIRE_SECONDS, flame, source])
        return True

    def extinguish(self, point: SimVec3, radius: float) -> int:
        """Put out fires and burning trees around a point; returns how many."""
        count = 0
        for fire in tuple(self.fires):
            if (fire[0] - point).length() <= radius:
                self._end_fire(fire)
                count += 1
        for tree in tuple(self.burning):
            if _is_gone(tree):
                continue
            dx, dz = tree.x - point.x, tree.z - point.z
            if dx * dx + dz * dz <= radius * radius:
                self.extinguish_tree(tree)
                count += 1
        return count

    def _end_fire(self, fire) -> None:
        fire[2].visible = False
        self._flames.append(fire[2])
        self.fires.remove(fire)

    def add_ice(self, point: SimVec3, *, on_water: bool, source) -> None:
        for formation in self.ice:
            if (formation[0] - point).length() < ICE_RADIUS:
                formation[1] = ICE_SECONDS
                return
        if not self._ice_bodies:
            oldest = self.ice.pop(0)
            oldest[2].visible = False
            self._ice_bodies.append(oldest[2])
        body = self._ice_bodies.pop()
        body.position = Vec3(point.x, point.y, point.z)
        body.visible = True
        self.ice.append([point, ICE_SECONDS, body, source, on_water])

    def add_scorch(self, point: SimVec3, radius: float = 1.6) -> None:
        mark = self._scorch_marks[self._scorch_cursor % MAX_SCORCH]
        self._scorch_cursor += 1
        ground = self.game.world.height_at(point.x, point.z)
        mark.position = Vec3(point.x, ground + .08, point.z)
        mark.scale = radius * 2.0
        mark.color = color.rgba32(18, 12, 8, 200)
        mark.visible = True
        for entry in self.scorches:
            if entry[0] is mark:
                entry[1] = SCORCH_SECONDS
                return
        self.scorches.append([mark, SCORCH_SECONDS])

    def heat_sources(self) -> list[SimVec3]:
        """Fires and burning trees, for infrared."""
        points = [fire[0] for fire in self.fires]
        points.extend(SimVec3(tree.x, tree.y, tree.z) for tree in self.burning if not _is_gone(tree))
        return points

    # -- per frame -------------------------------------------------------
    def step(self, dt: float) -> None:
        if not (self.burning or self.frozen or self.fires or self.ice or self.scorches):
            return
        world = self.game.world
        combat = self.game.combat
        for tree in tuple(self.burning):
            if _is_gone(tree):
                self.extinguish_tree(tree)
                continue
            entry = self.burning[tree]
            entry[0] -= dt
            world.damage_tree(tree, BURN_DPS * dt, SimVec3(1.0, 0.0, 0.0))
            if _is_gone(tree) or entry[0] <= 0.0:
                self.extinguish_tree(tree)
        for tree in tuple(self.frozen):
            entry = self.frozen[tree]
            entry[0] -= dt
            if _is_gone(tree) or entry[0] <= 0.0:
                self._thaw(tree)
        for fire in tuple(self.fires):
            fire[1] -= dt
            if fire[1] <= 0.0:
                self._end_fire(fire)
                continue
            for character in combat.in_world:
                if character is not fire[3] and combat.hostile(fire[3], character) \
                        and (SimVec3(character.x, character.y, character.z) - fire[0]).length() < FIRE_RADIUS:
                    combat.hit_character(fire[3], character, FIRE_DPS * dt, HEAT)
        for formation in tuple(self.ice):
            formation[1] -= dt
            if formation[1] <= 0.0:
                formation[2].visible = False
                self._ice_bodies.append(formation[2])
                self.ice.remove(formation)
                continue
            for character in combat.in_world:
                if character is not formation[3] and combat.hostile(formation[3], character) \
                        and (SimVec3(character.x, character.y, character.z) - formation[0]).length() < ICE_RADIUS:
                    character.vitals.add_status("slowed", .3)
        for entry in tuple(self.scorches):
            entry[1] -= dt
            if entry[1] <= 0.0:
                entry[0].visible = False
                self.scorches.remove(entry)

    def clear(self) -> None:
        for tree in tuple(self.burning):
            self.extinguish_tree(tree)
        for tree in tuple(self.frozen):
            self._thaw(tree)
        for fire in tuple(self.fires):
            self._end_fire(fire)
        for formation in tuple(self.ice):
            formation[2].visible = False
            self._ice_bodies.append(formation[2])
        self.ice.clear()
        for entry in self.scorches:
            entry[0].visible = False
        self.scorches.clear()


COLD_KIND = COLD
