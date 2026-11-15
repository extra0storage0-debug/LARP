"""Recoloured, batched copies of the first built body for AI characters.

The body is copied from the player's own scene graph, never rebuilt, so a clone
cannot drift from the original model. The face and hair batches are instanced by
every clone; only costume-coloured geometry exists per clone. Parts on one rigid
joint are flattened together so six extra Sentries add tens of draw calls, not
hundreds, and a low-poly set stands in beyond NEAR_DISTANCE.
"""

from __future__ import annotations

from dataclasses import dataclass

from characters.registry import BASE_BODY, definition, definitions
from math import cos, pi, sin

from panda3d.core import GeomNode, GeomVertexRewriter, ModelNode, NodePath, ShaderAttrib
from ursina import Entity, Mesh, Shader, Vec3, color, load_model, scene
from ursina.shaders import lit_with_shadows_shader

from characters.roster import KITS, kit_of
from characters.sentry_shader import SENTRY_LIGHT_SHADER

NEAR_DISTANCE = 18.0
WAIST_S_NODE = "raised-gold-waist-s"
CHEST_S_POSITION = (0.0, 1.70, .425)
LIMB_JOINTS = ("left_arm", "right_arm", "left_leg", "right_leg")
ELBOWS = {"left_arm": "left_elbow", "right_arm": "right_elbow"}
TORSO_NODE = "sculpted-gold-torso"
FINE_HAIR_NODES = ("golden-hair-highlights", "golden-hair-shadows")


def _rgb(r: int, g: int, b: int) -> tuple[float, float, float]:
    return (r / 255.0, g / 255.0, b / 255.0)


@dataclass(frozen=True, slots=True)
class CostumePalette:
    """One costume. Field names follow the roles colours play on the original."""
    name: str
    suit: tuple[float, float, float]        # shoulders, upper arms, thighs
    suit_light: tuple[float, float, float]  # lit side of the sculpted torso
    suit_shadow: tuple[float, float, float] # shaded side of the sculpted torso
    accent: tuple[float, float, float]      # gloves, boots, belt, forearms, briefs
    trim: tuple[float, float, float]        # belt rim, cape piping and emblems
    cape: tuple[float, float, float]        # cape cloth
    display: str = ""                       # the name players see


# name is the character's game slot, which AI, kits and tests key on. Everyone but the first body, in the order they were first built.
CLONE_PALETTES = tuple(CostumePalette(item.character_id, *item.palette, item.kit.display)
                       for item in sorted(definitions(), key=lambda item: item.seed) if item.character_id != BASE_BODY)

# Only ever seen as Sentry's Void copy. He himself is the original model, not a clone of it.
SENTRY_COPY_PALETTE = CostumePalette(BASE_BODY, *definition(BASE_BODY).palette, definition(BASE_BODY).kit.display)

_VILTRUMITE_SUIT = (_rgb(232, 232, 230), _rgb(248, 248, 246), _rgb(205, 206, 210),
                    _rgb(216, 218, 222), _rgb(176, 180, 188), _rgb(236, 236, 234))
HEAD_SKIN = _rgb(205, 157, 128)  # the tone the shared head is authored in
# Omni-Man's squad. Built only the first time they are needed.
SQUAD_PALETTES = (
    *(CostumePalette(f"VILTRUMITE_{index}", *_VILTRUMITE_SUIT, "VILTRUMITE") for index in range(1, 6)),
    CostumePalette("INVINCIBLE", _rgb(24, 66, 150), _rgb(236, 196, 40), _rgb(186, 150, 28),
                   _rgb(20, 54, 128), _rgb(16, 16, 20), _rgb(24, 66, 150), "INVINCIBLE"),
)

# The original's authored colours identify which costume role a part plays.
# Skin, eyes, lips, brows and hair use other values and are left untouched.
COSTUME_ROLES = {(220, 153, 24): "suit", (242, 180, 40): "suit_light",
                 (10, 17, 34): "accent", (9, 15, 30): "accent", (8, 13, 27): "accent",
                 (255, 193, 48): "trim", (255, 218, 104): "trim"}

