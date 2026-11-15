"""Sentry's keys 1 and 4: the Void form with its shadow cycle, and the Void nuclear execution."""

from __future__ import annotations

from math import atan2, cos, degrees, pi, sin
from random import Random

from panda3d.core import LVector4f, OmniBoundingVolume, ShaderAttrib, TransparencyAttrib
from ursina import Shader, Vec3, scene

from movement.flight_physics import FlightPhase, Vec3 as SimVec3
from powers.aiming import center_of, trace
from powers.base import Ability, Motion
from powers.common import HurledDown, ground_blast, launch_character, nuclear_sphere
from powers.fx import Bubble
from powers.universal import seize, settle
from powers.vitals import ENERGY, PHYSICAL

SHADOW = (14, 8, 26, 200)
SHADOW_SHADER = Shader(name="void_shadow", language=Shader.GLSL, vertex="""
#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform float osg_FrameTime;
in vec4 p3d_Vertex;
void main() {
    // A slow ripple over the surface: the shape stays his, and it never quite holds still.
    vec4 moved = p3d_Vertex;
    moved.x += sin(osg_FrameTime * 2.6 + p3d_Vertex.y * 5.0) * .018;
    moved.z += cos(osg_FrameTime * 2.1 + p3d_Vertex.y * 4.0) * .018;
    gl_Position = p3d_ModelViewProjectionMatrix * moved;
}
""", fragment="""
#version 140
out vec4 fragment_color;
void main() {
    fragment_color = vec4(.008, .006, .014, 1.0);
}
""")
# An enemy Void has taken: every vertex of the body is laid flat on the ground along the light, so what is left
# is the real outline of its real pose, moving and turning with it, and there is nothing else to see.
GROUND_SHADOW_SHADER = Shader(name="void_ground_shadow", language=Shader.GLSL, vertex="""
#version 140
uniform mat4 p3d_ModelMatrix;
uniform mat4 p3d_ViewProjectionMatrix;
uniform vec4 u_ground;  // the ground here: y = x * a + z * b + c
uniform vec4 u_cast;    // how far the light carries a point per metre above the feet, and the height of the feet
in vec4 p3d_Vertex;
void main() {
    vec4 world = p3d_ModelMatrix * p3d_Vertex;
    vec2 spot = world.xz + u_cast.xy * max(0.0, world.y - u_cast.z);
    float ground = u_ground.x * spot.x + u_ground.y * spot.y + u_ground.z;
    gl_Position = p3d_ViewProjectionMatrix * vec4(spot.x, ground, spot.y, 1.0);
}
""", fragment="""
#version 140
out vec4 fragment_color;
void main() {
    fragment_color = vec4(.015, .012, .022, .9);
}
""")
OVERRIDE = 100  # above every shader set anywhere on the body
SHADOW_TAG = "void-looks"
GROUND_TAG = "void-ground-shadow"
GROUND_LIFT = .18
GROUND_SAMPLE = 3.0      # metres either side, for which way the ground slopes under it
LIGHT_LEAN = (.45, .3)   # where there is no sun to ask
MIN_LEAN, MAX_LEAN = .8, 1.4  # under a high sun a true shadow is a blot: long enough here to know it for a body
# Key 1.
CYCLE_SECONDS = 60.0
SHADOW_UNTIL = 10.0      # he is black, and they are nothing but a shadow on the ground, unable to move or attack
# For the rest of the cycle he is himself, and they are back in the world, black, weakened and taking damage.
STATUS_SECONDS = .25
DAMAGE_TICK = .25
SHADOW_EVERY = .1
# Key 4. The shares add up to all of Damage.
NUKE_SHARE, FIRST_IMPACT_SHARE, COPY_SHARE, FINAL_HIT_SHARE, FINAL_BLAST_SHARE = .25, .05, .25, .15, .3
RUSH, GRIP, LIFT, NUKE, FALL, VOID, COPY, CHARGE, LIFT_AGAIN, FALL_AGAIN, AFTER = (
    "rush", "grip", "lift", "nuke", "fall", "void", "copy", "charge", "lift_again", "fall_again", "after")
