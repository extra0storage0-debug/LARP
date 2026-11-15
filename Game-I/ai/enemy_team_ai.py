"""Renderer-independent squad tactics for the enemy team.

The director owns shared decisions (roles, formation points, attack tokens).
Each brain turns those into one agent's movement and attack intent. Nothing here
imports the engine, so the behaviour can be exercised by plain unit tests.
"""

from __future__ import annotations

from characters.registry import definitions

from dataclasses import dataclass, field
from enum import Enum, auto
from math import atan2, cos, pi, sin, sqrt
from random import Random

from movement.flight_physics import Vec3

CEILING = 490.0
PURSUIT_DISTANCE = 220.0
SEPARATION_RADIUS = 9.0
RAM_OVERSHOOT = 110.0  # room to build speed on each pass
BRAWL_SECONDS = 5.0
BRAWL_GAP_SECONDS = 9.0


class Role(Enum):
    LEADER = auto()
    INTERCEPTOR = auto()
    ATTACKER = auto()
    RANGED = auto()
    FLANKER = auto()
    SUPPORT = auto()


class Strategy(Enum):
    PURSUE = auto()     # target is far away or outrunning the team
    ENCIRCLE = auto()   # close the ring before committing
    ASSAULT = auto()    # ring is formed; press from every side


# Filled first when few enemies remain, so the team keeps its most
# valuable jobs as members die. The leader is always assigned separately.
ROLE_PRIORITY = (Role.ATTACKER, Role.RANGED, Role.FLANKER,
                 Role.INTERCEPTOR, Role.SUPPORT)

# Desired distance from the target and base bearing relative to its travel
# direction. Distinct bearings are what produce a surround instead of a queue.
ROLE_STANDOFF = {Role.LEADER: (42.0, 90.0), Role.INTERCEPTOR: (26.0, 0.0),
                 Role.ATTACKER: (3.2, 215.0), Role.RANGED: (72.0, 270.0),
                 Role.FLANKER: (9.0, 150.0), Role.SUPPORT: (18.0, 40.0)}
ROLE_ELEVATION = {Role.LEADER: 16.0, Role.INTERCEPTOR: 6.0, Role.ATTACKER: 0.0,
                  Role.RANGED: 26.0, Role.FLANKER: 2.0, Role.SUPPORT: 9.0}

MELEE_ROLES = (Role.ATTACKER, Role.FLANKER)


@dataclass(slots=True)
class Personality:
    """Small per-enemy differences in timing and preference."""
    reaction: float = .2        # seconds of target-position lag
    aggression: float = 1.0     # scales attack cooldowns (higher attacks sooner)
    aim_rate: float = 2.4       # beam tracking speed in radians per second
    ranged_bias: float = 0.0    # added chance of choosing a ranged attack
    strafe: float = 1.0         # direction and strength of evasive sidesteps


PERSONALITIES = {item.character_id: Personality(*item.personality) for item in definitions()}


@dataclass(slots=True)
class AITuning:
    """AI character settings in decision units; defaults are the originals."""
    reaction: float = 1.0
    prediction: float = 1.0
    flight_pursuit: float = 1.0
    pursuit: float = 1.0
    coordination: float = 1.0
    flanking: float = 1.0
    detection_range: float = 20000.0
    role_interval: float = 2.5

    @classmethod
    def from_profile(cls, view) -> "AITuning":
        fraction = view.fraction
        return cls(
            reaction=fraction("reaction_time_pct") / max(.01, fraction("reaction_speed_pct")),
            prediction=fraction("target_prediction_pct"),
            flight_pursuit=fraction("flight_pursuit_pct"),
            pursuit=fraction("pursuit_aggression_pct"),
            coordination=fraction("team_coordination_pct"),
            flanking=fraction("flanking_frequency_pct"),
            detection_range=view.number("detection_range") * fraction("detection_sensitivity_pct"),
            role_interval=2.5 / max(.01, fraction("target_switching_pct")))


@dataclass(slots=True)
class TargetView:
    position: Vec3
    velocity: Vec3
    flying: bool = False
    altitude: float = 0.0
    alive: bool = True


@dataclass(slots=True)
class AgentView:
    """What the tactical layer needs to know about one enemy."""
    name: str
    position: Vec3
    velocity: Vec3
    flying: bool = False
    health_fraction: float = 1.0
    alive: bool = True
    frozen: bool = False


