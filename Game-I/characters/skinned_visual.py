"""The characters' bodies: a baked, skinned, textured model behind the same joints the game has always posed.

Gameplay only ever writes rotation_x and rotation_z on left_arm, right_arm, left_elbow, right_elbow, left_leg and
right_leg, and reads pose_root and the eye markers. That small surface stays exactly as it was; underneath,
each write moves real bones. Knees, spine, head and breathing follow from the same numbers.

If a character's baked files are missing the caller falls back to the older built body, so the game still runs.
"""

from __future__ import annotations

import json
from math import atan2, cos, degrees, exp, hypot, pi, radians, sin, sqrt
from pathlib import Path

import numpy as np
from panda3d.core import (BoundingSphere, Filename, LODNode, LQuaternionf, LVecBase3f, LVecBase4f, LVector3f, ModelNode, NodePath, PTA_LVecBase3f,
                          PartBundle, SamplerState, ShaderAttrib, Texture, TexturePool, TextureStage, TransparencyAttrib)
from ursina import Entity, Mesh, Shader, Vec3, color, scene

from characters.roster import kit_of
from characters.skinned_shader import CAPE_PBR_SHADER, GEAR_SHADER, HAIR_SHADER, SKIN_SHADER
from movement.character_styles import style_of

from characters.registry import definitions, model_of
from movement.gait import foot_at, leg_angles, leg_shape, plan_for

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "characters"
HIGH_DETAIL_QUALITIES = ("high", "ultra")
_quality = {"value": "low"}

# How each character carries themselves: chest out and chin up is not how Soldier Boy stands.
STANCES = {item.character_id: item.stance for item in definitions() if item.stance}
SECONDARY_TOLERANCE = .35  # degrees
TURN_STEP = .55            # a turn on the spot takes steps as this many m/s for each radian per second
WALK_STARTS, WALK_FULL = .08, .9  # m/s: from standing to a full stride
ARM_SWING_WALK, ARM_SWING_RUN, ARM_LAG = 34.0, 66.0, .25
WALK_FORWARD = 4.0         # degrees
TOGETHER_ANKLE, POINTED_FEET, SHOULDER_LIFT = .075, 58.0, .11
CAPE_LENGTH, CAPE_TOP_HALF, CAPE_HEM_HALF = 1.72, .2, .41  # down to the back of the knee, no wider than the shoulders' reach
CAPE_GRAVITY, AIR_LIMIT, AIR_PULL, CLOTH_DAMPING = 22.0, 70.0, 2.4, .97
DEFAULT_STANCE = dict(chest=-2.0, head=0.0, arms_out=9.0, run_lean=11.0, stride=1.0)


def set_detail_quality(quality: str) -> None:
    """Which texture size to load from now on: 1024 up to Medium, the full bake on High and Ultra."""
    _quality["value"] = str(quality).lower()


def _folder(name: str) -> Path:
    """Where a body's files are: a character may borrow another's model until it has its own."""
    return ASSETS / model_of(name)


def is_available(name: str) -> bool:
    folder = _folder(name)
    return all((folder / item).exists() for item in ("model.bam", "rig.json", "albedo.jpg", "material.jpg", "normal.jpg", "eye.jpg"))


def _load_texture(path: Path) -> Texture:
    texture = TexturePool.loadTexture(Filename.fromOsSpecific(str(path)))
    texture.setMinfilter(SamplerState.FT_linear_mipmap_linear)
    texture.setMagfilter(SamplerState.FT_linear)
    texture.setAnisotropicDegree(4)
    texture.setCompression(Texture.CMDefault)
    texture.setKeepRamImage(False)  # once on the GPU, no second copy in main memory
    return texture


def preload(names) -> None:
    """Everything a body needs from disk, now, so that nobody's first appearance can stall a frame later on."""
    _load_texture(ASSETS / "strands.png")
    for name in names:
        for stem in ("albedo", "material", "normal"):
            _sheet(name, stem)
        _load_texture(_folder(name) / "eye.jpg")
        _load_model(name)
    _flag_texture()
    for colors in CAPE_COLORS.values():
        if colors is not None:
            _cloth_texture(*colors)


def _sheet(name: str, stem: str) -> Texture:
    folder = _folder(name)
    high = folder / f"{stem}_hi.jpg"
    if _quality["value"] in HIGH_DETAIL_QUALITIES and high.exists():
        return _load_texture(high)
    return _load_texture(folder / f"{stem}.jpg")


def _quat(axis: tuple, degrees: float) -> LQuaternionf:
    q = LQuaternionf()
    q.setFromAxisAngle(degrees, LVector3f(*axis))
    return q


def _turn_between(start: LVector3f, end: LVector3f) -> LQuaternionf:
    """The shortest rotation taking one direction to another, whichever way this coordinate system turns."""
    start, end = LVector3f(start), LVector3f(end)
    start.normalize()
    end.normalize()
    axis = start.cross(end)
    if axis.length() < 1e-5:
        return LQuaternionf.identQuat()
    axis.normalize()
    angle = start.angleDeg(end)
    q = _quat(tuple(axis), angle)
    if (q.xform(start) - end).length() > .05:
        q = _quat(tuple(axis), -angle)
    return q


