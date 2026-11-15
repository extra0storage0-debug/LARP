"""How a human body walks and runs, worked out from where the feet have to be. No engine imports.

A planted foot does not move over the ground, so in the body's frame it travels backward at exactly the body's speed.
It rolls from the heel, through the flat foot, to the ball, and each of those points stays still on the ground while it
carries the weight. The swing brings the foot forward again, clear of the ground. The hip and knee then follow from
the foot's position, so that the legs cannot disagree with the ground.

Angles are degrees, positive meaning backward for a leg and toes down for a foot, as the body code has always used them.
Distances are the model's own, so each character walks with their own proportions.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import acos, atan2, cos, degrees, hypot, pi, radians, sin

WALK_TOP, RUN_FROM = 3.4, 6.0     # m/s: between these a walk becomes a run
# Cycles per second at each speed (one cycle is two steps), from how people walk, run and sprint.
FREQUENCIES = ((.0, .8), (1.5, .92), (3.0, 1.18), (WALK_TOP, 1.25), (RUN_FROM, 1.35), (12.0, 1.6), (22.0, 2.1), (40.0, 2.5), (80.0, 2.8))
WALK_DUTY, RUN_DUTY = .62, .36    # the share of a cycle each foot is on the ground
MIN_DUTY = .12                    # past where legs can keep up, a foot still touches down; see plan_for
REACH = 1.0                       # how long a stance can be, in leg lengths
FULL_REACH = .992                 # a knee never quite locks
HEEL_SHARE, BALL_SHARE, SOLE_SHARE = .07, .13, .085  # of the leg's length, from the ankle
HEEL_ROCK_UNTIL, BALL_ROCK_FROM = .18, .55           # of the stance
MAX_HIP_DROP = .12                # in leg lengths


@dataclass(frozen=True, slots=True)
class LegShape:
    """One body's legs, in its bind pose."""

    thigh: float
    shin: float
    thigh_rest: float   # the bones' own lean in the bind pose, in the leg's sagittal plane, as angles
    shin_rest: float
    hip_y: float        # how far above the flat ankle the hip stands
    hip_z: float        # how far ahead of the flat ankle the hip stands
    hip_half_width: float

    @property
    def length(self) -> float:
        return self.thigh + self.shin

    @property
    def heel(self) -> float:
        return self.length * HEEL_SHARE

    @property
    def ball(self) -> float:
        return self.length * BALL_SHARE

    @property
    def sole(self) -> float:
        return self.length * SOLE_SHARE


def leg_shape(hip, knee, ankle) -> LegShape:
    """From the bind-pose positions of one leg's joints."""
    thigh = (knee[1] - hip[1], knee[2] - hip[2])
    shin = (ankle[1] - knee[1], ankle[2] - knee[2])
    return LegShape(hypot(*thigh), hypot(*shin), degrees(atan2(-thigh[1], -thigh[0])), degrees(atan2(-shin[1], -shin[0])),
                    hip[1] - ankle[1], hip[2] - ankle[2], abs(hip[0]))


@dataclass(frozen=True, slots=True)
class Plan:
    """One speed's cycle."""

    frequency: float   # cycles per second
    duty: float        # share of the cycle on the ground
    sweep: float       # how far a planted foot travels under the body
    clearance: float   # how high the swinging foot lifts
    heel_strike: float # toes up as the heel lands
    toe_off: float     # heel up as the foot leaves
    running: float     # 0 a walk, 1 a run
    hip_yaw: float
    hip_roll: float
    bob: float
    sway: float
    hip_drop: float


def _smooth(low: float, high: float, value: float) -> float:
    t = max(0.0, min(1.0, (value - low) / (high - low)))
    return t * t * (3.0 - 2.0 * t)


def frequency_at(speed: float) -> float:
    if speed >= FREQUENCIES[-1][0]:
        return FREQUENCIES[-1][1]
    for (low, low_rate), (high, high_rate) in zip(FREQUENCIES, FREQUENCIES[1:]):
        if speed <= high:
            return low_rate + (high_rate - low_rate) * (speed - low) / (high - low)
    return FREQUENCIES[-1][1]


