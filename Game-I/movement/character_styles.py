"""How each character carries themselves and moves. No engine imports: plain numbers the body code reads, from each character's own file."""

from __future__ import annotations

from dataclasses import dataclass

from characters.registry import definitions


@dataclass(frozen=True, slots=True)
class Style:
    stride: float = 1.0       # how far the legs swing
    step: float = 1.0         # how far one step travels, so how quickly the legs turn over
    arm_swing: float = .65    # arms against legs
    run_elbow: float = -78.0  # how bent the arms are at a full run
    walk_elbow: float = -10.0
    land_depth: float = 1.0   # how far the legs give on landing
    idle_sway: float = .8     # slow shift of weight, in degrees
    breath_rate: float = 1.5
    flight_right_x: float = 0.0   # a flyer's right arm, against the reach both start from
    flight_right_z: float = 0.0
    flight_elbow: float = 0.0


STYLES = {item.character_id: Style(**item.movement) for item in definitions()}
STYLES["INVINCIBLE"] = Style(stride=1.05, step=1.0, arm_swing=.75, idle_sway=1.0, breath_rate=1.9, land_depth=.9,
                        flight_right_x=160.0, flight_right_z=-8.0)
DEFAULT_STYLE = Style()


def style_of(name: str) -> Style:
    return STYLES.get(name, DEFAULT_STYLE)