REACH = 3.0
NECK_HEIGHT = .55
GRIP_SECONDS = .2
MIN_RUSH_SPEED = 300.0
LIFT_HEIGHT = 60.0
THROW_HEIGHT = 120.0
LIFT_SPEED = 120.0
CEILING = 480.0
HOVER = 14.0
SHADOW_SECONDS = 5.0
COPY_SECONDS = 5.0
COPY_TELEPORT_EVERY = .35
COPY_RING = 3.0
FIRST_FALL_SPEED, FINAL_FALL_SPEED = 450.0, 600.0
FIRST_DRIFT, FINAL_DRIFT = .3, 2.0
NUKE_RADIUS_SHARE, MAX_NUKE_RADIUS = .1, 180.0   # of Range
FINAL_RADIUS_SHARE, MAX_FINAL_RADIUS = .1, 220.0
IMPACT_RADIUS = 30.0
OBSTACLE_SHARE = .03
NUKE_FIRE = (255, 190, 60)
NUKE_RING = (40, 20, 60, 220)
CHARGE_TINT = (255, 90, 40, 240)
CHARGE_SPOTS = ((.7, .4, 0.0), (-.7, 0.0, .3), (0.0, -.5, -.7))
AFTER_SECONDS = .3
TIME_LIMIT = 60.0


def is_black(body) -> bool:
    return body.pose_root.hasPythonTag(SHADOW_TAG)


def blacken(body, black: bool) -> None:
    """Costume, skin, hair and cape alike, whatever their own shaders, and with nothing changed on the model
    itself, so that taking this one off is all it takes for nothing to stay black."""
    root = body.pose_root
    if black == is_black(body):
        return
    if black:
        if not SHADOW_SHADER.compiled:
            SHADOW_SHADER.compile()
        root.setPythonTag(SHADOW_TAG, root.getAttrib(ShaderAttrib))
        root.setShader(SHADOW_SHADER._shader, OVERRIDE)
        return
    earlier = root.getPythonTag(SHADOW_TAG)
    root.clearPythonTag(SHADOW_TAG)
    root.clearShader()
    if earlier is not None:
        root.setAttrib(earlier)


def is_ground_shadow(body) -> bool:
    return body.pose_root.hasPythonTag(GROUND_TAG)


def to_ground_shadow(body, shadow: bool) -> None:
    """The body goes, leaving its shadow on the ground. Its health, place and state are not touched, and
    nothing on the model is changed, so taking this off is all it takes to bring it back."""
    root = body.pose_root
    if shadow == is_ground_shadow(body):
        return
    collider = body.collider  # nothing invisible to run into, or for the camera to back away from
    if shadow:
        if not GROUND_SHADOW_SHADER.compiled:
            GROUND_SHADOW_SHADER.compile()
        root.setPythonTag(GROUND_TAG, root.getAttrib(ShaderAttrib))
        root.setShader(GROUND_SHADOW_SHADER._shader, OVERRIDE)
        root.setTwoSided(True, OVERRIDE)
        root.setTransparency(TransparencyAttrib.MAlpha, OVERRIDE)
        root.setDepthOffset(8, OVERRIDE)
        root.setDepthWrite(False, OVERRIDE)  # its own parts all lie in one plane, and must not fight each other
        root.node().setBounds(OmniBoundingVolume())  # it is on the ground, not where the model's bounds say
        root.node().setFinal(True)
        if collider is not None:
            collider.node_path.stash()
        body.team.ground_shadows.add(body)
        refresh_ground_shadow(body)
        return
    earlier = root.getPythonTag(GROUND_TAG)
    root.clearPythonTag(GROUND_TAG)
    root.clearShader()
    if earlier is not None:
        root.setAttrib(earlier)
    root.clearTwoSided()
    root.clearTransparency()
    root.clearDepthOffset()
    root.clearDepthWrite()
    root.node().clearBounds()
    root.node().setFinal(False)
    if collider is not None:
        collider.node_path.unstash()
    body.team.ground_shadows.discard(body)