def plan_for(speed: float, shape: LegShape, step: float = 1.0, stride: float = 1.0) -> Plan:
    """``step`` and ``stride`` are the character's own: longer steps at a lower rate, and a bigger or smaller movement.

    Up to where the legs can follow, the foot's travel is exactly the ground's, so nothing can slide. Beyond that (about
    22 m/s for most) no leg could stay down for long enough, and the foot still touches down for MIN_DUTY of a cycle.
    """
    speed = abs(speed)
    length = shape.length
    running = _smooth(WALK_TOP, RUN_FROM, speed)
    frequency = frequency_at(speed) / step
    cycle = speed / frequency  # the ground covered in one cycle
    wanted = WALK_DUTY + (RUN_DUTY - WALK_DUTY) * running
    sweep = min(cycle * wanted, REACH * length * stride)
    duty = max(MIN_DUTY, min(wanted, sweep / max(cycle, 1e-6)))
    # The hips sit low enough for the leg to reach the foot at both ends of the stance.
    half = sweep * .5
    furthest = hypot(half, shape.hip_y)
    drop = max(0.0, furthest - length * FULL_REACH)
    size = min(1.0, speed / 1.5)
    return Plan(frequency, duty, sweep,
                length * (.07 + .05 * min(1.0, speed / 3.0) + .3 * running),
                (19.0 - 11.0 * running) * size, (34.0 + 12.0 * running) * size, running,
                (5.5 + 4.0 * running) * size * stride, (3.0 - 1.0 * running) * size,
                length * (.016 + .014 * running) * size, length * (.024 - .014 * running) * size,
                min(MAX_HIP_DROP * length, drop + length * .035 * running))


def foot_at(phase: float, plan: Plan, shape: LegShape) -> tuple[float, float, float]:
    """Where this foot's ankle is against the flat, standing ankle: along the direction of travel, up, and its pitch.

    ``phase`` is 0 to 1 through this leg's cycle, and 0 is the heel coming down.
    """
    phase %= 1.0
    if phase < plan.duty:
        return _stance(phase / plan.duty, plan, shape)
    along_0, up_0, pitch_0 = _stance(1.0, plan, shape)
    along_1, up_1, pitch_1 = _stance(0.0, plan, shape)
    t = (phase - plan.duty) / (1.0 - plan.duty)
    eased = t * t * (3.0 - 2.0 * t)
    # The foot leaves and lands moving at the ground's speed: it draws back just before the heel comes down, as a real one does.
    span = along_1 - along_0
    ground = min(abs(span) * .9, plan.sweep / plan.duty * (1.0 - plan.duty))
    along = (along_0 * (2.0 * t ** 3 - 3.0 * t ** 2 + 1.0) + along_1 * (3.0 * t ** 2 - 2.0 * t ** 3)
             - ground * (t ** 3 - 2.0 * t ** 2 + t) - ground * (t ** 3 - t ** 2))
    # A run folds the heel up behind, early; a walk just lifts the foot enough to clear the ground.
    lift = sin(pi * t) * (1.0 + .65 * plan.running * cos(pi * t))
    return (along,
            up_0 + (up_1 - up_0) * eased + plan.clearance * lift,
            pitch_0 + (pitch_1 - pitch_0) * eased + (12.0 + 26.0 * plan.running) * lift)


def _stance(u: float, plan: Plan, shape: LegShape) -> tuple[float, float, float]:
    """The contact stays still on the ground: it moves back through the body at the body's own speed."""
    contact = plan.sweep * (.5 - u)
    heel, ball, sole = shape.heel, shape.ball, shape.sole
    if u < HEEL_ROCK_UNTIL and plan.heel_strike:
        pitch = -plan.heel_strike * (1.0 - u / HEEL_ROCK_UNTIL) ** 2
        c, s = cos(radians(pitch)), sin(radians(pitch))
        return contact - heel + heel * c + sole * s, -heel * s + sole * c - sole, pitch
    if u > BALL_ROCK_FROM and plan.toe_off:
        pitch = plan.toe_off * ((u - BALL_ROCK_FROM) / (1.0 - BALL_ROCK_FROM)) ** 1.5
        c, s = cos(radians(pitch)), sin(radians(pitch))
        return contact + ball - ball * c + sole * s, ball * s + sole * c - sole, pitch
    return contact, 0.0, 0.0


def leg_angles(shape: LegShape, ankle_z: float, ankle_y: float, hip_z: float, hip_y: float, pitch: float) -> tuple[float, float, float]:
    """The thigh, knee and foot rotations that put the ankle there, with the foot at that pitch. Knees only bend forward."""
    dz, dy = ankle_z - hip_z, ankle_y - hip_y
    thigh, shin = shape.thigh, shape.shin
    reach = max(abs(thigh - shin) + 1e-4, min((thigh + shin) * FULL_REACH, hypot(dz, dy)))
    # Measured from straight down, positive backward.
    line = atan2(-dz, -dy)
    inner = max(-1.0, min(1.0, (thigh * thigh + shin * shin - reach * reach) / (2.0 * thigh * shin)))
    knee = pi - acos(inner)
    upper = line - atan2(shin * sin(knee), thigh + shin * cos(knee))
    thigh_x = degrees(upper) - shape.thigh_rest
    shin_abs = degrees(upper + knee)
    knee_x = shin_abs - shape.shin_rest - thigh_x
    return thigh_x, knee_x, pitch - (thigh_x + knee_x)