@dataclass(slots=True)
class Intent:
    """One decision: where to go, and whether to fly there."""
    destination: Vec3
    match_velocity: Vec3 = field(default_factory=Vec3)
    want_flight: bool = True
    distance_to_target: float = 0.0


def horizontal_distance(a: Vec3, b: Vec3) -> float:
    dx, dz = a.x - b.x, a.z - b.z
    return sqrt(dx * dx + dz * dz)


def predict_intercept(origin: Vec3, target: Vec3, target_velocity: Vec3,
                      pursuer_speed: float, *, max_lead: float = 6.0) -> Vec3:
    """Return where to aim so a constant-speed pursuer meets a moving target."""
    to_target = target - origin
    speed = max(1.0, float(pursuer_speed))
    a = (target_velocity.x ** 2 + target_velocity.y ** 2 + target_velocity.z ** 2
         - speed * speed)
    b = 2.0 * (to_target.x * target_velocity.x + to_target.y * target_velocity.y
               + to_target.z * target_velocity.z)
    c = to_target.x ** 2 + to_target.y ** 2 + to_target.z ** 2
    lead = None
    if abs(a) < 1e-6:
        lead = -c / b if abs(b) > 1e-6 else None
    else:
        discriminant = b * b - 4.0 * a * c
        if discriminant >= 0.0:
            root = sqrt(discriminant)
            times = [t for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a))
                     if t > 0.0]
            lead = min(times) if times else None
    if lead is None:
        # Target outruns the pursuer: head for its position after the cap.
        lead = max_lead
    return target + target_velocity * min(max_lead, lead)


def separation(agent: AgentView, others) -> Vec3:
    """Push apart nearby teammates so models never overlap or stack up."""
    push = Vec3()
    for other in others:
        if other is agent or not other.alive:
            continue
        delta = agent.position - other.position
        distance = delta.length()
        if 1e-5 < distance < SEPARATION_RADIUS:
            push = push + delta * ((SEPARATION_RADIUS - distance)
                                   / (SEPARATION_RADIUS * distance))
    return push