def _lean(game) -> tuple:
    light = getattr(getattr(game, "environment", None), "light", None)
    if light is None:
        return LIGHT_LEAN
    forward = light.forward
    if forward.y >= -.1:  # the sun is on the horizon or below it
        return LIGHT_LEAN
    x, z = forward.x / -forward.y, forward.z / -forward.y
    length = (x * x + z * z) ** .5
    if length < 1e-3:
        return LIGHT_LEAN
    scale = max(MIN_LEAN, min(MAX_LEAN, length)) / length
    return x * scale, z * scale


def refresh_ground_shadow(body) -> None:
    """The ground under it now, once a frame, since the body may be on the move."""
    game = body.team.game
    height_at = game.world.height_at
    x, z = float(body.x), float(body.z)
    across = (height_at(x + GROUND_SAMPLE, z) - height_at(x - GROUND_SAMPLE, z)) / (2.0 * GROUND_SAMPLE)
    along = (height_at(x, z + GROUND_SAMPLE) - height_at(x, z - GROUND_SAMPLE)) / (2.0 * GROUND_SAMPLE)
    root = body.pose_root
    root.setShaderInput("u_ground", LVector4f(across, along, height_at(x, z) + GROUND_LIFT - across * x - along * z, 0.0))
    lean = _lean(game)
    root.setShaderInput("u_cast", LVector4f(lean[0], lean[1], float(body.y) - .25, 0.0))


def set_enemy_look(body, shadow: bool = False, black: bool = False) -> None:
    """One at a time: each keeps what it replaced, so the other has to be off first."""
    if not shadow:
        to_ground_shadow(body, False)
    if not black:
        blacken(body, False)
    if shadow:
        to_ground_shadow(body, True)
    if black:
        blacken(body, True)


