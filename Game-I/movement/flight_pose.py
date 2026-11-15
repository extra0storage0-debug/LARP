"""Which flying pose a body should be in, from how it is really moving. No engine imports.

Reaching: arms ahead of the body, for flying forward. Hands on hips: for hovering, and for flying backward
or purely sideways. Rising and sinking on Space and Ctrl each have a controlled pose of their own. The two
thresholds differ so that a speed or direction sitting right on a limit cannot make the pose flicker.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

from movement.flight_physics import Vec3

REACHING, HANDS_ON_HIPS, ASCENDING, DESCENDING = "reaching", "hands_on_hips", "ascending", "descending"
VERTICAL_SPEED = 1.0                        # m/s up or down before a body takes the pose for it
ENTER_SPEED, LEAVE_SPEED = 7.0, 3.0
ENTER_AHEAD, STAY_AHEAD = .2, -.1           # share of the speed going the way the body faces
ENTER_VERTICAL, STAY_VERTICAL = .7, .6      # share of the speed going straight up or down
BLEND_RATE = 9.0                            # per second


@dataclass(frozen=True, slots=True)
class Pose:
    """Joint angles in degrees, written for the left side; the right side mirrors the z angles."""

    shoulder_x: float
    shoulder_z: float
    elbow_x: float
    elbow_z: float
    left_leg_x: float
    right_leg_x: float


POSES = {
    # The body lies along its direction of travel, so overhead is ahead: arms reach past the head
    # and a little apart, elbows barely bent, legs trailing behind.
    REACHING: Pose(shoulder_x=-168.0, shoulder_z=-5.0, elbow_x=-14.0, elbow_z=0.0,
                   left_leg_x=3.0, right_leg_x=3.0),
    # Upper arms out and slightly back, forearms folding in so the hands come to the hips.
    HANDS_ON_HIPS: Pose(shoulder_x=8.0, shoulder_z=30.0, elbow_x=8.0, elbow_z=-78.0,
                        left_leg_x=1.0, right_leg_x=1.0),
    # Rising under control: arms low and a little out, elbows easy, the legs drawn straight beneath.
    ASCENDING: Pose(shoulder_x=-10.0, shoulder_z=14.0, elbow_x=-16.0, elbow_z=0.0,
                    left_leg_x=2.0, right_leg_x=2.0),
    # Sinking under control: arms further out and forward for balance, and knees ready for the ground.
    DESCENDING: Pose(shoulder_x=-8.0, shoulder_z=30.0, elbow_x=-16.0, elbow_z=0.0,
                     left_leg_x=-5.0, right_leg_x=-5.0),
}


def choose_pose(current: str, velocity: Vec3, forward: Vec3, up: Vec3, thrusting: bool = True, vertical_input: float = 0.0) -> str:
    """``thrusting``: being driven the way the body faces. With none, it holds itself upright: hands on its hips however
    it is still drifting, unless ``vertical_input`` (Space above zero, Ctrl below) really is taking it up or down."""
    if not thrusting:
        radial = velocity.x * up.x + velocity.y * up.y + velocity.z * up.z
        if vertical_input > 0.0 and radial > VERTICAL_SPEED:
            return ASCENDING
        if vertical_input < 0.0 and radial < -VERTICAL_SPEED:
            return DESCENDING
        return HANDS_ON_HIPS
    speed = velocity.length()
    ahead = velocity.x * forward.x + velocity.y * forward.y + velocity.z * forward.z
    vertical = abs(velocity.x * up.x + velocity.y * up.y + velocity.z * up.z)
    if current == REACHING:
        keeps = speed > LEAVE_SPEED and (ahead > STAY_AHEAD * speed or vertical > STAY_VERTICAL * speed)
        return REACHING if keeps else HANDS_ON_HIPS
    enters = speed > ENTER_SPEED and (ahead > ENTER_AHEAD * speed or vertical > ENTER_VERTICAL * speed)
    return REACHING if enters else HANDS_ON_HIPS


def blend_amount(dt: float, rate: float = BLEND_RATE) -> float:
    """How far to close the gap this frame; the same pace at any frame rate."""
    return 1.0 - exp(-rate * max(0.0, dt))