_CAPE_VERTEX = lit_with_shadows_shader.vertex.replace(
    "void main() {\n"
    "    gl_Position = p3d_ModelViewProjectionMatrix * vertex;\n"
    "    vertex_position = vec3(p3d_ModelViewMatrix * vertex);\n"
    "    vertex_world_position = (p3d_ModelMatrix * vertex).xyz;\n",
    # Same formula as SentryCharacter._deform_cape, run on the GPU. The texture
    # coordinates carry each vertex's column and row in the cape grid.
    "uniform vec4 u_cape_wind;\n"
    "void main() {\n"
    "    float row = p3d_MultiTexCoord0.y;\n"
    "    float wave = sin(u_cape_wind.x * 7.0 + p3d_MultiTexCoord0.x * 24.0 * .72\n"
    "                     + row * 16.0 * .55);\n"
    "    float wind = u_cape_wind.y;\n"
    "    vec4 deformed = vertex;\n"
    "    deformed.x += wave * .055 * wind * row;\n"
    "    deformed.z += row * (u_cape_wind.z + u_cape_wind.w\n"
    "                         - abs(wave) * .34 * wind - max(0.0, wave) * .045 * wind);\n"
    "    gl_Position = p3d_ModelViewProjectionMatrix * deformed;\n"
    "    vertex_position = vec3(p3d_ModelViewMatrix * deformed);\n"
    "    vertex_world_position = (p3d_ModelMatrix * deformed).xyz;\n",
    1)
if "u_cape_wind" not in _CAPE_VERTEX:
    raise RuntimeError("Ursina's shadow shader changed; update the clone cape shader")

CAPE_SHADER = Shader(name="sentry_clone_cape", language=SENTRY_LIGHT_SHADER.language,
                     vertex=_CAPE_VERTEX, fragment=SENTRY_LIGHT_SHADER.fragment,
                     default_input={**SENTRY_LIGHT_SHADER.default_input,
                                    "u_cape_wind": (0.0, 0.0, 0.0, 0.0)},
                     continuous_input=dict(SENTRY_LIGHT_SHADER.continuous_input))


class Joint:
    """Entity-style rotation access on a plain node, for SentryCharacter.simulate."""

    __slots__ = ("node", "_x", "_z")

    def __init__(self, node: NodePath) -> None:
        self.node = node
        self._x = 0.0
        self._z = 0.0

    def _apply(self) -> None:
        directions = Entity.rotation_directions
        self.node.setHpr(0.0, self._x * directions[1], self._z * directions[2])

    @property
    def rotation_x(self) -> float:
        return self._x

    @rotation_x.setter
    def rotation_x(self, value: float) -> None:
        if value != self._x:
            self._x = value
            self._apply()

    @property
    def rotation_z(self) -> float:
        return self._z

    @rotation_z.setter
    def rotation_z(self, value: float) -> None:
        if value != self._z:
            self._z = value
            self._apply()


class EyePoint:
    """World-position view of a head-mounted point, as HeatVision expects."""

    __slots__ = ("node",)

    def __init__(self, node: NodePath) -> None:
        self.node = node

    @property
    def world_position(self) -> Vec3:
        return Vec3(*self.node.getPos(scene))


def _flag_color(across: float, down: float) -> tuple[float, float, float]:
    """Stripes with a blue, star-flecked field at the top corner, for Homelander's cape."""
    if across < .42 and down < .38:
        star = (int(across * 24.0) + int(down * 24.0)) % 3 == 0
        return (.93, .93, .90) if star else _rgb(24, 40, 92)
    return _rgb(176, 24, 30) if int(down * 13.0) % 2 == 0 else (.93, .93, .90)


def costume_role(color_scale) -> str | None:
    key = tuple(round(float(color_scale[i]) * 255.0) for i in range(3))
    return COSTUME_ROLES.get(key)


def _child_path(root: NodePath, node: NodePath) -> tuple[int, ...]:
    """Child indexes leading from root to node, valid on an exact copy of root."""
    path = []
    current = NodePath(node)
    stop = NodePath(root)
    while current != stop:
        parent = current.getParent()
        for index in range(parent.getNumChildren()):
            if parent.getChild(index) == current:
                path.append(index)
                break
        current = parent
    return tuple(reversed(path))


def _follow(root: NodePath, path: tuple[int, ...]) -> NodePath:
    node = root
    for index in path:
        node = node.getChild(index)
    return node


def _net_color(node: NodePath, stop: NodePath) -> tuple[float, float, float, float]:
    """Accumulated colour scale from ``stop`` down to ``node``."""
    r, g, b, a = 1.0, 1.0, 1.0, 1.0
    current = node
    while current != stop and not current.isEmpty():
        if current.hasColorScale():
            scale = current.getColorScale()
            r, g, b, a = r * scale[0], g * scale[1], b * scale[2], a * scale[3]
        current = current.getParent()
    return r, g, b, a