class VoidForm(Ability):
    """Key 1: Sentry goes black, and his enemy goes through a 60-second cycle for as long as it lasts."""

    ability_id = "void_form"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.subject = None
        self.cycle = 0.0
        self.stored = 0.0
        self.tick_left = 0.0
        self.shadow_left = 0.0
        self.rng = Random(11)

    def press(self) -> None:
        if self.active:
            self.cancel()
            self.say("VOID FORM OFF")
        elif self.usable():
            self.active = True
            self.shadow_left = 0.0
            blacken(self.owner, True)
            self.say("VOID FORM")

    def cancel(self) -> None:
        was_active, self.active = self.active, False
        self._let_go()
        if was_active and not isinstance(self.owner.motion, VoidNuclearExecution):  # that one puts him back itself
            blacken(self.owner, False)

    def reset(self) -> None:
        self.cancel()

    def _let_go(self) -> None:
        subject, self.subject = self.subject, None
        self.stored = 0.0
        if subject is not None:
            subject.vitals.clear_status("restrained")
            subject.vitals.clear_status("weakened")
            subject.vitals.clear_status("slowed")
            set_enemy_look(subject)

    def _valid(self, target) -> bool:
        return (target is not None and not target.parked and not target.vitals.downed
                and self.combat.hostile(self.owner, target))

    def _choose(self):
        """The manual lock if there is one; otherwise whoever it is on already, for as long as that lasts."""
        manual = self.combat.targets.lock_of(self.owner) if self.owner.controlled else None
        if manual is not None and manual is self.combat.targets.manual and self._valid(manual):
            return manual
        return self.subject if self._valid(self.subject) else self.target()

    def update(self, dt: float) -> None:
        if not self.active:
            return
        if self.vitals.nullified or self.vitals.downed:
            self.cancel()
            return
        self.shadow_left -= dt
        if self.shadow_left <= 0.0:
            self.shadow_left = SHADOW_EVERY
            if is_black(self.owner):
                self._drift(self.owner)
            if self.subject is not None and is_black(self.subject):  # it shows that this is doing them harm
                self._hurting(self.subject)
        if self.combat.time_stopped:
            return  # the cycle is world time, and stands still with the world
        chosen = self._choose()
        if chosen is not self.subject:
            self._let_go()
            self.subject = chosen
            self.cycle = 0.0
            self.tick_left = DAMAGE_TICK
            if chosen is not None:
                self._seize_subject()
        running_key_four = isinstance(self.owner.motion, VoidNuclearExecution)  # that has its own use for how they look
        if self.subject is None:
            if not running_key_four:
                blacken(self.owner, True)
            return
        before = self.cycle % CYCLE_SECONDS
        self.cycle += dt
        now = self.cycle % CYCLE_SECONDS
        if now < before:  # a new cycle starts
            self._seize_subject()
        vitals = self.subject.vitals
        if not running_key_four:
            blacken(self.owner, now < SHADOW_UNTIL)
            set_enemy_look(self.subject, shadow=now < SHADOW_UNTIL, black=now >= SHADOW_UNTIL)
        if now < SHADOW_UNTIL:
            vitals.add_status("restrained", STATUS_SECONDS)  # and it is taken off at exactly the time, below
            vitals.clear_status("slowed")
            vitals.clear_status("weakened")
            self.stored = 0.0
            return
        vitals.clear_status("restrained")
        vitals.add_status("slowed", STATUS_SECONDS)
        vitals.add_status("weakened", STATUS_SECONDS)
        powers = self.owner.powers
        self.stored += self.p("damage") * powers.strength * powers.energy_scale * dt
        self.tick_left -= dt
        if self.tick_left <= 0.0:
            self.tick_left = DAMAGE_TICK
            self.combat.hit_character(self.owner, self.subject, self.stored, ENERGY)
            self.stored = 0.0

    def _seize_subject(self) -> None:
        """Ten seconds with no movement and no attacks: whatever it had going stops now."""
        subject = self.subject
        subject.powers.cancel_all()
        if subject.motion is None or not subject.motion.ballistic:
            subject.release_motion()
        subject.knock = SimVec3()
        subject.ground.velocity = SimVec3()
        subject.flight.velocity = SimVec3()

    def _drift(self, body) -> None:
        rng = self.rng
        point = center_of(body) + SimVec3(rng.uniform(-.9, .9), rng.uniform(-1.2, 1.2), rng.uniform(-.9, .9))
        self.combat.puffs.emit(point, SimVec3(rng.uniform(-1.0, 1.0), 2.5, rng.uniform(-1.0, 1.0)), SHADOW,
                               size=.16, grow=.5, life=.8)

    def _hurting(self, body) -> None:
        rng = self.rng
        center = center_of(body)
        for _ in range(2):
            point = center + SimVec3(rng.uniform(-1.1, 1.1), rng.uniform(-1.4, 1.4), rng.uniform(-1.1, 1.1))
            self.combat.puffs.emit(point, SimVec3(rng.uniform(-2.0, 2.0), 3.5, rng.uniform(-2.0, 2.0)), SHADOW,
                                   size=.35, grow=1.4, life=.6)

    def hud_state(self) -> str:
        return "ON" if self.active else super().hud_state()


