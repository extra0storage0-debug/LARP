"""Ray and cone queries against characters, objects, trees and terrain, without the renderer."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sqrt

from movement.flight_physics import Vec3 as SimVec3
from world.destruction_math import sweep_point_aabb

CHARACTER_RADIUS = 1.5
CHARACTER_CENTER = 1.4
TERRAIN_STEPS = 40
MAX_TERRAIN_STEP = 30.0
TERRAIN_CEILING = 700.0  # above every hill, so a rising ray can stop searching
MAX_TRACE = 15000.0      # corner to corner of the island; nothing is further away


@dataclass(slots=True)
class Hit:
    kind: str                # character, object, tree, terrain, water or none
    point: SimVec3
    distance: float
    target: object = None


def center_of(character) -> SimVec3:
    return SimVec3(character.x, character.y + CHARACTER_CENTER, character.z)


def object_bounds(obj, padding: float = 0.0):
    half = (abs(obj.scale_x) * .5 + padding, abs(obj.scale_y) * .5 + padding,
            abs(obj.scale_z) * .5 + padding)
    return ((obj.x - half[0], obj.y - half[1], obj.z - half[2]),
            (obj.x + half[0], obj.y + half[1], obj.z + half[2]))


def _ray_sphere(origin: SimVec3, direction: SimVec3, center: SimVec3, radius: float,
                limit: float) -> float | None:
    offset = center - origin
    along = offset.x * direction.x + offset.y * direction.y + offset.z * direction.z
    if along < -radius or along > limit + radius:
        return None
    miss_sq = offset.x ** 2 + offset.y ** 2 + offset.z ** 2 - along * along
    if miss_sq > radius * radius:
        return None
    return max(0.0, along - sqrt(radius * radius - miss_sq))


def chunks_along(world, start: SimVec3, end: SimVec3):
    """Each chunk key the segment touches, and its neighbours when the ray is short."""
    size = world.CHUNK_SIZE
    length = (end - start).length()
    steps = max(1, int(length / (size * .5)) + 1)
    seen = set()
    for index in range(steps + 1):
        fraction = index / steps
        key = (int((start.x + (end.x - start.x) * fraction) // size),
               int((start.z + (end.z - start.z) * fraction) // size))
        if key not in seen:
            seen.add(key)
            yield key


def terrain_hit(world, origin: SimVec3, direction: SimVec3, limit: float) -> float | None:
    """March the height field, then bisect the crossing to about 5 cm."""
    previous = 0.0
    if origin.y <= world.height_at(origin.x, origin.z):
        return 0.0
    step = max(1.0, min(MAX_TERRAIN_STEP, limit / TERRAIN_STEPS))
    distance = 0.0
    while distance < limit:
        distance = min(limit, distance + step)
        if direction.y >= 0.0 and origin.y + direction.y * distance > TERRAIN_CEILING:
            return None
        x, y, z = (origin.x + direction.x * distance, origin.y + direction.y * distance,
                   origin.z + direction.z * distance)
        if y <= world.height_at(x, z):
            low, high = previous, distance
            for _ in range(8):
                middle = (low + high) * .5
                if origin.y + direction.y * middle <= world.height_at(
                        origin.x + direction.x * middle, origin.z + direction.z * middle):
                    high = middle
                else:
                    low = middle
            return high
        previous = distance
    return None


def trace(game, origin: SimVec3, direction: SimVec3, limit: float, *, ignore=(),
          radius: float = 0.0, characters=None, trees: bool = True, objects: bool = True,
          terrain: bool = True) -> Hit:
    """The nearest thing along a ray, within ``limit`` metres."""
    world = game.world
    direction = direction.normalized()
    limit = min(limit, MAX_TRACE)
    end = origin + direction * limit
    best = Hit("none", end, limit)
    roster = characters if characters is not None else game.combat.in_world
    for character in roster:
        if character in ignore:
            continue
        distance = _ray_sphere(origin, direction, center_of(character),
                               CHARACTER_RADIUS + radius, best.distance)
        if distance is not None and distance < best.distance:
            best = Hit("character", origin + direction * distance, distance, character)
    a, b = (origin.x, origin.y, origin.z), (end.x, end.y, end.z)
    keys = tuple(chunks_along(world, origin, end))
    if objects:
        for key in keys:
            for obj in world._objects_by_chunk.get(key, ()):
                if obj in ignore or not obj.enabled or obj.held or obj.health.broken:
                    continue
                low, high = object_bounds(obj, radius)
                found = sweep_point_aabb(a, b, low, high)
                if found is not None and found[0] * limit < best.distance:
                    best = Hit("object", origin + direction * (found[0] * limit),
                               found[0] * limit, obj)
    if trees:
        index = game.teams.trees
        for key in keys:
            for bounds in index.chunk_trees(key):
                if bounds[6] in ignore:
                    continue
                found = sweep_point_aabb(a, b, bounds[:3], bounds[3:6])
                if found is not None and found[0] * limit < best.distance:
                    best = Hit("tree", origin + direction * (found[0] * limit),
                               found[0] * limit, bounds[6])
    if terrain:
        distance = terrain_hit(world, origin, direction, best.distance)
        if distance is not None:
            point = origin + direction * distance
            kind = "water" if world.planet.is_ocean(point) else "terrain"
            best = Hit(kind, point, distance)
    return best


def in_cone(origin: SimVec3, direction: SimVec3, point: SimVec3, reach: float,
            half_angle_degrees: float) -> bool:
    """Whether a point lies inside a cone; ``direction`` must be normalised."""
    offset = point - origin
    distance = offset.length()
    if distance > reach:
        return False
    if distance < 1.5:
        return True
    along = (offset.x * direction.x + offset.y * direction.y + offset.z * direction.z) / distance
    return along >= cos(radians(half_angle_degrees))


def trees_in_radius(game, origin: SimVec3, radius: float):
    world = game.world
    size = world.CHUNK_SIZE
    span = int(radius // size) + 1
    cx, cz = int(origin.x // size), int(origin.z // size)
    for ix in range(cx - span, cx + span + 1):
        for iz in range(cz - span, cz + span + 1):
            for bounds in game.teams.trees.chunk_trees((ix, iz)):
                tree = bounds[6]
                dx, dz = tree.x - origin.x, tree.z - origin.z
                if dx * dx + dz * dz <= radius * radius:
                    yield tree


def objects_in_radius(game, origin: SimVec3, radius: float):
    world = game.world
    span = int(radius // world.CHUNK_SIZE) + 1
    for obj in world._nearby_objects(origin.x, origin.z, span):
        if not obj.enabled or obj.health.broken:
            continue
        dx, dy, dz = obj.x - origin.x, obj.y - origin.y, obj.z - origin.z
        if dx * dx + dy * dy + dz * dz <= radius * radius:
            yield obj


def line_blocked_by_zinc(game, start: SimVec3, end: SimVec3) -> bool:
    """True when zinc lies between two points, which Homelander's X-ray cannot see through."""
    a, b = (start.x, start.y, start.z), (end.x, end.y, end.z)
    for key in chunks_along(game.world, start, end):
        for obj in game.world._objects_by_chunk.get(key, ()):
            if getattr(obj, "zinc", False) and not obj.health.broken:
                low, high = object_bounds(obj)
                if sweep_point_aabb(a, b, low, high) is not None:
                    return True
    return False