def _uses_costume_color(node: NodePath) -> bool:
    if node.getName() == TORSO_NODE:
        return True
    return any(path.hasColorScale() and costume_role(path.getColorScale())
               for path in (node, *node.findAllMatches("**")))


def _recolor_parts(root: NodePath, palette: CostumePalette) -> None:
    """Swap each costume-coloured node's tint; other nodes keep their colour."""
    for node in (root, *root.findAllMatches("**")):
        if node.hasColorScale():
            role = costume_role(node.getColorScale())
            if role is not None:
                r, g, b = getattr(palette, role)
                node.setColorScale(r, g, b, 1.0)


def _recolor_torso(torso: NodePath, palette: CostumePalette) -> None:
    """Remap the torso's gold vertex shading onto the palette, keeping its shape."""
    dark, light = palette.suit_shadow, palette.suit_light
    for path in torso.findAllMatches("**/+GeomNode"):
        node = path.node()
        for index in range(node.getNumGeoms()):
            data = node.modifyGeom(index).modifyVertexData()
            rewriter = GeomVertexRewriter(data, "color")
            while not rewriter.isAtEnd():
                source = rewriter.getData4f()
                shade = max(0.0, min(1.0, (source[0] - 188.0 / 255.0) / (64.0 / 255.0)))
                rewriter.setData4f(dark[0] + (light[0] - dark[0]) * shade,
                                   dark[1] + (light[1] - dark[1]) * shade,
                                   dark[2] + (light[2] - dark[2]) * shade, 1.0)


def _low_poly_sphere() -> Mesh:
    """A unit-diameter sphere matching Ursina's model, at about 7% of its triangles."""
    rings, sectors = 6, 10
    vertices, normals, triangles = [], [], []
    for ring in range(rings + 1):
        phi = pi * ring / rings
        for sector in range(sectors):
            theta = 2.0 * pi * sector / sectors
            normal = (sin(phi) * cos(theta), cos(phi), sin(phi) * sin(theta))
            normals.append(normal)
            vertices.append(tuple(component * .5 for component in normal))
    for ring in range(rings):
        for sector in range(sectors):
            following = (sector + 1) % sectors
            a, b = ring * sectors + sector, ring * sectors + following
            c, d = (ring + 1) * sectors + following, (ring + 1) * sectors + sector
            # Outward winding: inward faces left far-LOD heads see-through.
            triangles.extend((a, c, b, a, d, c))
    return Mesh(vertices=vertices, normals=normals, triangles=triangles, static=True)


def _merge_batch(group: NodePath) -> None:
    """Bake transforms and tints, then gather every geom so Panda can unify them."""
    group.flattenStrong()
    merged = GeomNode(f"{group.getName()}-merged")
    paths = group.findAllMatches("**/+GeomNode")
    for path in paths:
        merged.addGeomsFrom(path.node())
    for child in tuple(group.getChildren()):
        child.removeNode()
    group.attachNewNode(merged)
    group.flattenStrong()


def _batch_children(owner: NodePath, name: str) -> NodePath:
    """Move owner's current children under one merged batch node."""
    batch = owner.attachNewNode(name)
    for child in tuple(owner.getChildren()):
        if child != batch:
            child.wrtReparentTo(batch)
    _merge_batch(batch)
    return batch


