"""A small set of destructible structures, vehicles and boulders near the island's centre.

The destruction spec needs real targets, and the natural island had none. These are few,
fixed and persistent: damage is kept in the same save as trees and craters.
"""

from __future__ import annotations

from math import cos, radians, sin

from ursina import Entity, Text, color, destroy

from movement.flight_physics import Vec3 as SimVec3
from world.buildings import Building
from world.interactive_objects import DestructibleEntity

# kind, distance from the island centre, bearing in degrees, and its dimensions.
SITES = (
    ("building", 135, 15, (16, 22, 14)), ("building", 170, 52, (22, 15, 16)),
    ("building", 150, 200, (14, 30, 14)), ("building", 190, 250, (20, 18, 20)),
    ("building", 240, 120, (18, 26, 18)),
    ("zinc", 120, 300, (14, 9, 14)),
    ("vehicle", 95, 30, (2.2, 1.5, 4.6)), ("vehicle", 112, 60, (2.2, 1.5, 4.6)),
    ("vehicle", 100, 165, (2.4, 2.2, 6.2)), ("vehicle", 118, 215, (2.2, 1.5, 4.6)),
    ("vehicle", 92, 265, (2.2, 1.5, 4.6)), ("vehicle", 130, 330, (2.4, 2.2, 6.2)),
    ("boulder", 80, 90, (3.2, 2.4, 3.0)), ("boulder", 86, 140, (2.2, 1.8, 2.4)),
    ("boulder", 90, 190, (4.2, 3.2, 4.0)), ("boulder", 84, 320, (2.8, 2.0, 2.6)),
)
BUILDING_TINTS = (color.rgb32(172, 164, 148), color.rgb32(140, 150, 160), color.rgb32(176, 150, 128),
                  color.rgb32(120, 128, 136), color.rgb32(160, 156, 142))
VEHICLE_TINTS = (color.rgb32(170, 52, 44), color.rgb32(44, 86, 150), color.rgb32(210, 190, 70),
                 color.rgb32(70, 110, 74), color.rgb32(188, 188, 192), color.rgb32(48, 50, 56))
ZINC_TINT = color.rgb32(132, 146, 158)
ROCK_TINT = color.rgb32(116, 112, 104)


class Vehicle(DestructibleEntity):
    """A parked vehicle: heavy enough to throw, and it explodes when it finally breaks."""

    liftable = True
    explosive = True

    def __init__(self, game, position, size, tint) -> None:
        super().__init__(game, position, size, tint, 150.0, "parked-vehicle")
        self.display_name = "Vehicle"
        self.mass_tonnes = 2.0 if size[2] < 5.0 else 8.0
        self.debris_tint = tint
        Entity(parent=self, model="cube", position=(0, .62, -.08), scale=(.86, .55, .52),
               color=color.rgb32(36, 44, 54), collider=None)
        for x in (-.52, .52):
            for z in (-.32, .32):
                Entity(parent=self, model="cube", position=(x, -.42, z), scale=(.12, .42, .2),
                       color=color.rgb32(18, 18, 20), collider=None)


class Boulder(DestructibleEntity):
    liftable = True

    def __init__(self, game, position, size) -> None:
        super().__init__(game, position, size, ROCK_TINT, 320.0, "boulder")
        self.display_name = "Boulder"
        self.model = "sphere"
        self.collider = "box"
        self.mass_tonnes = abs(size[0] * size[1] * size[2]) * .9
        self.debris_tint = ROCK_TINT


class Landmarks:
    def __init__(self, game) -> None:
        self.game = game
        self.items: list = []
        self.build()

    def build(self) -> None:
        for index, (kind, distance, bearing, size) in enumerate(SITES):
            self._place(index, kind, distance, bearing, size)

    def _place(self, index: int, kind: str, distance: float, bearing: float, size) -> None:
        game, world = self.game, self.game.world
        identifier = f"landmark:{index}:{kind}"
        x, z = sin(radians(bearing)) * distance, cos(radians(bearing)) * distance
        ground = world.height_at(x, z)
        state = world.object_states.get(identifier)
        if state and state.get("destroyed"):
            rubble = Entity(name="landmark-rubble", model="cube", position=(x, ground + .2, z),
                            scale=(max(1.2, size[0] * .5), .4, max(1.2, size[2] * .5)),
                            color=color.rgb32(104, 101, 94), collider=None)
            self.items.append(rubble)
            return
        if kind in ("building", "zinc"):
            tint = ZINC_TINT if kind == "zinc" else BUILDING_TINTS[index % len(BUILDING_TINTS)]
            item = Building(game, (x, ground + size[1] * .5, z), size, tint, 2026 + index)
            item.display_name = "Zinc Vault" if kind == "zinc" else "Building"
            item.chunk_key = (int(x // world.CHUNK_SIZE), int(z // world.CHUNK_SIZE))
            world.buildings.append(item)
            world._buildings_by_chunk.setdefault(item.chunk_key, []).append(item)
            if kind == "zinc":
                item.zinc = True
                item.health.maximum_health *= 3.0
                item.health.health = item.health.maximum_health
        elif kind == "vehicle":
            tint = VEHICLE_TINTS[index % len(VEHICLE_TINTS)]
            item = Vehicle(game, (x, ground + size[1] * .5 + .15, z), size, tint)
            item.rotation_y = bearing * 1.7
        else:
            item = Boulder(game, (x, ground + size[1] * .35, z), size)
            item.rotation_y = bearing
        item.persistent_id = identifier
        if state:
            item.health.health = max(1.0, min(item.health.maximum_health, float(state.get(
                "health", item.health.maximum_health))))
            item._update_damage_appearance()
        self.items.append(item)

    def restore_all(self) -> None:
        """Rebuild every landmark in its original place: Pause > Restore Landmarks."""
        world = self.game.world
        for item in self.items:
            if isinstance(item, DestructibleEntity):
                world.remove_object(item)
            world._destroy_entity_tree(item)
        self.items.clear()
        for index, (kind, _distance, _bearing, _size) in enumerate(SITES):
            world.object_states.pop(f"landmark:{index}:{kind}", None)
        world._damage_state_dirty = True
        world.save_damage_state()
        self.build()


__all__ = ["Boulder", "Landmarks", "SITES", "SimVec3", "Text", "Vehicle", "cos", "destroy"]