class TeamDirector:
    """Shared squad brain: target picture, roles, strategy and attack tokens."""

    def __init__(self) -> None:
        self.tuning = AITuning()
        self.roles: dict[str, Role] = {}
        self.leader: str | None = None
        self.strategy = Strategy.ENCIRCLE
        self._next_roles = 0.0
        self._ring_angle = 0.0
        self._living: tuple[str, ...] = ()

    def forget(self, name: str) -> None:
        self.roles.pop(name, None)
        self._next_roles = 0.0

    # -- periodic planning ----------------------------------------------
    def update(self, now: float, agents, target: TargetView) -> None:
        living = tuple(agent for agent in agents if agent.alive)
        names = tuple(agent.name for agent in living)
        if names != self._living or now >= self._next_roles:
            self._assign_roles(living, target)
            self._living = names
            self._next_roles = now + self.tuning.role_interval
        self._choose_strategy(living, target)
        # A slow drift keeps formation points from becoming predictable.
        self._ring_angle = (self._ring_angle + .35 * .25) % (2.0 * pi)

    def _assign_roles(self, living, target: TargetView) -> None:
        self.roles = {}
        if not living:
            self.leader = None
            return
        previous = self.leader
        candidates = sorted(living, key=lambda a: (-a.health_fraction, a.name))
        retained = next((a for a in living if a.name == previous
                         and a.health_fraction > .28), None)
        leader = retained or candidates[0]
        self.leader = leader.name
        self.roles[leader.name] = Role.LEADER

        remaining = [a for a in living if a is not leader]
        travel = target.velocity.normalized()
        if travel.length() < 1e-5:
            travel = Vec3(0.0, 0.0, 1.0)

        def dist(agent) -> float:
            return (agent.position - target.position).length()

        def ahead(agent) -> float:
            delta = agent.position - target.position
            return delta.x * travel.x + delta.y * travel.y + delta.z * travel.z

        selectors = {Role.ATTACKER: lambda a: (a.health_fraction < .35, dist(a)),
                     Role.RANGED: lambda a: -dist(a),
                     Role.FLANKER: ahead,
                     Role.INTERCEPTOR: lambda a: -ahead(a),
                     Role.SUPPORT: dist}
        for role in ROLE_PRIORITY:
            if not remaining:
                break
            choice = min(remaining, key=selectors[role])
            self.roles[choice.name] = role
            remaining.remove(choice)

    def _choose_strategy(self, living, target: TargetView) -> None:
        if not living:
            return
        distances = [(a.position - target.position).length() for a in living]
        nearest = min(distances)
        speed = target.velocity.length()
        if nearest > PURSUIT_DISTANCE or (speed > 130.0 and nearest > 60.0):
            self.strategy = Strategy.PURSUE
        elif sum(1 for d in distances if d < 90.0) >= max(1, len(living) // 2 + 1):
            self.strategy = Strategy.ASSAULT
        else:
            self.strategy = Strategy.ENCIRCLE

    def role_of(self, name: str) -> Role:
        return self.roles.get(name, Role.SUPPORT)

    def formation_point(self, name: str, target: TargetView,
                        agent_speed: float) -> Vec3:
        """World point this role should hold around the (moving) target."""
        role = self.role_of(name)
        standoff, bearing = ROLE_STANDOFF[role]
        tuning = self.tuning
        if role is Role.FLANKER:
            # Flanking Frequency moves this slot between front-quarter and behind.
            bearing = 40.0 + (bearing - 40.0) * min(1.0, tuning.flanking)
        if role not in MELEE_ROLES:
            standoff /= max(.05, tuning.pursuit)
        heading = atan2(target.velocity.x, target.velocity.z) \
            if target.velocity.length() > 1.0 else self._ring_angle
        angle = heading + bearing * pi / 180.0
        if self.strategy is Strategy.ENCIRCLE and role in MELEE_ROLES:
            # Melee roles wait on the ring until the others are in position.
            standoff = max(standoff, 16.0)
        # Interceptors stand where the target is about to be, not where it is.
        anchor = target.position
        if role is Role.INTERCEPTOR and target.velocity.length() > 5.0:
            anchor = predict_intercept(target.position - target.velocity.normalized() * 60.0,
                                       target.position, target.velocity, agent_speed)
        elevation = ROLE_ELEVATION[role] if target.flying or role is not Role.ATTACKER else 0.0
        return Vec3(anchor.x + sin(angle) * standoff,
                    min(CEILING, anchor.y + elevation),
                    anchor.z + cos(angle) * standoff)


class EnemyBrain:
    """One AI character's movement decisions; updated on a staggered schedule."""

    def __init__(self, name: str, personality: Personality, *, seed: int = 0) -> None:
        self.name = name
        self.personality = personality
        self.tuning = AITuning()
        self.rng = Random(seed)
        self.can_fly = True
        self._stale_position: Vec3 | None = None
        self._stale_velocity = Vec3()
        self._stale_time = -999.0

    def observed_target(self, target: TargetView, now: float) -> TargetView:
        """Return the target as this character perceives it after its reaction lag."""
        if (self._stale_position is None
                or now - self._stale_time >= self.personality.reaction * self.tuning.reaction):
            self._stale_position = target.position
            self._stale_velocity = target.velocity
            self._stale_time = now
        age = now - self._stale_time
        return TargetView(self._stale_position + self._stale_velocity * age,
                          self._stale_velocity, target.flying, target.altitude,
                          target.alive)

    def decide(self, now: float, agent: AgentView, target: TargetView,
               director: TeamDirector, teammates, *, flight_speed: float) -> Intent:
        """Produce this tick's destination for one AI character."""
        tuning = self.tuning
        seen = self.observed_target(target, now)
        distance = (agent.position - seen.position).length()
        role = director.role_of(self.name)
        if distance > tuning.detection_range:
            # Out of detection range: the target is unknown, so hold position.
            return Intent(agent.position, Vec3(), agent.flying, distance)
        if director.strategy is Strategy.PURSUE:
            destination = self._pursuit_point(agent, seen, role, flight_speed)
        else:
            destination = director.formation_point(self.name, seen, flight_speed)
            # Without coordination each character simply heads straight for the target.
            coordination = min(1.0, tuning.coordination)
            destination = seen.position + (destination - seen.position) * coordination
        want_flight = self.can_fly and (target.flying or distance > 120.0
                                        or role in (Role.RANGED, Role.LEADER)
                                        or target.altitude > 6.0)
        match = seen.velocity * min(1.0, tuning.prediction)
        return Intent(destination, match, want_flight, distance)

    def _pursuit_point(self, agent: AgentView, target: TargetView, role: Role,
                       flight_speed: float) -> Vec3:
        intercept = predict_intercept(agent.position, target.position, target.velocity,
                                      flight_speed)
        # Prediction Accuracy and Pursuit Sensitivity scale how far ahead to aim.
        lead = self.tuning.prediction * self.tuning.flight_pursuit
        intercept = target.position + (intercept - target.position) * lead
        # Fan out across the predicted point so the chase is not one straight line.
        offset = {Role.LEADER: 0.0, Role.INTERCEPTOR: 0.0, Role.ATTACKER: -14.0,
                  Role.RANGED: 26.0, Role.FLANKER: 30.0, Role.SUPPORT: -30.0}[role]
        travel = target.velocity.normalized()
        side = Vec3(travel.z, 0.0, -travel.x)
        if side.length() < 1e-5:
            side = Vec3(1.0, 0.0, 0.0)
        return intercept + side * offset


@dataclass(slots=True)
class SteeringCommand:
    move: Vec3
    vertical: float = 0.0
    boost: bool = False
    brake: bool = False
    heading: Vec3 | None = None  # horizontal direction the velocity should turn toward


def steer_flight(position: Vec3, velocity: Vec3, destination: Vec3, match_velocity: Vec3,
                 *, cruise_speed: float, boost_speed: float, thrust: float, braking: float,
                 dt: float, push: Vec3 | None = None,
                 arrive_radius: float = 2.0) -> SteeringCommand:
    """Convert a destination into flight input without overshooting or orbiting.

    Desired velocity decays with the remaining stopping distance and adds the
    target's own velocity, so an enemy settles beside a moving player instead of
    flying past and circling back. The panel can set flight values thousands of
    times the defaults, so thrust is sized to the frame: one full thrust step at
    5,000 m/s2 would otherwise overshoot every formation point.
    """
    delta = destination - position
    distance = delta.length()
    target_speed = match_velocity.length()
    # Boost is a separate cap in the flight model, and can be below cruise speed.
    use_boost_cap = boost_speed > cruise_speed
    fastest = max(boost_speed, cruise_speed)
    limit = fastest if distance > 120.0 or target_speed > cruise_speed * .8 else cruise_speed
    if distance < arrive_radius and target_speed < 1.0 and (push is None or push.length() < .05):
        return SteeringCommand(Vec3(), 0.0, False, velocity.length() > 4.0 and braking >= thrust)

    frame = max(1e-3, dt)
    deceleration = max(thrust, braking, 20.0) * .6
    closing = min(limit, sqrt(2.0 * deceleration * distance), distance / (2.0 * frame))
    desired = delta.normalized() * closing + match_velocity
    if push is not None:
        desired = desired + push * 22.0
    desired = desired.clamped(limit)

    error = desired - velocity
    speed = velocity.length()
    aligned = (velocity.x * desired.x + velocity.y * desired.y
               + velocity.z * desired.z) / max(1e-5, speed * max(desired.length(), 1e-5))
    # Overspeed or nearly reversing: shed speed first, when brakes beat engine thrust.
    brake = (braking >= thrust and speed > 25.0
             and (speed > desired.length() * 1.35 or aligned < -.2))
    # Command only the thrust this frame needs to cancel the velocity error, which
    # prevents hunting back and forth around a formation point.
    command = error * (1.0 / max(error.length(), thrust * frame, 1e-3))
    boost = (use_boost_cap and limit > cruise_speed
             and desired.length() > cruise_speed * .95 and not brake)
    heading = Vec3(desired.x, 0.0, desired.z)
    return SteeringCommand(Vec3(command.x, 0.0, command.z).clamped(1.0),
                           max(-1.0, min(1.0, command.y)), boost, brake,
                           heading if heading.length() > 1.0 else None)


def terrain_safe_altitude(position: Vec3, velocity: Vec3, height_at, *,
                          clearance: float = 7.0, horizon: float = 1.2) -> float:
    """Lowest safe flight height along the next ``horizon`` seconds of travel."""
    highest = height_at(position.x, position.z)
    for fraction in (.35, .7, 1.0):
        probe = position + velocity * (horizon * fraction)
        highest = max(highest, height_at(probe.x, probe.z))
    return min(CEILING, highest + clearance)