class CloneAssets:
    """Everything extracted once from the player's model and shared by all clones."""

    def __init__(self, template) -> None:
        source = template.pose_root
        joint_paths = {name: _child_path(source, getattr(template, name))
                       for name in (*LIMB_JOINTS, "cape")}
        self.elbow_paths = {arm: _child_path(getattr(template, arm), getattr(template, elbow))
                            for arm, elbow in ELBOWS.items()}
        self.elbow_y = float(template.left_elbow.y)
        eye_paths = (_child_path(source, template.eye_left),
                     _child_path(source, template.eye_right))
        emblem_path = _child_path(template.cape, template.cape_emblem)

        self._holder = NodePath("sentry-clone-assets")
        master = source.copyTo(self._holder)
        master.setHpr(0, 0, 0)
        # The shader ignores Panda materials, and every part uses the same shader
        # with the same inputs. Lifting those to the clone root and unlocking model
        # roots is what allows flattenStrong to merge the parts into few geoms.
        shader_slot = ShaderAttrib.getClassType()
        for node in (master, *master.findAllMatches("**")):
            node.clearMaterial()
            node.node().clearAttrib(shader_slot)
            if isinstance(node.node(), ModelNode):
                node.node().setPreserveTransform(ModelNode.PTNone)
        self.template = template
        self.cape_rows = template._cape_rows
        self.cape_cols = template._cape_cols
        self.cape_vertices = list(template._cape_vertices)
        self.cape_trim = template._cape_trim_geometry(self.cape_vertices)

        joints = {name: _follow(master, path) for name, path in joint_paths.items()}
        for joint in joints.values():
            joint.setHpr(0, 0, 0)
        self.eye_positions = tuple(_follow(master, path).getPos(master) for path in eye_paths)
        self.cape_position = joints["cape"].getPos(master)
        self.emblem = _follow(joints["cape"], emblem_path).copyTo(self._holder)
        self.emblem.setPos(_follow(joints["cape"], emblem_path).getPos())
        self.limbs = joints

        # Sentry's hair and brows belong to Sentry; each character adds its own.
        emblem_mark = master.find(f"**/{WAIST_S_NODE}")
        self.chest_s = emblem_mark.copyTo(self._holder)
        emblem_mark.removeNode()
        for name in ("complete-hair-root", "brows", "*_ear", "*_ear_inner", "*_cheek"):
            for node in master.findAllMatches(f"**/{name}"):
                node.removeNode()
        self.locks = master.attachNewNode("hair-locks")

        sphere_probe = template.parts["head"].model.find("**/+GeomNode")
        self._sphere_rows = sphere_probe.node().getGeom(0).getVertexData().getNumRows()
        self._low_sphere = self._extract_low_sphere()

        self.body = self._holder.attachNewNode("costume-body")
        self.shared_near = self._holder.attachNewNode("shared-head")
        excluded = {*joints.values(), self.locks}
        for child in tuple(master.getChildren()):
            if child in excluded:
                continue
            child.wrtReparentTo(self.body if _uses_costume_color(child) else self.shared_near)
        self.shared_far = self.shared_near.copyTo(self._holder)
        self.simplify(self.shared_far)
        _merge_batch(self.shared_near)
        _merge_batch(self.shared_far)

    def _extract_low_sphere(self):
        mesh = _low_poly_sphere()
        for path in (mesh, *mesh.findAllMatches("**")):
            node = path.node()
            if hasattr(node, "getNumGeoms") and node.getNumGeoms():
                return node.getGeom(0).makeCopy()
        raise RuntimeError("Low-poly sphere produced no geometry")

    def simplify(self, group: NodePath) -> None:
        """Swap full spheres for the low-poly one and drop hair-strand detail."""
        for name in FINE_HAIR_NODES:
            found = group.findAllMatches(f"**/{name}")
            for node in found:
                node.removeNode()
        for path in group.findAllMatches("**/+GeomNode"):
            node = path.node()
            if (node.getNumGeoms()
                    and node.getGeom(0).getVertexData().getNumRows() == self._sphere_rows):
                node.removeAllGeoms()
                node.addGeom(self._low_sphere)