def _rest_rotation(start, end) -> LQuaternionf:
    """Turns the bind pose's arm, which slopes out and down, to hang straight, as the old rig's arms did at zero."""
    return _turn_between(LVector3f(end[0] - start[0], end[1] - start[1], end[2] - start[2]), LVector3f(0.0, -1.0, 0.0))


class CapeChain:
    """Six points joined by fixed lengths: gravity, the air going past, and the shoulders moving under it (verlet).

    It costs a few dozen microseconds, against several milliseconds for a true cloth, and the shader drapes the real
    cloth on the line this gives. It can never pass in front of the body: each point keeps behind the back.
    """

    BEHIND = (0.0, -.10, -.17, -.23, -.28, -.31)  # how far behind the neck each point must stay, down the back

    def __init__(self, length: float) -> None:
        self.segment = length / 5.0
        self.now = [[0.0, -self.segment * i, self.BEHIND[i]] for i in range(6)]
        self.before = [list(p) for p in self.now]
        self.last_velocity = (0.0, 0.0, 0.0)
        self.air_speed = 0.0
        self.tension = 0.0

    def point(self, index: int) -> tuple:
        return tuple(self.now[index])

    def step(self, seconds: float, gravity: tuple, velocity: tuple) -> None:
        dt = max(1.0 / 240.0, min(1.0 / 24.0, seconds))
        vx, vy, vz = velocity
        # Being accelerated pushes hanging cloth the other way, and the air streams past against the motion. Beyond a
        # certain speed air simply pulls it straight, so one number holds from a walk up to a dive at full boost.
        ax = max(-55.0, min(55.0, (vx - self.last_velocity[0]) / dt))
        ay = max(-55.0, min(55.0, (vy - self.last_velocity[1]) / dt))
        az = max(-55.0, min(55.0, (vz - self.last_velocity[2]) / dt))
        self.last_velocity = velocity
        speed = sqrt(vx * vx + vy * vy + vz * vz)
        self.air_speed += (speed - self.air_speed) * min(1.0, dt * 5.0)
        limit = min(1.0, AIR_LIMIT / max(speed, 1e-3))
        airx, airy, airz = -vx * limit, -vy * limit, -vz * limit
        now, before = self.now, self.before
        for index in range(1, 6):
            p, q = now[index], before[index]
            share = .35 + index * .13  # the free end feels the air most
            for axis, (g, a, air) in enumerate(((gravity[0], ax, airx), (gravity[1], ay, airy), (gravity[2], az, airz))):
                moving = (p[axis] - q[axis]) / dt
                force = g - a * .35 + (air - moving) * AIR_PULL * share
                q[axis] = p[axis]
                p[axis] += moving * dt * CLOTH_DAMPING + force * dt * dt
        pull = 0.0
        for _ in range(2):
            for index in range(1, 6):
                a, b = now[index - 1], now[index]
                dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                length = sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
                fix = (length - self.segment) / length
                if index == 1:
                    b[0] -= dx * fix
                    b[1] -= dy * fix
                    b[2] -= dz * fix
                else:
                    half = fix * .5
                    a[0] += dx * half
                    a[1] += dy * half
                    a[2] += dz * half
                    b[0] -= dx * half
                    b[1] -= dy * half
                    b[2] -= dz * half
                if b[2] > self.BEHIND[index]:
                    b[2] = self.BEHIND[index]
                pull += abs(fix)
        reach = sqrt(sum(value * value for value in now[5])) / (self.segment * 5.0)
        self.tension = max(0.0, min(1.0, (reach - .86) / .13)) * min(1.0, self.air_speed / 12.0)


class Bone:
    """Entity-style rotation_x and rotation_z on a bone, as the game's body code has always used them."""

    __slots__ = ("node", "_x", "_y", "_z", "_shown_y", "_rest", "_rest_inverse", "_after", "_bias_z", "_bias_x", "_first", "_tolerance", "_shown_x", "_shown_z")

    def __init__(self, node: NodePath, rest: LQuaternionf | None = None, relative_rest: LQuaternionf | None = None, after=None,
                 bias_z: float = 0.0, bias_x: float = 0.0, first: LQuaternionf | None = None, tolerance: float = 0.0) -> None:
        self.node = node
        self._tolerance = tolerance  # secondary motion only moves its bone for a change that could be seen
        self._shown_x = self._shown_y = self._shown_z = 1e9
        self._y = 0.0
        self._bias_z = bias_z
        self._bias_x = bias_x
        self._first = first  # applied before anything else: a forearm made straight with its upper arm
        self._x = 0.0
        self._z = 0.0
        self._rest = rest
        self._rest_inverse = relative_rest
        self._after = after
        self._apply()

    def _apply(self) -> None:
        if (abs(self._x - self._shown_x) < self._tolerance and abs(self._z - self._shown_z) < self._tolerance
                and abs(self._y - self._shown_y) < self._tolerance):
            return
        self._shown_x, self._shown_y, self._shown_z = self._x, self._y, self._z
        directions = Entity.rotation_directions
        game = LQuaternionf()
        game.setHpr((self._y * directions[1], (self._x + self._bias_x) * directions[1], (self._z + self._bias_z) * directions[2]))
        if self._rest is None:
            self.node.setQuat(game)
        elif self._rest_inverse is None:
            self.node.setQuat(self._rest * game)
        else:  # a forearm: bends in the same axes as if the arm hung straight
            self.node.setQuat(self._first * self._rest * game * self._rest_inverse)
        if self._after is not None:
            self._after(self._x, self._z)

    def _follow(self) -> None:
        self._after(self._x, self._z)

    @property
    def rotation_x(self) -> float:
        return self._x

    @rotation_x.setter
    def rotation_x(self, value: float) -> None:
        if value != self._x:
            self._x = value
            self._apply()

    @property
    def rotation_y(self) -> float:
        return self._y

    @rotation_y.setter
    def rotation_y(self, value: float) -> None:
        if value != self._y:
            self._y = value
            self._apply()

    @property
    def rotation_z(self) -> float:
        return self._z

    @rotation_z.setter
    def rotation_z(self, value: float) -> None:
        if value != self._z:
            self._z = value
            self._apply()


