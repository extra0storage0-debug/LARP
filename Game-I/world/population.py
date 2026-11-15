"""Quality-bounded district population plans for the streamed island."""

from __future__ import annotations


_NPC_CAPACITY = {"low": 32, "medium": 56, "high": 88, "ultra": 112}
_TRAFFIC_CAPACITY = {"low": 12, "medium": 24, "high": 40, "ultra": 52}
_NPC_PER_CHUNK = {
    "low": {"downtown": 3, "luxury": 2, "rural": 1, "coastal": 1,
            "forest": 0, "mountain": 0},
    "medium": {"downtown": 6, "luxury": 4, "rural": 3, "coastal": 2,
               "forest": 1, "mountain": 1},
    "high": {"downtown": 10, "luxury": 7, "rural": 4, "coastal": 3,
             "forest": 1, "mountain": 2},
    "ultra": {"downtown": 14, "luxury": 9, "rural": 6, "coastal": 4,
              "forest": 2, "mountain": 2},
}
_TRAFFIC_PER_CHUNK = {
    "low": {"downtown": 1, "luxury": 1, "rural": 0, "coastal": 0,
            "forest": 0, "mountain": 0},
    "medium": {"downtown": 3, "luxury": 2, "rural": 1, "coastal": 1,
               "forest": 0, "mountain": 0},
    "high": {"downtown": 5, "luxury": 3, "rural": 2, "coastal": 2,
             "forest": 0, "mountain": 1},
    "ultra": {"downtown": 7, "luxury": 4, "rural": 3, "coastal": 2,
              "forest": 1, "mountain": 1},
}


def _key(value: str, allowed: dict, default: str) -> str:
    value = str(value).lower()
    return value if value in allowed else default


def civilian_capacity(quality: str, density: str, legacy_limit: int = 8) -> int:
    """Return a conservative global living-NPC cap, retaining the old cap as a multiplier."""
    quality = _key(quality, _NPC_CAPACITY, "low")
    density = _key(density, _NPC_PER_CHUNK, "medium")
    density_cap = {"low": 12, "medium": 32, "high": 56, "ultra": 88}[density]
    legacy_cap = max(1, int(legacy_limit)) * 4
    return min(_NPC_CAPACITY[quality], density_cap, legacy_cap)


def civilians_per_chunk(district: str, density: str) -> int:
    density = _key(density, _NPC_PER_CHUNK, "medium")
    return _NPC_PER_CHUNK[density].get(str(district).lower(), 0)


def traffic_capacity(quality: str, density: str) -> int:
    quality = _key(quality, _TRAFFIC_CAPACITY, "low")
    density = _key(density, _TRAFFIC_PER_CHUNK, "medium")
    density_cap = {"low": 8, "medium": 18, "high": 30, "ultra": 40}[density]
    return min(_TRAFFIC_CAPACITY[quality], density_cap)


def traffic_per_chunk(district: str, density: str) -> int:
    density = _key(density, _TRAFFIC_PER_CHUNK, "medium")
    return _TRAFFIC_PER_CHUNK[density].get(str(district).lower(), 0)