class CloneVisual:
    """One enemy's copy of the body: joints, LOD sets and animatable handles."""

    def __init__(self, owner: NodePath, assets: CloneAssets, palette: CostumePalette) -> None:
        self.pose_root = owner.attachNewNode(f"{palette.name.lower()}-sentry-pose-root")
        if not SENTRY_LIGHT_SHADER.compiled:
            SENTRY_LIGHT_SHADER.compile()
        self.pose_root.setShader(SENTRY_LIGHT_SHADER._shader)
        for key, value in SENTRY_LIGHT_SHADER.default_input.items():
            self.pose_root.setShaderInput(key, value() if callable(value) else value)
        kit = kit_of(palette.name)
        self.pose_root.setScale(*kit.body_scale)
        self.near = self.pose_root.attachNewNode("detail-near")
        self.far = self.pose_root.attachNewNode("detail-far")
        if kit.skin is None:
            assets.shared_near.instanceTo(self.near)
            assets.shared_far.instanceTo(self.far)
        else:  # their own tone means their own copy of the head; for the rest, one is shared
            for shared, group in ((assets.shared_near, self.near), (assets.shared_far, self.far)):
                head = shared.copyTo(group)
                head.setColorScale(*(kit.skin[i] / HEAD_SKIN[i] for i in range(3)), 1.0)
                _merge_batch(head)

        body = assets.body.copyTo(self.near)
        _recolor_parts(body, palette)
        if kit.chest_s is not None:
            waist_s = assets.chest_s.copyTo(body)
            waist_s.setPos(*CHEST_S_POSITION)
            waist_s.setScale(-1.6, 1.6, 1.6)  # the mark is authored for the opposite facing
            waist_s.setColorScale(*kit.chest_s, 1.0)
        torso = body.find(f"**/{TORSO_NODE}")
        if not torso.isEmpty():
            _recolor_torso(torso, palette)
        far_body = body.copyTo(self.far)
        assets.simplify(far_body)
        _merge_batch(body)
        _merge_batch(far_body)

        self._lod_switches: list[tuple[NodePath, NodePath]] = []
        limbs = {}
        for name in LIMB_JOINTS:
            joint = assets.limbs[name].copyTo(self.pose_root)
            _recolor_parts(joint, palette)
            elbow = self._detach_elbow(assets, name, joint)
            near = _batch_children(joint, "limb-near")
            # The far set is built from the master so it can still be simplified.
            far_source = assets.limbs[name].copyTo(self.pose_root)
            far_source.setPos(0, 0, 0)
            _recolor_parts(far_source, palette)
            assets.simplify(far_source)
            far_elbow = self._detach_elbow(assets, name, far_source)
            far = _batch_children(far_source, "limb-far")
            far.reparentTo(joint)
            far_source.removeNode()
            self._lod_switches.append((near, far))
            limbs[name] = Joint(joint)
            if elbow is not None:
                near_forearm = _batch_children(elbow, "limb-near")
                far_forearm = _batch_children(far_elbow, "limb-far")
                far_forearm.reparentTo(elbow)
                far_elbow.removeNode()
                elbow.reparentTo(joint)
                self._lod_switches.append((near_forearm, far_forearm))
                limbs[ELBOWS[name]] = Joint(elbow)
        self.left_arm = limbs["left_arm"]
        self.right_arm = limbs["right_arm"]
        self.left_elbow = limbs["left_elbow"]
        self.right_elbow = limbs["right_elbow"]
        self.left_leg = limbs["left_leg"]
        self.right_leg = limbs["right_leg"]

        self.locks_node = assets.locks.copyTo(self.pose_root)
        self.lock_joints = [Joint(lock) for lock in self.locks_node.getChildren()]

        self.eye_left = EyePoint(self._marker("eye-left", assets.eye_positions[0]))
        self.eye_right = EyePoint(self._marker("eye-right", assets.eye_positions[1]))

        self._cape_nodes: list[Entity] = []
        self.cape = self._build_cape(assets, palette)
        if not kit.cape:
            self.cape.node.hide()
        self._build_costume(assets, kit.parts, "costume")
        self._helmet = None
        if kit.helmet_parts:
            self._helmet = self._build_costume(assets, kit.helmet_parts, "helmet")["body"]
            self._helmet.hide()
        self._shield = None
        if kit.shield_parts:
            self._shield = self._build_costume(assets, kit.shield_parts, "shield")["left_arm"]
        self.is_near = None
        self.set_detail(True)

    @staticmethod
    def _detach_elbow(assets: CloneAssets, name: str, joint: NodePath) -> NodePath | None:
        """Take the forearm off an arm, so the two are batched separately and can bend."""
        path = assets.elbow_paths.get(name)
        if path is None:
            return None
        elbow = _follow(joint, path)
        elbow.detachNode()
        return elbow

    def set_shield(self, visible: bool) -> None:
        if self._shield is not None:
            (self._shield.show() if visible else self._shield.hide())

    def set_helmet(self, visible: bool) -> None:
        if self._helmet is not None:
            (self._helmet.show() if visible else self._helmet.hide())

    def _build_costume(self, assets: CloneAssets, parts, label: str) -> dict:
        """Bake one character's hair, emblems and gear onto the body and limbs."""
        eye_a, eye_b = assets.eye_positions
        face = ((eye_a[0] + eye_b[0]) * .5, (eye_a[1] + eye_b[1]) * .5, (eye_a[2] + eye_b[2]) * .5)
        cube = load_model("cube")
        groups: dict[str, NodePath] = {}
        for anchor, shape, position, scale, tint, roll in parts:
            # Sleeves and gloves below the elbow bend with it. A shield stays strapped to the arm.
            on_forearm = anchor in ELBOWS and label != "shield" and position[1] < assets.elbow_y
            key = ELBOWS[anchor] if on_forearm else anchor
            if on_forearm:
                position = (position[0], position[1] - assets.elbow_y, position[2])
            group = groups.get(key)
            if group is None:
                joint = getattr(self, key).node if key in (*LIMB_JOINTS, *ELBOWS.values()) else self.pose_root
                group = groups[key] = joint.attachNewNode(f"{label}-{key}")
            if shape == "s":
                geom = GeomNode("costume-sphere")
                geom.addGeom(assets._low_sphere)
                part = group.attachNewNode(geom)
            else:
                part = cube.copyTo(group)
            offset = face if anchor == "face" else (0.0, 0.0, 0.0)
            # Ursina's y-up, z-forward model space, as every other body part uses.
            part.setPos(*(position[i] + offset[i] for i in range(3)))
            part.setScale(*scale)
            part.setR(roll)
            part.setColorScale(*tint, 1.0)
        for group in groups.values():
            _merge_batch(group)
            group.setTwoSided(True)  # ursina's cube and flattened discs are seen from both sides
        return groups

    def _marker(self, name: str, position) -> NodePath:
        marker = self.pose_root.attachNewNode(name)
        marker.setPos(position)
        return marker

    def _build_cape(self, assets: CloneAssets, palette: CostumePalette) -> Joint:
        """The original cape grid, recoloured, deforming on the GPU."""
        node = self.pose_root.attachNewNode("cape")
        node.setPos(assets.cape_position)
        rows, cols = assets.cape_rows, assets.cape_cols
        cloth = palette.cape
        flag = kit_of(palette.name).flag_cape
        colors, uvs, triangles = [], [], []
        for row in range(rows):
            for col in range(cols):
                uvs.append((col / (cols - 1), row / (rows - 1)))
                fold = max(0.0, cos(col * 2 * pi / (cols - 1) * 2.0))
                sheen = 1.0 + fold * .34
                base = _flag_color(col / (cols - 1), row / (rows - 1)) if flag else cloth
                colors.append(color.rgba(min(1.0, base[0] * sheen), min(1.0, base[1] * sheen),
                                         min(1.0, base[2] * sheen), 1.0))
        for row in range(rows - 1):
            for col in range(cols - 1):
                i = row * cols + col
                triangles.extend((i, i + cols, i + 1, i + 1, i + cols, i + cols + 1))
        cloth_mesh = Mesh(vertices=assets.cape_vertices, triangles=triangles, colors=colors,
                          uvs=uvs, static=True)

        trim_vertices, trim_triangles = assets.cape_trim
        trim_uvs = []
        inset = .24 / (cols - 1)
        for row in range(rows):
            v = row / (rows - 1)
            trim_uvs.extend(((0.0, v), (inset, v), (1.0, v), (1.0 - inset, v)))
        trim_mesh = Mesh(vertices=trim_vertices, triangles=trim_triangles, uvs=trim_uvs,
                         static=True)

        r, g, b = palette.trim
        for mesh, tint in ((cloth_mesh, color.white), (trim_mesh, color.rgba(r, g, b, 1.0))):
            part = Entity(model=mesh, shader=CAPE_SHADER, color=tint, double_sided=True,
                          add_to_scene_entities=False, collider=None)
            part.reparentTo(node)
            self._cape_nodes.append(part)

        return Joint(node)

    def set_cape_wind(self, time: float, wind: float, forward: float, right: float) -> None:
        for part in self._cape_nodes:
            part.setShaderInput("u_cape_wind", time, wind,
                                max(-.34, min(.34, forward / 520.0)),
                                max(-.22, min(.22, right / 520.0)))

    def set_detail(self, near: bool) -> None:
        """Show full geometry near the camera and the low-poly set otherwise."""
        if near == self.is_near:
            return
        self.is_near = near
        visible, hidden = (self.near, self.far) if near else (self.far, self.near)
        visible.show()
        hidden.hide()
        for near_limb, far_limb in self._lod_switches:
            (near_limb.show() if near else near_limb.hide())
            (far_limb.hide() if near else far_limb.show())
        (self.locks_node.show() if near else self.locks_node.hide())