class Marker:
    """A world-position view of a point on the body, as the beams expect of an eye."""

    __slots__ = ("node",)

    def __init__(self, node: NodePath) -> None:
        self.node = node

    @property
    def world_position(self) -> Vec3:
        return Vec3(*self.node.getPos(scene))


_cape_sheets: dict = {}


def _sheet_from(pixels: np.ndarray, name: str) -> Texture:
    """A texture from an RGB array whose first row is the top of the picture."""
    height, width, _ = pixels.shape
    data = (np.clip(pixels[::-1, :, ::-1], 0.0, 1.0) * 255.0 + .5).astype(np.uint8)  # Panda stores BGR, bottom row first
    texture = Texture(name)
    texture.setup2dTexture(width, height, Texture.TUnsignedByte, Texture.FRgb)
    texture.setRamImage(data.tobytes())
    texture.setMinfilter(SamplerState.FT_linear_mipmap_linear)
    texture.setAnisotropicDegree(4)
    return texture


def _flag_texture() -> Texture:
    if "flag" in _cape_sheets:
        return _cape_sheets["flag"]
    width, height = 512, 256
    rows = np.arange(height)
    pixels = np.zeros((height, width, 3), dtype=np.float32)
    red = (rows / height * 13.0).astype(np.int32) % 2 == 0
    pixels[red] = (.69, .10, .12)
    pixels[~red] = (.93, .93, .90)
    field_w, field_h = int(width * .42), int(height * 7 / 13)
    pixels[:field_h, :field_w] = (.09, .16, .36)
    star = 4
    for row in range(9):
        for col in range(11 if row % 2 == 0 else 10):
            cx = int((col + (.5 if row % 2 == 0 else 1.0)) * field_w / 11.0)
            cy = int((row + .6) * field_h / 9.6)
            for dy in range(-star, star + 1):
                span = star - abs(dy)
                pixels[cy + dy, cx - span:cx + span + 1] = (.94, .94, .90)
    _cape_sheets["flag"] = _sheet_from(pixels, "flag-cape")
    return _cape_sheets["flag"]


def _cloth_texture(tint, trim) -> Texture:
    key = (tint, trim)
    if key not in _cape_sheets:
        size = 256
        y, x = np.mgrid[0:size, 0:size].astype(np.float32)
        fold = .92 + .10 * np.sin(x * .19) * np.sin(y * .07 + x * .02) + .02 * np.sin(x * 1.4) * np.sin(y * 1.4)
        edge = (np.minimum(x, size - 1 - x) < 8) | (y > size - 9)
        pixels = np.where(edge[..., None], np.array(trim, dtype=np.float32), np.array(tint, dtype=np.float32)) * fold[..., None]
        _cape_sheets[key] = _sheet_from(pixels, "cloth")
    return _cape_sheets[key]


CAPE_COLORS = {
    **{item.character_id: item.cape_colors for item in definitions() if item.kit.cape},
    "VILTRUMITE_1": ((.93, .93, .92), (.65, .66, .70)),
    "VILTRUMITE_4": ((.93, .93, .92), (.65, .66, .70)),
}


