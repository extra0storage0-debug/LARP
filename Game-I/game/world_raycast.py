"""Deterministic world-space raycasts for Ursina 8.3."""

from panda3d.core import LQuaternionf
from ursina import raycast, scene
from ursina.raycast import _raycaster


def world_raycast(origin, direction, *, distance=9999, ignore=None,
                  traverse_target=scene):
    """Cast from world coordinates without inheriting the prior ray's rotation.

    Ursina's raycast helper reuses one Entity. Its 180-degree fallback can retain
    a stale horizontal axis when the camera obstruction ray and aim ray oppose
    each other. Resetting the reusable Entity to world identity makes the helper
    deterministic for all camera headings while preserving Ursina's hit data.
    """
    _raycaster.setQuat(LQuaternionf.identQuat())
    return raycast(origin, direction, distance=distance,
                   traverse_target=traverse_target, ignore=ignore)
