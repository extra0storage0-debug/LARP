"""Small deterministic helpers shared by destruction and collision code."""

from __future__ import annotations

from dataclasses import dataclass

from math import exp


def crater_height_delta(distance: float, radius: float, depth: float) -> float:
    """Return a smooth crater bowl plus a compact ejecta rim profile."""
    radius = max(.01, float(radius))
    depth = max(0.0, float(depth))
    radial = max(0.0, float(distance)) / radius
    if radial >= 1.25:
        return 0.0
    bowl = -depth * (1.0 - min(1.0, radial) ** 2) ** 2 if radial < 1.0 else 0.0
    rim = depth * .24 * exp(-((radial - .86) / .11) ** 2)
    fade = 1.0 if radial <= 1.0 else max(0.0, (1.25 - radial) / .25)
    return bowl + rim * fade


@dataclass(slots=True)
class DestructionScales:
    """Multipliers from the Destruction and Visual settings; 1.0 is the original."""
    radius: float = 1.0
    damage: float = 1.0
    force: float = 1.0
    crater: float = 1.0
    terrain: float = 1.0
    tree: float = 1.0
    building: float = 1.0
    camera_shake: float = 1.0
    debris_speed: float = 1.0
    chain: float = 1.0
    effect_duration: float = 1.0
    visual: float = 1.0
    smoke: float = 1.0
    explosion_sound: float = 1.0

    @classmethod
    def from_tuning(cls, tuning, shared: "DestructionScales | None" = None) -> "DestructionScales":
        """Read a profile; an enemy's scales keep the player's visual preferences."""
        fraction = tuning.fraction
        base = shared or cls()
        return cls(fraction("explosion_radius_pct"), fraction("explosion_damage_pct"),
                   fraction("explosion_force_pct"), fraction("crater_size_pct"),
                   fraction("terrain_damage_pct"), fraction("tree_damage_pct"),
                   fraction("building_damage_pct"), fraction("destruction_camera_shake_pct"),
                   fraction("debris_speed_pct", base.debris_speed),
                   fraction("chain_reaction_pct", base.chain),
                   fraction("destruction_effect_pct", base.effect_duration),
                   fraction("explosion_visual_pct", base.visual),
                   fraction("smoke_density_pct", base.smoke),
                   fraction("explosion_sound_pct", base.explosion_sound))


def sweep_point_aabb(start, end, minimum, maximum):
    """Slab-test a segment against an AABB; return (t, hit normal) or None."""
    direction = tuple(float(end[i]) - float(start[i]) for i in range(3))
    t_enter, t_exit = 0.0, 1.0
    hit_axis, hit_sign = -1, 0.0
    for axis in range(3):
        origin = float(start[axis])
        delta = direction[axis]
        low, high = float(minimum[axis]), float(maximum[axis])
        if abs(delta) < 1e-9:
            if origin < low or origin > high:
                return None
            continue
        first, second = (low - origin) / delta, (high - origin) / delta
        sign = -1.0
        if first > second:
            first, second = second, first
            sign = 1.0
        if first > t_enter:
            t_enter, hit_axis, hit_sign = first, axis, sign
        t_exit = min(t_exit, second)
        if t_enter > t_exit:
            return None
    if t_exit < 0.0 or t_enter > 1.0:
        return None
    normal = [0.0, 0.0, 0.0]
    if hit_axis >= 0:
        normal[hit_axis] = hit_sign
    else:
        # Segment starts inside; use the face opposing its dominant motion.
        axis = max(range(3), key=lambda i: abs(direction[i]))
        normal[axis] = -1.0 if direction[axis] >= 0.0 else 1.0
    return max(0.0, t_enter), tuple(normal)


def superhuman_impact_damage(speed_mps: float) -> float:
    """Nonlinear structural damage from relative normal impact velocity."""
    excess = max(0.0, float(speed_mps) - 12.0)
    return min(12_000.0, excess ** 1.7 * .85)