class SkinnedVisual:
    """One character's body. Offers everything the older CloneVisual did, so nothing above it has to know."""

    def __init__(self, owner: NodePath, name: str) -> None:
        self.name = name
        self.kit = kit_of(name)
        self.stance = STANCES.get(name, DEFAULT_STANCE)
        self.style = style_of(name)
        self.rig = json.loads((_folder(name) / "rig.json").read_text(encoding="utf-8"))
        self.pose_root = owner.attachNewNode(f"{name.lower()}-pose-root")
        self.body_root = self.pose_root.attachNewNode("body-root")  # what getting up off the ground tips
        self.model = NodePath(_load_model(name))
        self.model.reparentTo(self.body_root)
        self._apply_materials()
        self.character = self.model.node()
        self.bundle = self.character.getBundle(0)
        self._controls: dict[str, NodePath] = {}
        self._build_controls()
        self._build_limbs()
        self.eye_left = Marker(self._marker("eye-left", self.rig["eyes"][0], "head"))
        self.eye_right = Marker(self._marker("eye-right", self.rig["eyes"][1], "head"))
        self.lock_joints: list = []
        self.is_near = True
        self._cape_nodes: list = []
        self.cape = self._build_cape()
        if not self.kit.cape:
            self.cape.node.hide()
        self._shield = self._build_shield() if self.kit.shield_parts else None
        helmets = self.model.findAllMatches("**/helmet")
        self._helmet = self.model.attachNewNode("helmet-set") if helmets.getNumPaths() else None
        self._helmet_parts = helmets
        if self._helmet is not None:
            self.set_helmet(False)
        self._time = (hash(name) & 255) * .1
        self._speed = 0.0
        self._lean = 0.0
        self._turn_lean = 0.0
        self._flinch = 0.0
        self._flinch_side = 0.0
        self._strike_twist = 0.0
        self._recovery = 0.0
        self.set_breathing(0.0, 0.0, False)

    # -- construction -------------------------------------------------------------------------------------
    def _apply_materials(self) -> None:
        albedo, material, normal = _sheet(self.name, "albedo"), _sheet(self.name, "material"), _sheet(self.name, "normal")
        strands = _load_texture(ASSETS / "strands.png")
        strands.setMinfilter(SamplerState.FT_linear_mipmap_linear)
        eye = _load_texture(_folder(self.name) / "eye.jpg")
        for path in self.model.findAllMatches("**/body"):
            _skin_state(path, SKIN_SHADER)
            path.setShaderInput("u_albedo", albedo)
            path.setShaderInput("u_material", material)
            path.setShaderInput("u_normal", normal)
        for path in self.model.findAllMatches("**/hair"):
            _skin_state(path, HAIR_SHADER)
            path.setShaderInput("u_albedo", strands)
            path.setTransparency(TransparencyAttrib.MBinary)
            path.setTwoSided(True)
        for path in (*self.model.findAllMatches("**/gear"), *self.model.findAllMatches("**/helmet")):
            _skin_state(path, GEAR_SHADER)
        flat_material = _flat_material()
        flat_normal = _flat_normal()
        for path in self.model.findAllMatches("**/eyes"):
            _skin_state(path, SKIN_SHADER)
            path.setShaderInput("u_albedo", eye)
            path.setShaderInput("u_material", flat_material)
            path.setShaderInput("u_normal", flat_normal)

    def _build_controls(self) -> None:
        for name, joint in self.rig["joints"].items():
            parent = self._controls[joint["parent"]] if joint["parent"] else self.body_root
            node = parent.attachNewNode(ModelNode(f"bone-{name}"))
            node.setPos(*joint["offset"])
            self.bundle.controlJoint(name, node.node())
            self._controls[name] = node

    def _build_limbs(self) -> None:
        joints = self.rig["joints"]
        c = self._controls

        def arm(side: str):
            rest = _rest_rotation(joints[f"upperarm_{side}"]["at"], joints[f"lowerarm_{side}"]["at"])
            inverse = LQuaternionf(rest)
            inverse.invertInPlace()
            out = self.stance["arms_out"] * (1.0 if side == "l" else -1.0)  # broad arms do not hang against the ribs
            node = c[f"upperarm_{side}"]
            at_rest = node.getPos()

            def shrug(x: float, _z: float) -> None:
                # A raised arm takes its collarbone with it: the shoulder rises instead of the skin stretching.
                node.setY(at_rest[1] + SHOULDER_LIFT * (1.0 - cos(radians(x))) * .5)

            shoulder = Bone(node, rest, bias_z=out, after=shrug)
            # The bind pose's forearm bends forward at the elbow. Zero means straight, as it always has to the game.
            upper = LVector3f(*joints[f"lowerarm_{side}"]["at"]) - LVector3f(*joints[f"upperarm_{side}"]["at"])
            lower = LVector3f(*joints[f"hand_{side}"]["at"]) - LVector3f(*joints[f"lowerarm_{side}"]["at"])
            straight = _turn_between(lower, upper)
            elbow = Bone(c[f"lowerarm_{side}"], rest, inverse, bias_x=-14.0, first=straight)
            return shoulder, elbow

        self.left_arm, self.left_elbow = arm("l")
        self.right_arm, self.right_elbow = arm("r")
        self.left_knee = Bone(c["calf_l"], tolerance=SECONDARY_TOLERANCE)
        self.right_knee = Bone(c["calf_r"], tolerance=SECONDARY_TOLERANCE)
        self.left_foot = Bone(c["foot_l"], tolerance=SECONDARY_TOLERANCE)
        self.right_foot = Bone(c["foot_r"], tolerance=SECONDARY_TOLERANCE)
        self._gait_phase = 0.0
        self._gait = 0.0         # 0 standing or posed by an attack, 1 walking or running
        self._gait_bend = 30.0
        self._gait_knees = [0.0, 0.0]    # left, right: what the feet need of each leg
        self._gait_pitches = [0.0, 0.0]
        self._walk_roll = 0.0
        self.gait_plan = None
        self._squat = 0.0        # the crouch of taking off and of landing, from 0 to 1
        self._grounded = True
        self._together = 0.0     # 1: legs straight and side by side, as a body flies
        self._pointed = 0.0      # 1: toes pointing down the line of the leg
        hip, knee, ankle = (joints[name]["at"] for name in ("thigh_l", "calf_l", "foot_l"))
        self._thigh_length = sqrt(sum((a - b) ** 2 for a, b in zip(hip, knee)))
        self._shin_length = sqrt(sum((a - b) ** 2 for a, b in zip(knee, ankle)))
        self._pelvis_rest = c["pelvis"].getPos()
        self._pelvis = Bone(c["pelvis"], tolerance=SECONDARY_TOLERANCE)
        self._leg_shape = leg_shape(hip, knee, ankle)

        def leg_follows(knee_bone: Bone, foot: Bone, index: int):
            def follow(x: float, _z: float) -> None:
                # An attack or flight pose bends the knee by the leg's angle. Walking takes what the foot's place needs.
                posed = (max(0.0, -x) * .62 if x < 0.0 else x * .35) * (1.0 - self._together)
                gait = self._gait
                bend = posed + (self._gait_knees[index] - posed) * gait + self._squat * 62.0
                knee_bone.rotation_x = bend
                # A standing foot lies flat on the ground, whatever the thigh and shin above it are doing.
                held = -(x + bend) * (.85 if self._grounded else .25) + self._pointed * POINTED_FEET
                foot.rotation_x = held + (self._gait_pitches[index] - (x + bend) - held) * gait
            return follow

        self.left_leg = Bone(c["thigh_l"], after=leg_follows(self.left_knee, self.left_foot, 0))
        self.right_leg = Bone(c["thigh_r"], after=leg_follows(self.right_knee, self.right_foot, 1))
        # The legs meet at the feet: how far each thigh has to turn in is this body's own hips and ankles.
        hip_x, ankle_x = abs(joints["thigh_l"]["at"][0]), abs(joints["foot_l"]["at"][0])
        self._close_legs = degrees(atan2(max(0.0, ankle_x - TOGETHER_ANKLE), joints["thigh_l"]["at"][1] - joints["foot_l"]["at"][1]))
        self._spine = Bone(c["spine_03"], tolerance=SECONDARY_TOLERANCE)
        self._lower = Bone(c["spine_01"], tolerance=SECONDARY_TOLERANCE)
        self._neck = Bone(c["neck_01"], tolerance=SECONDARY_TOLERANCE)
        self._head = Bone(c["head"], tolerance=SECONDARY_TOLERANCE)
        self._legs_at_rest = True

    def _marker(self, name: str, position, bone: str) -> NodePath:
        marker = self.pose_root.attachNewNode(name)
        marker.setPos(*position)
        return marker

    def _build_cape(self):
        from characters.sentry_clone import Joint
        joints = self.rig["joints"]
        anchor = self._controls["spine_03"].attachNewNode("cape")
        neck = joints["neck_01"]["at"]
        chest = joints["spine_03"]["at"]
        anchor.setPos(0.0, neck[1] - chest[1] - .03, neck[2] - chest[2] - .15)
        self._chain = CapeChain(CAPE_LENGTH)
        if not self.kit.cape:
            return Joint(anchor)
        rows, cols = 16, 11
        vertices, uvs, triangles = [], [], []
        for row in range(rows):
            for col in range(cols):
                u, t = col / (cols - 1), row / (rows - 1)
                # Where it really is comes from the chain, in the shader. This only has to be big enough for culling.
                vertices.append(((u * 2.0 - 1.0) * .5, -t * CAPE_LENGTH, -.3 * t))
                uvs.append((u, t))
        for row in range(rows - 1):
            for col in range(cols - 1):
                i = row * cols + col
                triangles.extend((i, i + cols, i + 1, i + 1, i + cols, i + cols + 1))
        mesh = Mesh(vertices=vertices, triangles=triangles, uvs=uvs, static=True)
        part = Entity(model=mesh, shader=CAPE_PBR_SHADER, color=color.white, double_sided=True, add_to_scene_entities=False, collider=None)
        part.reparentTo(anchor)
        part.node().setBounds(BoundingSphere((0.0, -CAPE_LENGTH * .5, 0.0), CAPE_LENGTH * 1.3))
        part.node().setFinal(True)
        sheet = _folder(self.name) / "cape.jpg"
        part.setShaderInput("u_albedo", _load_texture(sheet) if sheet.exists() else _cloth_texture((.5, .5, .5), (.4, .4, .4)))
        self._chain_points = PTA_LVecBase3f.emptyArray(6)
        for index in range(6):
            self._chain_points.setElement(index, LVecBase3f(*self._chain.point(index)))
        part.setShaderInput("u_chain", self._chain_points)
        part.setShaderInput("u_cape_shape", LVecBase4f(CAPE_TOP_HALF, CAPE_HEM_HALF, 0.0, 1.0))
        self._cape_nodes.append(part)
        self._cape_anchor = anchor
        return Joint(anchor)

    def _build_shield(self) -> NodePath:
        """Soldier Boy's heater shield, strapped to his left forearm, with its star and eagle wings in relief."""
        from panda3d.core import GeomNode
        forearm = self._controls["lowerarm_l"]
        shield = forearm.attachNewNode("shield")
        joints = self.rig["joints"]
        rest = _rest_rotation(joints["upperarm_l"]["at"], joints["lowerarm_l"]["at"])
        upper = LVector3f(*joints["lowerarm_l"]["at"]) - LVector3f(*joints["upperarm_l"]["at"])
        lower = LVector3f(*joints["hand_l"]["at"]) - LVector3f(*joints["lowerarm_l"]["at"])
        inverse = _turn_between(lower, upper) * rest  # undoes what the forearm's frame carries, so it hangs square to him
        inverse.invertInPlace()
        shield.setQuat(inverse)
        # Outline of a heater shield, as a shallow dome so that it catches the light.
        outline = [(-.34, .30), (.34, .30), (.34, -.02), (.22, -.26), (0.0, -.46), (-.22, -.26), (-.34, -.02)]
        vertices, triangles, colors = [(0.0, 0.0, .07)], [], [color.rgb(.36, .40, .34)]
        rings = ((1.0, .0, (.20, .23, .18)), (.86, .035, (.46, .50, .44)), (.42, .06, (.36, .40, .34)))
        for scale, lift, tone in rings:
            for x, y in outline:
                vertices.append((x * scale, y * scale, lift))
                colors.append(color.rgb(*tone))
        count = len(outline)
        for ring in range(len(rings) - 1):
            for i in range(count):
                a, b = 1 + ring * count + i, 1 + ring * count + (i + 1) % count
                c, d = a + count, b + count
                triangles.extend((a, b, d, a, d, c))
        last = 1 + (len(rings) - 1) * count
        for i in range(count):
            triangles.extend((last + i, last + (i + 1) % count, 0))
        body = Entity(model=Mesh(vertices=vertices, triangles=triangles, colors=colors, static=True), color=color.white, double_sided=True, unlit=False,
                      add_to_scene_entities=False, collider=None)
        body.reparentTo(shield)
        # An eagle in relief: spread wings, body and head.
        star_points = [(0.0, -.17, .085), (-.05, .03, .085), (-.29, .17, .085), (-.2, .03, .085), (-.27, .01, .085), (-.12, -.07, .085),
                       (.05, .03, .085), (.29, .17, .085), (.2, .03, .085), (.27, .01, .085), (.12, -.07, .085), (0.0, .13, .09), (.05, .09, .09)]
        star_tris = [0, 1, 5, 1, 3, 5, 1, 2, 3, 3, 4, 5, 0, 10, 6, 6, 10, 8, 6, 8, 7, 8, 10, 9, 0, 6, 1, 1, 6, 11, 6, 12, 11]
        gold = color.rgb(.66, .53, .28)
        star = Entity(model=Mesh(vertices=star_points, triangles=star_tris, colors=[gold] * len(star_points), static=True), color=color.white, double_sided=True,
                      add_to_scene_entities=False, collider=None)
        star.reparentTo(shield)
        # Across the front of the forearm, in the axes of an arm hanging straight down.
        shield.setPos(inverse.xform(LVector3f(.02, -.24, .17)))
        return shield

    def _build_helmet(self) -> NodePath:
        from ursina import load_model
        head = self._controls["head"]
        at = self.rig["joints"]["head"]["at"]
        top = self.rig["eyes"][0][1] + .13
        helmet = load_model("sphere").copyTo(head)
        helmet.setPos(0.0, top - at[1], .03)
        helmet.setScale(.40, .28, .44)
        helmet.setColorScale(.22, .26, .17, 1.0)
        helmet.hide()
        return helmet

    # -- what the game calls ------------------------------------------------------------------------------
    def set_shield(self, visible: bool) -> None:
        if self._shield is not None:
            (self._shield.show() if visible else self._shield.hide())

    def set_helmet(self, visible: bool) -> None:
        if self._helmet is not None:
            (self._helmet.show() if visible else self._helmet.hide())
            for path in self._helmet_parts:
                (path.show() if visible else path.hide())

    def set_cape_wind(self, time: float, wind: float, forward: float, right: float) -> None:
        """Move the cape with what the body is doing now: only the characters' own cape step knows real velocities."""
        self.step_cape(1.0 / 60.0, (0.0, 0.0, 0.0))

    def step_cape(self, seconds: float, world_velocity: tuple) -> None:
        """One step of the cape's chain, in the frame of the shoulders it hangs from."""
        if not self._cape_nodes:
            return
        anchor = self._cape_anchor
        gravity = anchor.getRelativeVector(scene, LVector3f(0.0, -CAPE_GRAVITY, 0.0))
        velocity = anchor.getRelativeVector(scene, LVector3f(*world_velocity))
        self._chain.step(seconds, tuple(gravity), tuple(velocity))
        points = self._chain_points
        for index in range(6):
            x, y, z = self._chain.point(index)
            points.setElement(index, LVecBase3f(x, y, z))
        wind = min(1.0, self._chain.air_speed / 45.0)
        slack = max(.12, 1.0 - self._chain.tension)
        for part in self._cape_nodes:
            part.setShaderInput("u_cape_shape", LVecBase4f(CAPE_TOP_HALF, CAPE_HEM_HALF * (1.0 - wind * .1), wind, slack))

    def set_detail(self, near: bool) -> None:
        """Distance is the LOD node's business; a far body still skips its breathing."""
        self.is_near = near

    def set_gait(self, phase: float, amount: float, running: float, grounded: bool) -> None:
        """Not walking: in the air, or standing. Whatever walking left in the hips and spine goes with it."""
        self._gait_phase = phase
        self._gait = amount
        self._grounded = grounded
        if self._walk_roll or self._pelvis.rotation_y or self._spine.rotation_y:
            self._walk_roll = 0.0
            self._pelvis.rotation_y = self._pelvis.rotation_z = 0.0
            self._lower.rotation_y = self._spine.rotation_y = self._neck.rotation_y = 0.0
            self.left_leg.rotation_y = self.right_leg.rotation_y = 0.0
            self.left_leg.rotation_z = self.right_leg.rotation_z = 0.0

    def walk(self, seconds: float, along_x: float, along_z: float, turning: float) -> tuple[float, float, float, float, float]:
        """One frame of the cycle, from the body's real velocity in its own frame and how fast it is turning, in radians.

        Returns the thigh angles the legs should have, the arms' swing, and how much of a run this is.
        """
        shape, style = self._leg_shape, self.style
        speed = hypot(along_x, along_z)
        # Turning on the spot still takes steps; a body does not pivot on planted feet.
        pace = max(speed, abs(turning) * TURN_STEP)
        plan = plan_for(pace, shape, style.step, style.stride)
        self.gait_plan = plan
        amount = max(0.0, min(1.0, (pace - WALK_STARTS) / (WALK_FULL - WALK_STARTS)))
        amount = amount * amount * (3.0 - 2.0 * amount)
        self._gait_phase += 2.0 * pi * plan.frequency * seconds
        self._gait = amount
        self._grounded = True
        if amount <= 0.0:
            self.set_gait(self._gait_phase, 0.0, 0.0, True)
            self._gait_knees[0] = self._gait_knees[1] = self._gait_pitches[0] = self._gait_pitches[1] = 0.0
            return 0.0, 0.0, 0.0, 0.0, 0.0
        if speed > .05:
            forward, sideways = along_z / speed, along_x / speed
        else:
            forward, sideways = 1.0, 0.0
        cycle = self._gait_phase / (2.0 * pi)
        beat = 2.0 * pi * cycle
        # The hip goes forward with its leg, and the hip over the planted foot rides higher.
        yaw = plan.hip_yaw * cos(beat) * forward * amount
        roll = plan.hip_roll * sin(beat) * amount
        width = shape.hip_half_width
        hip_forward = width * sin(radians(yaw))
        hip_up = width * sin(radians(roll))
        # The weight rises over a planted leg at a walk, and in the air at a run.
        bob = plan.bob * cos(2.0 * beat) * (1.0 - 2.0 * plan.running) * amount
        drop = plan.hip_drop * amount
        rest = self._pelvis_rest
        sway = -plan.sway * sin(beat) * amount
        self._controls["pelvis"].setPos(rest[0] + sway, rest[1] - drop + bob, rest[2])
        self._pelvis.rotation_y = yaw
        self._pelvis.rotation_z = roll
        self._lower.rotation_y = -yaw * .55
        self._spine.rotation_y = -yaw * 1.35   # the shoulders turn against the hips
        self._neck.rotation_y = yaw * .45      # and the head keeps looking where it is going
        self._walk_roll = roll
        thighs = [0.0, 0.0]
        for index, side, phase in ((0, 1.0, cycle), (1, -1.0, cycle + .5)):
            along, up, pitch = foot_at(phase, plan, shape)
            thigh, knee, foot = leg_angles(shape, along * forward, up, shape.hip_z + side * hip_forward,
                                           shape.hip_y - drop + bob + side * hip_up, pitch * max(0.0, forward))
            thighs[index] = thigh * amount
            self._gait_knees[index] = knee
            self._gait_pitches[index] = pitch * max(0.0, forward)
            # The legs hang from the pelvis, so they undo its turn, roll and sway: a planted foot takes no part in them.
            leg = self.left_leg if index == 0 else self.right_leg
            leg.rotation_y = -yaw
            leg.rotation_z = -degrees(atan2(along * sideways * amount - sway, shape.hip_y - drop + bob)) - roll
        swing = (ARM_SWING_WALK + (ARM_SWING_RUN - ARM_SWING_WALK) * plan.running) * style.arm_swing * amount
        return thighs[0], thighs[1], swing * cos(beat + ARM_LAG), -swing * cos(beat + ARM_LAG), plan.running * amount

    def hold_legs(self, together: float, pointed: float, blend: float) -> None:
        """Eased in from wherever the legs were, so going from a run to flight never snaps. Applies over any leg pose."""
        before = self._together, self._pointed
        self._together += (together - self._together) * blend
        self._pointed += (pointed - self._pointed) * blend
        if abs(self._together - before[0]) + abs(self._pointed - before[1]) < 1e-3:
            return
        angle = self._close_legs * self._together
        self.left_leg._bias_z = -angle
        self.right_leg._bias_z = angle
        self.left_leg._shown_x = self.right_leg._shown_x = 1e9
        self.left_leg._apply()
        self.right_leg._apply()

    def squat(self, amount: float) -> None:
        """The legs take a landing, or gather for a leap; it eases out by itself."""
        self._squat = max(self._squat, min(1.0, amount * self.style.land_depth))

    def flinch(self, amount: float, side: float) -> None:
        """A blow rocks the upper body back, and to the side it came from."""
        self._flinch = max(self._flinch, min(1.0, amount))
        self._flinch_side = side

    def strike_twist(self, degrees: float) -> None:
        """Shoulders and hips go into a punch or a kick."""
        self._strike_twist = degrees

    def recover_from(self, pitch: float) -> None:
        """Back on the feet from however a tumble left the body, instead of snapping upright."""
        self._recovery = ((pitch + 180.0) % 360.0) - 180.0
        self.body_root.setP(self._recovery)

    def foot_is_planted(self, index: int) -> bool:
        """0 left, 1 right: is this foot in the part of its cycle that carries weight?"""
        plan = self.gait_plan
        return plan is not None and (self._gait_phase / (2.0 * pi) + (.5 if index else 0.0)) % 1.0 < plan.duty

    def _plant_pelvis(self) -> None:
        """The hips drop as far as the longer leg needs, so that a foot is on the ground all through the stride."""
        if self._gait > .01:
            return  # walking places the hips itself
        if not self._grounded:
            self._controls["pelvis"].setPos(self._pelvis_rest)
            return
        thigh, shin = self._thigh_length, self._shin_length
        left, right = self.left_leg.rotation_x, self.right_leg.rotation_x
        left_drop = thigh * cos(radians(left)) + shin * cos(radians(left + self.left_knee.rotation_x))
        right_drop = thigh * cos(radians(right)) + shin * cos(radians(right + self.right_knee.rotation_x))
        rest = self._pelvis_rest
        self._controls["pelvis"].setPos(rest[0], rest[1] + max(left_drop, right_drop) - (thigh + shin), rest[2])

    def set_breathing(self, seconds: float, speed: float, airborne: bool, turning: float = 0.0, speeding_up: float = 0.0) -> None:
        """Spine, neck and head: the stance, a slow breath, a lean into a run, into a turn and into a change of speed."""
        self._time += seconds
        self._speed += (speed - self._speed) * min(1.0, seconds * 6.0)
        stance, style = self.stance, self.style
        running = min(1.0, self._speed / 14.0) if not airborne else 0.0
        pull = max(-14.0, min(16.0, speeding_up * .14)) if not airborne else 0.0
        self._lean += (stance["run_lean"] * running + pull - self._lean) * min(1.0, seconds * 6.0)
        self._turn_lean += (max(-12.0, min(12.0, turning * .05)) * running - self._turn_lean) * min(1.0, seconds * 8.0)
        self._squat *= exp(-seconds * 5.0)
        self._flinch *= exp(-seconds * 7.0)
        self._strike_twist *= exp(-seconds * 9.0)
        if self._recovery:
            self._recovery *= exp(-seconds * 6.5)
            if abs(self._recovery) < .5:
                self._recovery = 0.0
            self.body_root.setP(self._recovery)
        breath = sin(self._time * style.breath_rate) * .9
        carried = WALK_FORWARD * min(1.0, self._speed / 2.0) if not airborne else 0.0  # weight over the front foot
        chest = stance["chest"] + breath + self._lean * .55 - self._flinch * 24.0 + carried * .6
        self._spine.rotation_x = chest
        self._spine.rotation_z = self._turn_lean * .6 + self._flinch * self._flinch_side * 14.0
        self._lower.rotation_x = self._lean * .45 + self._squat * 24.0 + carried
        self._lower.rotation_z = self._turn_lean * .4 - self._walk_roll * .7 + (0.0 if airborne else sin(self._time * .55) * style.idle_sway * (1.0 - running))
        self._neck.rotation_x = -self._lean * .25
        self._head.rotation_x = stance["head"] - self._lean * .35 + breath * .3 - self._squat * 12.0 + self._flinch * 10.0
        if self._strike_twist:
            self._controls["spine_03"].setH(self._controls["spine_03"].getH() + self._strike_twist)
        # Legs at rest and not squatting, the common case by far, cost nothing at all.
        squatting = self._squat > .01
        at_rest = not squatting and self._gait < .01 and self.left_leg.rotation_x == 0.0 and self.right_leg.rotation_x == 0.0
        if at_rest and self._legs_at_rest:
            return
        self._legs_at_rest = at_rest
        if squatting:
            self.left_leg._follow()
            self.right_leg._follow()
            bend = -self._squat * 34.0 * Entity.rotation_directions[1]
            for bone in (self.left_leg, self.right_leg):
                bone.node.setP(bone.node.getP() + bend)
        self._plant_pelvis()