class VoidNuclearExecution(Motion):
    """Key 4: a nuclear sphere in his grip, the ground, five seconds of shadow, five of his Void copy,
    charges, and the ground again."""

    def __init__(self, ability, target) -> None:
        super().__init__(ability.owner)
        self.ability = ability
        self.target = target
        self.phase = RUSH
        self.phase_time = 0.0
        self.was_flying = self.owner.flight.is_flying
        self.thrown = False  # until the last of it, nobody breaks away from this
        self.top = 0.0
        self.fall = None
        self.stage_left = 0.0
        self.copy = None
        self.copy_clock = 0.0
        self.copy_hits = 0
        self.stages = [RUSH]
        self.rng = Random(23)
        self.owner.flight.phase = FlightPhase.CRUISE
        self.owner.flight.phase_time = 0.0
        set_enemy_look(target)

    def _enter(self, phase: str) -> None:
        self.phase = phase
        self.phase_time = 0.0
        self.stages.append(phase)

    def _gone(self) -> bool:
        target = self.target
        return target.parked or target.vitals.downed or not self.ability.combat.hostile(self.owner, target)

    def _total(self) -> float:
        powers = self.owner.powers
        return self.ability.p("damage") * powers.strength * powers.attack_scale

    def step(self, dt: float) -> bool:
        self.elapsed += dt
        self.phase_time += dt
        owner, target = self.owner, self.target
        if self.phase != AFTER:
            if self._gone() or self.elapsed > TIME_LIMIT:
                return False
            target.vitals.add_status("held", .2)
            dx, dz = float(target.x) - float(owner.x), float(target.z) - float(owner.z)
            if dx * dx + dz * dz > .01:
                self.facing = degrees(atan2(dx, dz))
        self._show_charges()
        return getattr(self, f"_step_{self.phase}")(dt)

    # -- moving and holding ----------------------------------------------
    def _fly_to(self, point: SimVec3, speed: float, dt: float) -> float:
        ability, owner = self.ability, self.owner
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        offset = point - here
        distance = offset.length()
        step = min(speed * dt, distance)
        if step <= 1e-6:
            owner.flight.velocity = SimVec3()
            return distance
        direction = offset.normalized()
        hit = trace(ability.game, center_of(owner), direction, step + 1.0, ignore=(owner, self.target), characters=(),
                    terrain=False)
        if hit.kind in ("object", "tree"):
            ability.combat.damage_hit(owner, hit, self._total() * OBSTACLE_SHARE, direction, kind=PHYSICAL, force=20.0)
        velocity = direction * (step / max(dt, 1e-4))
        self._move(velocity, dt)
        owner.flight.velocity = velocity
        return distance - step

    def _hold(self) -> None:
        owner, target = self.owner, self.target
        offset = SimVec3(float(target.x) - float(owner.x), 0.0, float(target.z) - float(owner.z))
        side = offset.normalized() if offset.length() > 1e-3 else self.ability.facing()
        target.position = (float(owner.x) + side.x * REACH, float(owner.y) + NECK_HEIGHT, float(owner.z) + side.z * REACH)
        owner.right_arm.rotation_x = -150.0

    def _reach_target(self, dt: float) -> bool:
        owner = self.owner
        speed = max(MIN_RUSH_SPEED, self.ability.p("speed"))
        offset = center_of(self.target) - center_of(owner)
        remaining = offset.length() - REACH
        if remaining <= speed * dt + .05:
            owner.flight.velocity = SimVec3()
            self.ability.game.world.play_power_sound(.35)
            return True
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        self._fly_to(here + offset.normalized() * remaining, speed, dt)
        return False

    def _lift_to(self, metres: float) -> None:
        owner = self.owner
        ground = self.ability.game.world.height_at(float(owner.x), float(owner.z))
        self.top = min(CEILING, max(float(owner.y), ground + metres))

    def _rise(self, dt: float) -> bool:
        owner = self.owner
        left = self.top - float(owner.y)
        if left <= .01:  # positions are single precision: the last of it may never quite be covered
            return True
        speed = min(LIFT_SPEED, left / max(dt, 1e-4))
        self._move(SimVec3(0.0, speed, 0.0), dt)
        owner.flight.velocity = SimVec3(0.0, speed, 0.0)
        self._hold()
        return False

    def _hover(self, dt: float) -> None:
        """Up and to one side, with a clear view of it."""
        owner, target = self.owner, self.target
        here = SimVec3(float(owner.x), float(owner.y), float(owner.z))
        there = SimVec3(float(target.x), float(target.y), float(target.z))
        flat = SimVec3(here.x - there.x, 0.0, here.z - there.z)
        flat = flat.normalized() if flat.length() > 1e-3 else SimVec3(1.0, 0.0, 0.0)
        self._fly_to(there + flat * HOVER + SimVec3(0.0, 6.0, 0.0), MIN_RUSH_SPEED, dt)

    # -- the stages ------------------------------------------------------
    def _step_rush(self, dt: float) -> bool:
        if self._reach_target(dt):
            self._enter(GRIP)
        return True

    def _step_grip(self, dt: float) -> bool:
        self._hold()
        if self.phase_time >= GRIP_SECONDS:
            self._lift_to(LIFT_HEIGHT)
            self._enter(LIFT)
        return True

    def _step_lift(self, dt: float) -> bool:
        if self._rise(dt):
            self._enter(NUKE)
        return True

    def _step_nuke(self, dt: float) -> bool:
        ability, owner = self.ability, self.owner
        self._hold()
        radius = ability.area(NUKE_RADIUS_SHARE, MAX_NUKE_RADIUS)
        nuclear_sphere(ability, owner, center_of(self.target), radius, self._total() * NUKE_SHARE,
                       ability.force(80.0, 180.0), NUKE_FIRE, NUKE_RING)
        self.fall = HurledDown(ability, owner, self.target, FIRST_FALL_SPEED, FIRST_DRIFT)
        self.target.pose_root.setP(-60.0)
        owner.right_arm.rotation_x = 60.0
        self._enter(FALL)
        return True

    def _step_fall(self, dt: float) -> bool:
        owner, ability = self.owner, self.ability
        owner.flight.velocity = SimVec3()
        if self.fall.step(dt, self._total() * OBSTACLE_SHARE):
            ground_blast(ability, owner, self.target, self.fall.point, self._total() * FIRST_IMPACT_SHARE, IMPACT_RADIUS,
                         ability.force(30.0, 120.0), NUKE_FIRE, NUKE_RING, "void-execution")
            owner.right_arm.rotation_x = 0.0
            blacken(owner, True)
            set_enemy_look(self.target, shadow=True)
            self.stage_left = SHADOW_SECONDS
            self._enter(VOID)
        return True

    def _step_void(self, dt: float) -> bool:
        self._hover(dt)
        self.stage_left = max(0.0, self.stage_left - dt)
        self.target.vitals.add_status("restrained", min(STATUS_SECONDS, self.stage_left))
        if self.stage_left <= 0.0:
            self.target.vitals.clear_status("restrained")
            self._restore_looks()
            self.copy = self.owner.team.borrow_puppets(self.owner.character_id, 1)[0]
            blacken(self.copy, True)
            self.stage_left = COPY_SECONDS
            self.copy_clock = 0.0
            self._teleport_copy()
            self._enter(COPY)
        return True

    def _teleport_copy(self) -> None:
        """A real change of place, with a wisp left at each end, and a hit on arrival."""
        ability, copy, target = self.ability, self.copy, self.target
        combat = ability.combat
        combat.puffs.emit(center_of(copy), SimVec3(0.0, 1.0, 0.0), SHADOW, size=1.2, grow=2.0, life=.35)
        angle = self.rng.uniform(0.0, 2.0 * pi)
        x, z = float(target.x) + sin(angle) * COPY_RING, float(target.z) + cos(angle) * COPY_RING
        y = max(ability.game.world.height_at(x, z) + .25, float(target.y))
        copy.position = (x, y, z)
        yaw = degrees(atan2(float(target.x) - x, float(target.z) - z))
        copy.local_yaw = yaw
        ability.game.planet.orient_entity(copy, SimVec3(x, y, z), yaw)
        combat.puffs.emit(center_of(copy), SimVec3(0.0, 1.0, 0.0), SHADOW, size=1.2, grow=2.0, life=.35)
        if self.copy_hits % 2:
            copy.right_leg.rotation_x, copy.right_arm.rotation_x = -90.0, 0.0
        else:
            copy.right_arm.rotation_x, copy.right_leg.rotation_x = -150.0, 0.0
        self.copy_hits += 1
        combat.hit_character(self.owner, target, self._total() * COPY_SHARE * COPY_TELEPORT_EVERY / COPY_SECONDS, PHYSICAL)
        target.pose_root.setP(self.rng.uniform(-22.0, 22.0))
        combat.puffs.emit(center_of(target), SimVec3(0.0, 2.0, 0.0), NUKE_RING, size=.7, grow=2.0, life=.25)
        ability.game.world.play_power_sound(.25)

    def _step_copy(self, dt: float) -> bool:
        self._hover(dt)
        seconds = min(dt, self.stage_left)
        self.stage_left -= seconds
        self.copy_clock += seconds
        if self.copy_clock >= COPY_TELEPORT_EVERY and self.stage_left > 0.0:
            self.copy_clock -= COPY_TELEPORT_EVERY
            self._teleport_copy()
            if self._gone():
                return False
        if self.stage_left <= 0.0:
            self._return_copy()
            self.target.pose_root.setP(0.0)
            self._enter(CHARGE)
        return True

    def _step_charge(self, dt: float) -> bool:
        if self._reach_target(dt):
            self.charges_on = True
            self.ability.game.world.play_power_sound(.3)
            self._lift_to(THROW_HEIGHT)
            self._enter(LIFT_AGAIN)
        return True

    charges_on = False

    def _show_charges(self) -> None:
        if not self.charges_on:
            return
        center = center_of(self.target)
        for bubble, spot in zip(self.ability.charges, CHARGE_SPOTS):
            bubble.entity.position = Vec3(center.x + spot[0], center.y + spot[1], center.z + spot[2])
            bubble.show(.8)

    def _hide_charges(self) -> None:
        self.charges_on = False
        for bubble in self.ability.charges:
            bubble.hide()

    def _step_lift_again(self, dt: float) -> bool:
        if self._rise(dt):
            self.fall = HurledDown(self.ability, self.owner, self.target, FINAL_FALL_SPEED, FINAL_DRIFT)
            self.target.pose_root.setP(-60.0)
            self.owner.right_arm.rotation_x = 60.0
            self.ability.game.camera_impulse = max(self.ability.game.camera_impulse, 2.5)
            self._enter(FALL_AGAIN)
        return True

    def _step_fall_again(self, dt: float) -> bool:
        ability, owner = self.ability, self.owner
        owner.flight.velocity = SimVec3()
        if self.fall.step(dt, self._total() * OBSTACLE_SHARE):
            self._hide_charges()
            ability.combat.hit_character(owner, self.target, self._total() * FINAL_HIT_SHARE, PHYSICAL)
            radius = ability.area(FINAL_RADIUS_SHARE, MAX_FINAL_RADIUS)
            nuclear_sphere(ability, owner, self.fall.point, radius, self._total() * FINAL_BLAST_SHARE,
                           ability.force(80.0, 180.0), NUKE_FIRE, NUKE_RING, on_ground=True)
            self.thrown = True
            self._release()
            self._enter(AFTER)
        return True

    def _step_after(self, dt: float) -> bool:
        self.owner.flight.velocity = SimVec3()
        return self.phase_time < AFTER_SECONDS

    # -- leaving everything as it was ------------------------------------
    def _return_copy(self) -> None:
        copy, self.copy = self.copy, None
        if copy is not None:
            copy.right_arm.rotation_x = copy.right_leg.rotation_x = 0.0
            self.owner.team.return_puppets([copy])

    def _restore_looks(self) -> None:
        void = self.ability.owner.powers.abilities["void_form"]
        blacken(self.owner, void.active)
        set_enemy_look(self.target)  # if the Void form has them, its next update gives them back their look

    def _release(self) -> None:
        target = self.target
        target.vitals.clear_status("held")
        target.vitals.clear_status("restrained")
        if not target.vitals.downed:
            target.pose_root.setP(0.0)

    def finish(self) -> None:
        """Runs however this ends: no copy, no charges, nothing left black, and nobody left hanging."""
        owner, target = self.owner, self.target
        self._return_copy()
        self._hide_charges()
        self._restore_looks()
        self._release()
        if self.phase in (GRIP, LIFT, NUKE, FALL, LIFT_AGAIN, FALL_AGAIN) and not target.parked:
            launch_character(owner, target, SimVec3())
        owner.right_arm.rotation_x = 0.0
        owner.flight.velocity = SimVec3()
        settle(owner, self.was_flying)


class VoidNuclearExecutionAbility(Ability):
    ability_id = "void_nuclear_execution"

    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.charges = [Bubble(scene, CHARGE_TINT, center=0.0) for _ in CHARGE_SPOTS]

    def press(self) -> None:
        owner = self.owner
        if not self.usable() or owner.motion is not None or not owner.flight_allowed:
            return  # one already running is a motion, so it can never start twice
        target = self.target()
        if target is None:
            self.say("NO ENEMY IN RANGE")
            return
        seize(owner, target)
        owner.motion = VoidNuclearExecution(self, target)
        self.say("VOID NUCLEAR EXECUTION")

    def hud_state(self) -> str:
        return "ON" if isinstance(self.owner.motion, VoidNuclearExecution) else super().hud_state()