_model_cache: dict = {}


def _load_model(name: str):
    """One master per character, copied: a body built twice shares its geometry, and its joints stay its own."""
    path = _folder(name) / "model.bam"
    master = _model_cache.get(name)
    if master is None:
        from panda3d.core import BamFile
        reader = BamFile()
        reader.openRead(Filename.fromOsSpecific(str(path)))
        node = reader.readNode()
        reader.close()
        _model_cache[name] = master = NodePath(node)
    return master.copyTo(NodePath("holder")).node()


def _skin_state(path: NodePath, shader: Shader) -> None:
    if not shader.compiled:
        shader.compile()
    attrib = ShaderAttrib.make(shader._shader)
    attrib = attrib.setFlag(ShaderAttrib.F_hardware_skinning, True)
    path.setAttrib(attrib)
    for key, value in shader.default_input.items():
        path.setShaderInput(key, value() if callable(value) else value)


_shared: dict = {}


def _flat_material() -> Texture:
    if "material" not in _shared:
        texture = Texture("flat-material")
        texture.setup2dTexture(1, 1, Texture.TUnsignedByte, Texture.FRgb)
        texture.setRamImage(bytes((0, 0, 70)))  # stored BGR: rough .27, not metal, not skin
        _shared["material"] = texture
    return _shared["material"]


def _flat_normal() -> Texture:
    if "normal" not in _shared:
        texture = Texture("flat-normal")
        texture.setup2dTexture(1, 1, Texture.TUnsignedByte, Texture.FRgb)
        texture.setRamImage(bytes((255, 128, 128)))
        _shared["normal"] = texture
    return _shared["normal"]
