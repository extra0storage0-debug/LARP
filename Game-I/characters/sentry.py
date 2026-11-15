"""Visible, modular primitive superhuman that can be replaced by a rigged model."""

from __future__ import annotations

from math import cos, exp, pi, radians, sin, sqrt

from panda3d.core import LColor, LQuaternionf, LVector3f, Material
from ursina import Entity, Mesh, Vec3, color
from characters.sentry_shader import SENTRY_LIGHT_SHADER

from movement.character_styles import DEFAULT_STYLE
from movement.flight_pose import ASCENDING, DESCENDING, HANDS_ON_HIPS, POSES, REACHING, blend_amount, choose_pose
from movement.flight_physics import (FlightDynamics, FlightPhase, Vec3 as SimVec3,
                                     rotate_towards_degrees)
from movement.flight_steering import flight_posture, quaternion_slerp
from movement.ground_movement import GroundMovement
from game.island_frame import cross, dot
from world import native_bridge as native


def _build_sculpted_torso():
    """Create a single contoured suit surface with broad chest and defined abs."""
    from math import cos, exp, pi, sin

    profile = ((.76, .37, .235), (.91, .43, .275), (1.08, .405, .255),
               (1.28, .37, .235), (1.48, .42, .255), (1.70, .53, .300),
               (1.88, .59, .315), (2.04, .49, .260), (2.15, .26, .195))
    rows, columns = 72, 64
    vertices, colors, normals, triangles = [], [], [], []

    def smooth_profile(y, axis):
        for idx in range(len(profile) - 1):
            low, high = profile[idx], profile[idx + 1]
            if low[0] <= y <= high[0]:
                t = (y - low[0]) / (high[0] - low[0])
                t = t * t * (3 - 2 * t)
                return low[axis] + (high[axis] - low[axis]) * t
        return profile[0 if y < profile[0][0] else -1][axis]

    for row in range(rows + 1):
        y = profile[0][0] + (profile[-1][0] - profile[0][0]) * row / rows
        width, depth = smooth_profile(y, 1), smooth_profile(y, 2)
        delta = .002
        width_slope = (smooth_profile(min(profile[-1][0], y + delta), 1)
                       - smooth_profile(max(profile[0][0], y - delta), 1)) / (2 * delta)
        depth_slope = (smooth_profile(min(profile[-1][0], y + delta), 2)
                       - smooth_profile(max(profile[0][0], y - delta), 2)) / (2 * delta)
        for column in range(columns):
            theta = 2 * pi * column / columns
            front = max(0.0, sin(theta))
            x = width * cos(theta)
            z = depth * sin(theta)
            # Pectoral mass, a restrained center cleft, and paired abdominal
            # planes are shaped into the same continuous surface.
            chest = .065 * exp(-((y - 1.78) / .21) ** 2)
            pec_split = .030 * exp(-(x / .045) ** 2) * exp(-((y - 1.79) / .18) ** 2)
            abs_zone = exp(-((y - 1.38) / .30) ** 4)
            abs_bulge = .048 * abs_zone * exp(-((abs(x) - .145) / .105) ** 2) \
                * (.55 + .45 * cos((y - 1.36) * 18.0) ** 2)
            ab_center_crease = .012 * abs_zone * exp(-(x / .034) ** 2)
            ab_row_crease = .009 * (exp(-((y - 1.427) / .022) ** 2)
                                    + exp(-((y - 1.262) / .022) ** 2)) \
                * exp(-(x / .29) ** 4)
            waist_draw = -.016 * exp(-((y - 1.10) / .19) ** 2)
            z += front * (chest - pec_split + abs_bulge - ab_center_crease
                          - ab_row_crease + waist_draw)
            vertices.append((x, y, z))
            normal = (cos(theta) / width,
                      -(x * x * width_slope / width ** 3
                        + z * z * depth_slope / depth ** 3),
                      sin(theta) / depth)
            normal_length = sqrt(sum(component * component for component in normal))
            normals.append(tuple(component / max(normal_length, 1e-8)
                                 for component in normal))
            muscle_light = .5 + .5 * max(0.0, cos(theta))
            shade = max(0.0, min(1.0, .60 + .20 * muscle_light
                                  + .12 * exp(-((y - 1.78) / .32) ** 2)
                                  + .22 * abs_bulge / .048
                                  - .15 * ab_center_crease / .012
                                  - .10 * min(1.0, ab_row_crease / .009)))
            colors.append(color.rgb32(round(188 + 64 * shade),
                                      round(108 + 93 * shade),
                                      round(12 + 53 * shade)))

    for row in range(rows):
        for column in range(columns):
            nxt = (column + 1) % columns
            a, b = row * columns + column, row * columns + nxt
            c, d = (row + 1) * columns + nxt, (row + 1) * columns + column
            # The ring order runs upward; reverse winding so normals face out.
            triangles.extend((a, c, b, a, d, c))
    return Mesh(vertices=vertices, triangles=triangles, colors=colors,
                normals=normals, static=True)


def _append_tube(vertices, triangles, points, radius: float, sides: int = 6,
                 end_radius: float | None = None) -> None:
    """Append a low-poly swept tube for brows and individual hair strands."""
    from math import cos, sin, sqrt

    def normalize(v):
        length = sqrt(sum(component * component for component in v))
        return tuple(component / max(length, 1e-8) for component in v)

    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

    first = len(vertices)
    for index, point in enumerate(points):
        t = index / max(1, len(points) - 1)
        ring_radius = radius if end_radius is None else radius + (end_radius - radius) * t
        previous = points[max(0, index - 1)]
        following = points[min(len(points) - 1, index + 1)]
        tangent = normalize(tuple(following[i] - previous[i] for i in range(3)))
        reference = (0.0, 1.0, 0.0) if abs(tangent[1]) < .9 else (1.0, 0.0, 0.0)
        side = normalize(cross(tangent, reference))
        other = normalize(cross(tangent, side))
        for ring in range(sides):
            angle = 2.0 * 3.141592653589793 * ring / sides
            vertices.append(tuple(point[axis] + ring_radius * (side[axis] * cos(angle)
                                                                + other[axis] * sin(angle))
                                  for axis in range(3)))
    for index in range(len(points) - 1):
        for ring in range(sides):
            a = first + index * sides + ring
            b = first + index * sides + (ring + 1) % sides
            c = b + sides
            d = a + sides
            triangles.extend((a, b, c, a, c, d))

JUMP_GRAVITY = 22.0
JUMP_CUT_GRAVITY = 2.4       # let go of jump on the way up, and the hop ends sooner
SUPER_JUMP_TERMINAL = 700.0  # a leap can go up without limit, and he has to be able to get back down from it
TERMINAL_FALL_SPEED = 150.0  # gravity and air balance here, unless something is driving the body down
STEP_AT_WALK, STEP_AT_RUN = 1.15, 4.4
MAX_TURN_BANK, TURN_BANK, BANK_FULL_SPEED = 38.0, -.22, 40.0
HOVER_FEET = .35  # how far the toes point down while hovering; all the way in forward flight
POINTED_BY_POSE = {REACHING: 1.0, HANDS_ON_HIPS: HOVER_FEET, ASCENDING: .8, DESCENDING: .45}
MAX_STRIDE_RATE = 30.0
WALK_STANCE, WALK_NARROW = .3, .68  # how far the feet come in under the body, standing and walking
MIN_WALK_ELBOW = -8.0
# The super jump. A tap is a hop; holding the key drives the leap on for a moment; another press, in
# the air or on the ground, starts that again. These speeds and heights only keep the numbers stable.
SUPER_TAP_SCALE = 2.5        # of Jump Strength
SUPER_THRUST = 320.0         # metres per second squared, while the key is held
SUPER_HOLD_SECONDS = .8      # to one press
MAX_JUMP_SPEED = 900.0       # up or down
SAFE_ALTITUDE = 200000.0     # well beyond anywhere reachable; only here so that a position cannot overflow
SUPER_LANDING_SPEED = 40.0   # below this he simply lands
SUPER_LAUNCH_SPEED = 260.0   # F: the full leap at once; held, it keeps driving on as Space does
ELBOW_Y = -.52  # below the shoulder joint, where the upper arm ends
POSE_SETTLE_SECONDS = .6


def fall_with_air(vertical: float, gravity: float, dt: float, terminal: float = TERMINAL_FALL_SPEED) -> float:
    """One step of gravity, with drag growing as the square of the speed of a fall, up to terminal velocity."""
    vertical -= gravity * dt
    if vertical < 0.0:
        vertical += gravity * (vertical / terminal) ** 2 * dt
    return vertical


class SentryCharacter(Entity):
    def __init__(self, game, **kwargs):
        kwargs.setdefault("model", None)
        kwargs.setdefault("position", (0, .25, 0))
        super().__init__(**kwargs)
        self.game = game
        self.flight = FlightDynamics()
        self.ground = GroundMovement()
        self.local_yaw = 0.0
        self.tuning = getattr(self.game, "tuning", None)
        self.jump_height = 0.0
        self.flight_pose = HANDS_ON_HIPS
        self._pose_settling = 0.0
        self.jump_velocity = 0.0
        self.jump_hold_left = 0.0
        self.jump_power = 1.0
        self.jump_held = False
        self._animation_rate = 1.0
        self._posture_rate = 5.5
        self._cape_step = 1.0
        self._native_cape = None
        self._cape_progress = 0.0
        self._animation_time = 0.0
        self._stride_phase = 0.0
        self._walk_yaw = 0.0
        self._vertical_input = 0.0
        self._jump_cut = False
        self._last_yaw = 0.0
        self.thrusting = True  # the player's own input says otherwise; AI flies wherever it is flying
        self._airflow_forward = 0.0
        self._airflow_right = 0.0
        self.apply_sentry_config()
        self.reentry_glow = Entity(parent=self, model="sphere", position=(0, 1.42, 0),
                                   scale=(1.18, 2.55, 1.05),
                                   color=color.rgba32(255, 86, 22, 0),
                                   unlit=True, transparency=True, collider=None,
                                   name="atmospheric-reentry-glow")
        previous_shader = Entity.default_shader
        Entity.default_shader = SENTRY_LIGHT_SHADER
        try:
            self._build_body()
        finally:
            Entity.default_shader = previous_shader

    def _build_body(self) -> None:
        self.pose_root = Entity(parent=self, name="flight-posture-root",
                                position=(0, 0, 0), rotation=(0, 0, 0))
        suit = color.rgb32(220, 153, 24)
        suit_light = color.rgb32(242, 180, 40)
        suit_highlight = color.rgb32(255, 211, 82)
        glove = color.rgb32(10, 17, 34)
        boot = color.rgb32(9, 15, 30)
        gold = color.rgb32(255, 193, 48)
        gold_highlight = color.rgb32(255, 218, 104)
        self.gold_material = Material("sentry-gold")
        self.gold_material.setSpecular(LColor(.90, .70, .31, 1))
        self.gold_material.setShininess(34)
        self.gold_material.setMetallic(.34)
        self.hair_material = Material("golden-hair")
        self.hair_material.setSpecular(LColor(.68, .48, .19, 1))
        self.hair_material.setShininess(30)
        self.cape_material = Material("midnight-cape")
        self.cape_material.setSpecular(LColor(.20, .24, .34, 1))
        self.cape_material.setShininess(12)
        self.parts: dict[str, Entity] = {}

        def part(name: str, model: str, position, scale, tint, **options) -> Entity:
            item = Entity(parent=self, name=name, model=model, position=position,
                          scale=scale, color=tint, **options)
            self.parts[name] = item
            return item

        # A continuous tailored torso avoids the stacked-ball silhouette while
        # retaining the original Sentry entity root and all gameplay attachment points.
        self.parts["torso_suit"] = Entity(parent=self, name="sculpted-gold-torso",
                                          model=_build_sculpted_torso(), color=color.white)
        self.parts["briefs"] = part("navy-tailored-briefs", "sphere", (0, .88, .005),
                                    (.435, .265, .282), glove)
        self.parts["belt"] = part("belt", "sphere", (0, 1.02, .015),
                                  (.49, .18, .30), glove)
        # Flat circular plate and gold rim keep the belt mark crisp at game scale.
        medallion_vertices = [(0.0, 0.0, 0.0)]
        for index in range(48):
            angle = 2 * pi * index / 48
            medallion_vertices.append((.155 * cos(angle), .155 * sin(angle), 0.0))
        medallion_triangles = []
        for index in range(48):
            medallion_triangles.extend((0, 1 + (index + 1) % 48, 1 + index))
        self.parts["belt_medallion"] = Entity(
            parent=self, name="belt-medallion", model=Mesh(vertices=medallion_vertices,
                triangles=medallion_triangles, static=True), position=(0, 1.04, .35),
            color=color.rgb32(8, 13, 27), double_sided=True)
        ring_vertices, ring_triangles = [], []
        for index in range(48):
            angle = 2 * pi * index / 48
            for radius in (.155, .18):
                ring_vertices.append((radius * cos(angle), radius * sin(angle), 0.0))
        for index in range(48):
            a = index * 2
            b = a + 1
            c = ((index + 1) % 48) * 2 + 1
            d = ((index + 1) % 48) * 2
            ring_triangles.extend((a, b, c, a, c, d))
        self.parts["belt_buckle"] = Entity(
            parent=self, name="raised-gold-belt-rim", model=Mesh(vertices=ring_vertices,
                triangles=ring_triangles, static=True), position=(0, 1.04, .354),
            color=gold, double_sided=True)
        self.parts["neck"] = part("neck", "sphere", (0, 2.18, .02),
                                  (.25, .14, .24), glove)
        skin = color.rgb32(205, 157, 128)
        skin_light = color.rgb32(224, 178, 148)
        skin_shadow = color.rgb32(148, 99, 82)
        part("head", "sphere", (0, 2.51, .04), (.43, .53, .40), skin)
        # Tapered jaw, cheek planes and chin give the face a stronger silhouette.
        part("jaw", "sphere", (0, 2.34, .12), (.35, .34, .32), skin)
        part("chin", "sphere", (0, 2.245, .34), (.205, .125, .115), skin_light)
        part("left_cheek", "sphere", (-.235, 2.48, .345), (.105, .105, .060), skin_light)
        part("right_cheek", "sphere", (.235, 2.48, .345), (.105, .105, .060), skin_light)

        # Eye sockets, visible ivory eyes, blue irises, pupils and lids.
        self.eye_left = part("left_eye", "sphere", (-.105, 2.545, .419), (.079, .050, .035),
                             color.rgb32(238, 232, 215))
        self.eye_right = part("right_eye", "sphere", (.105, 2.545, .419), (.079, .050, .035),
                              color.rgb32(238, 232, 215))
        for x, side in ((-.105, "left"), (.105, "right")):
            part(f"{side}_iris", "sphere", (x, 2.545, .451), (.030, .034, .014),
                 color.rgb32(55, 111, 151))
            part(f"{side}_pupil", "sphere", (x, 2.545, .463), (.014, .022, .009),
                 color.rgb32(18, 21, 25))
            part(f"{side}_lower_lid", "sphere", (x, 2.505, .427), (.078, .018, .024), skin_shadow)

        # Brow ridges are swept geometry rather than flat decals.
        brow_vertices, brow_triangles = [], []
        for points in (
            ((-.20, 2.625, .415), (-.13, 2.66, .435), (-.06, 2.635, .445)),
            ((.06, 2.635, .445), (.13, 2.66, .435), (.20, 2.625, .415)),
        ):
            _append_tube(brow_vertices, brow_triangles, points, .018, 7)
        self.parts["brows"] = Entity(parent=self, name="brows",
                                     model=Mesh(vertices=brow_vertices, triangles=brow_triangles,
                                                static=True),
                                     color=color.rgb32(48, 35, 31), double_sided=True)

        part("nose_bridge", "sphere", (0, 2.485, .439), (.066, .14, .078), skin_light)
        part("nose_tip", "sphere", (0, 2.418, .485), (.078, .058, .060), skin_light)
        part("left_nostril", "sphere", (-.052, 2.397, .518), (.027, .018, .014), skin_shadow)
        part("right_nostril", "sphere", (.052, 2.397, .518), (.027, .018, .014), skin_shadow)
        part("upper_lip", "sphere", (0, 2.315, .449), (.117, .030, .044), color.rgb32(130, 72, 68))
        part("lower_lip", "sphere", (0, 2.285, .448), (.105, .026, .040), color.rgb32(174, 105, 96))
        part("mouth_line", "sphere", (0, 2.300, .478), (.087, .009, .010), color.rgb32(67, 43, 41))
        for x, side in ((-.405, "left"), (.405, "right")):
            part(f"{side}_ear", "sphere", (x, 2.50, .015), (.085, .135, .085), skin)
            part(f"{side}_ear_inner", "sphere", (x * 1.04, 2.505, .087),
                 (.043, .090, .023), skin_shadow)

        # A connected scalp shell and a rear curtain replace the old floating
        # cap/locks. The root cancels the head ellipsoid scale, so the mesh stays
        # in Sentry-local metres while following the actual animated head node.
        self._build_hair()
        part("left_shoulder", "sphere", (-.48, 1.93, 0), (.22, .27, .28), suit)
        part("right_shoulder", "sphere", (.48, 1.93, 0), (.22, .27, .28), suit)

        self.left_arm = Entity(parent=self, position=(-.62, 1.55, 0))
        self.left_upper_arm = Entity(parent=self.left_arm, model="sphere", position=(0, -.30, 0),
                                     scale=(.265, .52, .28), color=suit)
        # Everything below the elbow hangs from its own joint, at the same place at rest.
        self.left_elbow = Entity(parent=self.left_arm, position=(0, ELBOW_Y, 0))
        self.left_forearm = Entity(parent=self.left_elbow, model="sphere", position=(0, -.70 - ELBOW_Y, .025),
                                   scale=(.21, .43, .225), color=suit_light)
        self.left_glove = Entity(parent=self.left_elbow, model="sphere", position=(0, -.98 - ELBOW_Y, .05),
                                 scale=(.19, .22, .20), color=glove)
        self.left_cuff = Entity(parent=self.left_elbow, model="sphere", position=(0, -.83 - ELBOW_Y, .035),
                                scale=(.218, .075, .232), color=glove)
        self.right_arm = Entity(parent=self, position=(.62, 1.55, 0))
        self.right_upper_arm = Entity(parent=self.right_arm, model="sphere", position=(0, -.30, 0),
                                      scale=(.265, .52, .28), color=suit)
        self.right_elbow = Entity(parent=self.right_arm, position=(0, ELBOW_Y, 0))
        self.right_forearm = Entity(parent=self.right_elbow, model="sphere", position=(0, -.70 - ELBOW_Y, .025),
                                    scale=(.21, .43, .225), color=suit_light)
        self.right_glove = Entity(parent=self.right_elbow, model="sphere", position=(0, -.98 - ELBOW_Y, .05),
                                  scale=(.19, .22, .20), color=glove)
        self.right_cuff = Entity(parent=self.right_elbow, model="sphere", position=(0, -.83 - ELBOW_Y, .035),
                                 scale=(.218, .075, .232), color=glove)
        # Individual covered fingers keep the hands readable at gameplay scale.
        for elbow, side in ((self.left_elbow, -1), (self.right_elbow, 1)):
            for finger in range(4):
                x = (finger - 1.5) * .073
                Entity(parent=elbow, name=f"navy-glove-finger-{side}-{finger}",
                       model="sphere", position=(x, -1.115 - ELBOW_Y, .075),
                       scale=(.038, .105, .044), color=glove)
            Entity(parent=elbow, name=f"navy-glove-thumb-{side}",
                   model="sphere", position=(side * .145, -1.035 - ELBOW_Y, .085),
                   rotation_z=side * -28, scale=(.052, .12, .05), color=glove)

        self.left_leg = Entity(parent=self, position=(-.16, .72, 0))
        self.left_thigh = Entity(parent=self.left_leg, model="sphere", position=(0, -.32, 0),
                                 scale=(.30, .68, .335), color=suit)
        self.left_boot = Entity(parent=self.left_leg, model="sphere", position=(0, -.75, .075),
                                scale=(.225, .46, .28), color=boot)
        Entity(parent=self.left_leg, name="left-navy-boot-foot", model="sphere",
               position=(0, -.88, .18), scale=(.23, .15, .34), color=boot)
        self.right_leg = Entity(parent=self, position=(.16, .72, 0))
        self.right_thigh = Entity(parent=self.right_leg, model="sphere", position=(0, -.32, 0),
                                  scale=(.30, .68, .335), color=suit)
        self.right_boot = Entity(parent=self.right_leg, model="sphere", position=(0, -.75, .075),
                                 scale=(.225, .46, .28), color=boot)
        Entity(parent=self.right_leg, name="right-navy-boot-foot", model="sphere",
               position=(0, -.88, .18), scale=(.23, .15, .34), color=boot)

        # A lightweight cape grid deforms with airflow; separate narrow meshes
        # carry its gold piping and large rear S so both follow the same cape root.
        self._cape_rows, self._cape_cols = 17, 25
        self._cape_vertices = []
        self._cape_colors = []
        for row in range(self._cape_rows):
            t = row / (self._cape_rows - 1)
            width = .45 + .40 * t
            for col in range(self._cape_cols):
                x = (col / (self._cape_cols - 1) * 2.0 - 1.0) * width
                fold = cos(col * 2 * pi / (self._cape_cols - 1) * 2.0)
                y = -2.02 * t + .15 * t * (x / max(width, .01)) ** 2
                z = -.37 - .055 * fold * t
                self._cape_vertices.append((x, y, z))
                sheen = round(16 + max(0.0, fold) * 20)
                self._cape_colors.append(color.rgb32(14 + sheen // 3,
                                                     25 + sheen // 2,
                                                     54 + sheen))
        triangles = []
        for row in range(self._cape_rows - 1):
            for col in range(self._cape_cols - 1):
                i = row * self._cape_cols + col
                triangles.extend((i, i + self._cape_cols, i + 1,
                                  i + 1, i + self._cape_cols, i + self._cape_cols + 1))
        self.cape_mesh = Mesh(vertices=self._cape_vertices, triangles=triangles,
                              colors=self._cape_colors, static=False)
        # The cape mesh vertices already encode its dark navy folds. Applying a
        # second navy entity tint multiplies those values down to black.
        self.cape = Entity(parent=self, model=self.cape_mesh, position=(0, 2.28, -.12),
                           color=color.white, double_sided=True, unlit=False)
        self.cape.setMaterial(self.cape_material)

        trim_vertices, trim_triangles = self._cape_trim_geometry(self._cape_vertices)
        self.cape_trim_mesh = Mesh(vertices=trim_vertices, triangles=trim_triangles, static=False)
        self.cape_trim = Entity(parent=self.cape, name="gold-cape-edge-trim",
                                model=self.cape_trim_mesh, color=gold_highlight,
                                double_sided=True)
        self.cape_trim.setMaterial(self.gold_material)
        s_points = ((.22, .23, 0), (.12, .29, 0), (-.08, .30, 0),
                    (-.21, .22, 0), (-.19, .10, 0), (-.06, .025, 0),
                    (.12, -.04, 0), (.20, -.14, 0), (.17, -.25, 0),
                    (.04, -.30, 0), (-.13, -.29, 0), (-.22, -.23, 0))
        emblem_vertices, emblem_triangles = [], []
        _append_tube(emblem_vertices, emblem_triangles, s_points, .052, 9)
        self.cape_emblem = Entity(parent=self.cape, name="gold-s-cape-emblem",
                                  model=Mesh(vertices=emblem_vertices,
                                             triangles=emblem_triangles, static=True),
                                  position=(0, -1.04, -.415), color=gold_highlight,
                                  double_sided=True)
        self.cape_emblem.setMaterial(self.gold_material)

        waist_s = ((.087, .098, 0), (.035, .12, 0), (-.045, .112, 0),
                   (-.086, .069, 0), (-.075, .024, 0), (-.018, -.004, 0),
                   (.052, -.032, 0), (.078, -.07, 0), (.058, -.11, 0),
                   (.008, -.12, 0), (-.058, -.101, 0))
        waist_vertices, waist_triangles = [], []
        _append_tube(waist_vertices, waist_triangles, waist_s, .021, 8)
        self.parts["waist_s"] = Entity(
            parent=self, name="raised-gold-waist-s",
            model=Mesh(vertices=waist_vertices, triangles=waist_triangles, static=True),
            position=(0, 1.04, .362), color=gold_highlight, double_sided=True)
        self.parts["waist_s"].setMaterial(self.gold_material)

        gold_part_names = ("torso_suit", "left_shoulder", "right_shoulder", "belt_buckle")
        for name in gold_part_names:
            self.parts[name].setMaterial(self.gold_material)
        for item in (self.left_upper_arm, self.right_upper_arm,
                     self.left_thigh, self.right_thigh):
            item.setMaterial(self.gold_material)
        for item in (self.left_glove, self.right_glove, self.left_boot,
                     self.right_boot, self.parts["belt"], self.left_forearm,
                     self.right_forearm, self.left_cuff, self.right_cuff,
                     self.parts["belt_medallion"], self.parts["neck"]):
            item.color = glove
        for lock in self.hair_locks:
            lock.setMaterial(self.hair_material)

        # Keep the gameplay root upright and facing independently from the
        # visible flight pose. Its collider, gravity frame, and camera target
        # therefore never inherit a dive or backward-flight rotation.
        for child in tuple(self.children):
            if child not in (self.pose_root, self.reentry_glow):
                child.parent = self.pose_root

    def set_character_light_floor(self, value: float) -> None:
        """Update every character mesh; shader defaults are entity-local."""
        def apply(entity) -> None:
            entity.set_shader_input("u_character_light_floor", value)
            for child in entity.children:
                apply(child)

        for child in self.children:
            apply(child)

    def _cape_trim_geometry(self, cape_vertices):
        vertices, triangles = [], []
        row_width = 4
        for row in range(self._cape_rows):
            base = row * self._cape_cols
            for edge, inner in ((base, base + 1),
                                (base + self._cape_cols - 1,
                                 base + self._cape_cols - 2)):
                outer_point, inner_point = cape_vertices[edge], cape_vertices[inner]
                inset_x = outer_point[0] + (inner_point[0] - outer_point[0]) * .24
                z = outer_point[2] - .022
                vertices.extend(((outer_point[0], outer_point[1], z),
                                 (inset_x, outer_point[1], z)))
        for row in range(self._cape_rows - 1):
            for side in range(2):
                a = row * row_width + side * 2
                b = a + 1
                c = a + row_width + 1
                d = a + row_width
                triangles.extend((a, b, c, a, c, d))
        return vertices, triangles

    def _build_hair(self) -> None:
        """Build a loose golden-blonde scalp shell with layered wavy locks."""
        hair_base = color.rgb32(204, 139, 35)
        hair_mid = color.rgb32(229, 164, 51)
        hair_highlight = color.rgb32(248, 202, 93)
        hair_shadow = color.rgb32(160, 98, 27)
        self.parts["head"].color = color.rgb32(205, 157, 128)
        self.hair_root = Entity(parent=self.parts["head"], name="complete-hair-root",
                                model=None, position=(0, 0, 0),
                                scale=(1 / .43, 1 / .53, 1 / .40))

        theta_segments = 112
        scalp_rows = 18
        rx, ry, rz = .465, .595, .435

        def boundary(theta: float) -> float:
            wrapped = (theta + pi) % (2 * pi) - pi
            # Keep the central forehead hairline above the eyes, then bring the
            # fringe down around the temples and nape.
            fraction = max(0.0, (abs(wrapped) - .32) / (pi - .32))
            # A raised center hairline, long temple panels, and a natural nape.
            wave = .012 * sin(theta * 8.0 + .3) + .006 * sin(theta * 15.0)
            return 1.34 + .84 * fraction ** .82 + wave

        def surface_point(theta: float, phi: float, lift: float = .0):
            wave = (.012 * sin(theta * 9.0 + phi * 5.0)
                    + .006 * sin(theta * 17.0 - phi * 12.0)) * sin(phi)
            rear_volume = .30 * max(0.0, -cos(theta)) * sin(phi) \
                * (.35 + .65 * phi / pi)
            return ((rx + lift + wave) * sin(phi) * sin(theta),
                    (ry + lift + wave * .55) * cos(phi),
                    (rz + lift + wave) * sin(phi) * cos(theta) - rear_volume)

        vertices = [(0.0, ry, 0.0)]
        vertex_colors = [hair_highlight]
        triangles = []
        for row in range(1, scalp_rows + 1):
            t = row / scalp_rows
            for column in range(theta_segments):
                theta = 2 * pi * column / theta_segments
                phi = boundary(theta) * t
                vertices.append(surface_point(theta, phi))
                wave = .5 + .5 * sin(theta * 11.0 + phi * 8.0)
                vertex_colors.append(color.rgb32(round(177 + 70 * wave),
                                                 round(104 + 88 * wave),
                                                 round(24 + 46 * wave)))

        first_ring = 1
        for column in range(theta_segments):
            following = (column + 1) % theta_segments
            triangles.extend((0, first_ring + column, first_ring + following))
        for row in range(1, scalp_rows):
            upper = 1 + (row - 1) * theta_segments
            lower = 1 + row * theta_segments
            for column in range(theta_segments):
                following = (column + 1) % theta_segments
                a, b = upper + column, upper + following
                c, d = lower + following, lower + column
                triangles.extend((a, b, c, a, c, d))

        # Continue the same edge into a single side-and-rear hair curtain.
        # Its open front arc keeps the eyes, brows and face unobstructed.
        curtain_rows = 10
        edge_offset = 1 + (scalp_rows - 1) * theta_segments
        def bottom_y(theta: float) -> float:
            rear_weight = max(0.0, -cos(theta))
            return -.63 - .18 * rear_weight + .05 * sin(theta * 4.0)

        for row in range(1, curtain_rows + 1):
            t = row / curtain_rows
            for column in range(theta_segments):
                theta = 2 * pi * column / theta_segments
                phi = boundary(theta)
                edge = surface_point(theta, phi)
                radius_x = rx * sin(phi) * (1.0 + .38 * t)
                radius_z = rz * sin(phi) * (1.0 - .08 * t + .035 * sin(pi * t))
                wrapped = (theta + pi) % (2 * pi) - pi
                side_wrap = max(0.0, 1.0 - abs(abs(wrapped) - pi / 2) / (pi / 2))
                x = radius_x * sin(theta) + .04 * sin(theta * 9.0 + t * pi) * sin(pi * t)
                rear_volume = .30 * max(0.0, -cos(theta)) * sin(phi) \
                    * (.35 + .65 * phi / pi)
                z = radius_z * cos(theta) - rear_volume - .018 * sin(pi * t) \
                    - .12 * max(0.0, -cos(theta)) * t \
                    - .55 * side_wrap * t \
                    - .026 * sin(theta * 8.0 + t * 2 * pi) * sin(pi * t)
                y = edge[1] + (bottom_y(theta) - edge[1]) * t
                vertices.append((x, y, z))
                wave = .5 + .5 * sin(theta * 11.0 + phi * 8.0 + t * 4.0)
                vertex_colors.append(color.rgb32(round(174 + 68 * wave),
                                                 round(99 + 88 * wave),
                                                 round(19 + 48 * wave)))

        def rear_arc(theta: float) -> bool:
            wrapped = (theta + pi) % (2 * pi) - pi
            return abs(wrapped) >= .70

        for row in range(curtain_rows):
            upper = edge_offset + row * theta_segments
            lower = upper + theta_segments
            for column in range(theta_segments):
                following = (column + 1) % theta_segments
                theta_mid = 2 * pi * (column + .5) / theta_segments
                if not rear_arc(theta_mid):
                    continue
                a, b = upper + column, upper + following
                c, d = lower + following, lower + column
                triangles.extend((a, b, c, a, c, d))

        scalp = Entity(parent=self.hair_root, name="continuous-scalp-and-rear-curtain",
                       model=Mesh(vertices=vertices, triangles=triangles,
                                  colors=vertex_colors, static=True),
                       color=color.white, double_sided=True)
        scalp.setMaterial(self.hair_material)
        self.parts["hair_shell"] = scalp

        # A handful of tapered, connected hair ribbons add layered volume at
        # both temples and across the loose shoulder-length rear curtain.
        self.hair_locks: list[Entity] = []
        lock_angles = tuple(-2.90 + index * (5.80 / 17) for index in range(18))
        for index, theta in enumerate(lock_angles):
            phi = boundary(theta) - .035
            start = surface_point(theta, phi, .012)
            side_sign = -1.0 if sin(theta) < 0 else 1.0
            end_x = side_sign * (.30 + .10 * abs(sin(theta)))
            end_z = .16 if abs(theta) < .85 else (-.52 if abs(theta) > 1.45 else -.34)
            points = []
            for step in range(19):
                t = step / 18
                wave = sin(t * 4 * pi + index * .72) * sin(pi * t)
                points.append((start[0] + (end_x - start[0]) * t + side_sign * .065 * wave,
                               start[1] + (bottom_y(theta) - .05 - start[1]) * t,
                               start[2] + (end_z - start[2]) * t - .05 * wave))
            local_points = tuple((x - start[0], y - start[1], z - start[2])
                                 for x, y, z in points)
            lock_vertices, lock_triangles = [], []
            radius = .020 if abs(theta) < .85 else (.029 if abs(theta) > 2.2 else .024)
            _append_tube(lock_vertices, lock_triangles, local_points, radius, 8,
                         end_radius=.003)
            lock_tint = (hair_shadow, hair_base, hair_mid)[index % 3]
            lock = Entity(parent=self.hair_root, name=f"connected-hair-lock-{index}",
                          model=Mesh(vertices=lock_vertices, triangles=lock_triangles,
                                     static=True), position=start, origin=(0, 0, 0),
                          color=lock_tint, double_sided=True)
            lock.setMaterial(self.hair_material)
            self.hair_locks.append(lock)

        # Fine golden sweeps catch the light along the loose waves.
        light_vertices, light_triangles = [], []
        shadow_vertices, shadow_triangles = [], []
        for strand in range(20):
            theta_end = -2.95 + strand * (5.9 / 19)
            phi_end = boundary(theta_end) - .04
            points = []
            for step in range(12):
                t = step / 11
                phi = .20 + (phi_end - .20) * t
                theta = theta_end * (.68 + .32 * t) \
                    + .085 * sin(t * 2 * pi + strand * .8) * sin(pi * t)
                phi += .055 * sin(t * 2 * pi + strand * .62) * sin(pi * t)
                points.append(surface_point(theta, phi, .010))
            if strand % 4 == 0:
                _append_tube(shadow_vertices, shadow_triangles, points, .0045, 5,
                             end_radius=.002)
            else:
                _append_tube(light_vertices, light_triangles, points, .004, 5,
                             end_radius=.002)
        self.parts["hair_highlights"] = Entity(
            parent=self.hair_root, name="golden-hair-highlights",
            model=Mesh(vertices=light_vertices, triangles=light_triangles, static=True),
            color=hair_highlight, double_sided=True)
        self.parts["hair_highlights"].setMaterial(self.hair_material)
        self.parts["hair_shadows"] = Entity(
            parent=self.hair_root, name="golden-hair-shadows",
            model=Mesh(vertices=shadow_vertices, triangles=shadow_triangles, static=True),
            color=hair_shadow, double_sided=True)
        self.parts["hair_shadows"].setMaterial(self.hair_material)

    def apply_sentry_config(self) -> None:
        cfg = getattr(self.game, "sentry_config", None)
        if not cfg:
            return
        fc = self.flight.config
        fc.cruise_speed = float(cfg.get("flight_speed", cfg.get("normal_flight_speed", 100.0)))
        fc.boost_speed = float(cfg.get("flight_boost_speed", cfg.get("max_boost_speed", 500.0)))
        boost_mult = max(1.5, fc.boost_speed / max(1.0, fc.cruise_speed))
        fc.acceleration = max(40.0, fc.cruise_speed * 0.5)
        fc.boost_acceleration = max(100.0, fc.acceleration * boost_mult)
        fc.braking_deceleration = cfg.get("air_braking_strength", 100.0)
        fc.steering_rate = cfg.get("flight_turn_speed", 125.0)
        fc.landing_speed = cfg.get("descent_speed", 24.0)
        fc.ground_impact_speed = cfg.get("impact_force", 95.0)
        fc.flight_inertia = cfg.get("flight_inertia", 0.70)
        fc.vertical_ascent_speed = cfg.get("vertical_ascent_speed", 25.0)
        fc.air_resistance = cfg.get("air_resistance", 0.000035)
        fc.atmospheric_drag = cfg.get("atmospheric_drag", 1.0)
        fc.gravity_multiplier = cfg.get("gravity_multiplier", 1.0)
        fc.maximum_falling_speed = cfg.get("maximum_falling_speed", 150.0)

        gm = self.ground
        ground_spd = float(cfg.get("ground_speed", cfg.get("ground_running_speed", 50.0)))
        gm.walk_speed = ground_spd
        gm.sprint_multiplier = cfg.get("sprint_multiplier", 2.5)
        gm.acceleration = max(48.0, ground_spd * 1.5)
        gm.deceleration = cfg.get("deceleration", 9.0)
        gm.max_running_speed = max(ground_spd, ground_spd * 1.5)
        gm.dash_speed = cfg.get("dash_speed", 80.0)
        gm.dash_duration = cfg.get("dash_duration", 0.25)
        gm.dash_cooldown = cfg.get("dash_cooldown", 1.0)

        tuning = self.tuning
        if tuning is None:
            return
        # Each percent setting multiplies the value derived above, so 100 keeps
        # every original number exactly.
        fc.boost_speed *= tuning.fraction("boost_multiplier_pct")
        fc.acceleration *= (tuning.fraction("flight_acceleration_pct")
                            * tuning.fraction("flight_responsiveness_pct"))
        fc.boost_acceleration *= (tuning.fraction("flight_acceleration_pct")
                                  * tuning.fraction("flight_responsiveness_pct"))
        fc.steering_rate *= tuning.fraction("flight_turning_pct")
        fc.vertical_ascent_speed *= tuning.fraction("vertical_speed_pct")
        fc.landing_speed *= tuning.fraction("vertical_speed_pct")
        fc.takeoff_impulse = tuning.number("takeoff_speed_dm", 75.0) * .1
        fc.horizontal_speed_scale = tuning.fraction("horizontal_speed_pct")
        gm.acceleration *= (tuning.fraction("ground_acceleration_pct")
                            * tuning.fraction("movement_responsiveness_pct"))
        gm.deceleration *= tuning.fraction("movement_responsiveness_pct")
        gm.max_running_speed = ground_spd * tuning.fraction("running_speed_pct")
        gm.walk_pace = tuning.number("walking_pace", 3.0) if self.controlled else None
        self._animation_rate = tuning.fraction("animation_speed_pct")
        self._posture_rate = 5.5 * tuning.fraction("flight_stability_pct")
        # Cape quality sets how many of the frames recompute the cloth.
        self._cape_step = min(1.0, max(0.0, tuning.fraction("cape_quality_pct")))

    def simulate(self, dt: float, move: SimVec3, vertical: float, *, boost: bool = False,
                 brake: bool = False, sprint: bool = False, ground_distance: float = 0.0,
                 steering_direction: SimVec3 | None = None, aimed: bool = False) -> None:
        dt = max(0.0, min(dt, .05))
        self._vertical_input = vertical
        self._animation_time += dt * self._animation_rate
        cfg = getattr(self.game, "sentry_config", None)
        planet = self.game.planet
        world_pos = SimVec3(self.x, self.y, self.z)
        local_up = planet.normal(world_pos)
        altitude = planet.altitude(world_pos)
        submerged = planet.is_ocean(world_pos) and altitude < 0.0
        if self.flight.is_flying:
            velocity = self.flight.step(move, vertical, dt, boost=boost, brake=brake,
                                        ground_distance=ground_distance,
                                        steering_direction=steering_direction, up=local_up,
                                        gravity=planet.gravity(world_pos),
                                        air_density=(0.0 if submerged else
                                                      self.game.environment.air_density(max(0.0, altitude))),
                                        aimed=aimed)
            # Dense water damps momentum and provides buoyancy
            if submerged:
                water_res = cfg.get("water_resistance", 1.8) if cfg else 1.8
                buoyancy = cfg.get("buoyancy_strength", 12.0) if cfg else 12.0
                velocity = velocity * exp(-water_res * dt)
                velocity = velocity + local_up * (buoyancy * dt)
                self.flight.velocity = velocity

            # Maximum flight altitude boundary
            max_alt = cfg.get("max_flight_altitude", 200000.0) if cfg else 200000.0
            next_pos = SimVec3(self.x + velocity.x * dt, self.y + velocity.y * dt,
                               self.z + velocity.z * dt)
            if altitude > max_alt:
                radial_v = velocity.x * local_up.x + velocity.y * local_up.y + velocity.z * local_up.z
                if radial_v > 0.0:
                    velocity = velocity - local_up * radial_v
                    self.flight.velocity = velocity
                next_pos = planet.project(next_pos, max_alt)

            if self.flight.phase is FlightPhase.GROUNDED:
                next_pos = planet.project(next_pos, .25)
            altitude_clamp = getattr(planet, "clamp_flight_altitude", None)
            if callable(altitude_clamp):
                next_pos = altitude_clamp(next_pos, velocity)
                self.flight.velocity = velocity
            self.position = Vec3(next_pos.x, next_pos.y, next_pos.z)
            self.game.world.resolve_sentry(self, previous_position=world_pos)
            self.local_yaw = rotate_towards_degrees(
                self.local_yaw, self.game.camera.yaw,
                self.flight.config.steering_rate * dt * 1.5)
            planet.orient_entity(self, SimVec3(self.x, self.y, self.z), self.local_yaw)
            self._update_flight_pose(dt, local_up)
            self.cape.rotation_x = sin(self._animation_time * 5.0) * (self.flight.speed_mps * .025)
        else:
            airborne = self.keeps_own_height
            velocity = self.ground.step(move, dt, sprint=sprint, coast=airborne)
            if airborne:
                self._step_super_jump(dt, world_pos, velocity)
            else:
                next_pos = planet.tangent_move(world_pos,
                                               SimVec3(velocity.x * dt, velocity.y * dt,
                                                       velocity.z * dt), .25)
                self.position = Vec3(next_pos.x, next_pos.y, next_pos.z)
                self.game.world.resolve_sentry(self, previous_position=world_pos)
                self._step_jump(dt)
            self.left_arm.rotation_z += (0.0 - self.left_arm.rotation_z) * min(1.0, dt * 8.0)
            self.right_arm.rotation_z += (0.0 - self.right_arm.rotation_z) * min(1.0, dt * 8.0)
            self._relax_elbows(dt)
            ground_turn_rate = cfg.get("turning_speed", 300.0) if cfg else 300.0
            self.local_yaw = rotate_towards_degrees(self.local_yaw,
                                                    self.game.camera.yaw, ground_turn_rate * dt)
            planet.orient_entity(self, SimVec3(self.x, self.y, self.z), self.local_yaw)
            pace = velocity.length()
            stride = min(1.0, pace / 4.0)
            running = min(1.0, pace / 28.0)  # a walk becomes a sprint: longer reach, quicker legs, arms pumping
            # The legs turn over exactly as fast as the ground goes by: one step is one half-turn of the cycle,
            # which is what keeps a planted foot from sliding, up to where legs can no longer follow at all.
            style = getattr(getattr(self, "visual", None), "style", DEFAULT_STYLE)
            step_length = (STEP_AT_WALK + (STEP_AT_RUN - STEP_AT_WALK) * running) * style.step
            before = self._stride_phase
            self._stride_phase += dt * min(MAX_STRIDE_RATE, pi * pace / step_length)
            swing = sin(self._stride_phase) * (24.0 + running * 34.0) * stride * style.stride
            if airborne:  # no strides in the air: one knee leads on the way up, and both come under him to land
                rising = self.jump_velocity > 0.0
                swing = 0.0
                self.left_leg.rotation_x += ((-26.0 if rising else -7.0) - self.left_leg.rotation_x) * blend_amount(dt)
                self.right_leg.rotation_x += ((7.0 if rising else -4.0) - self.right_leg.rotation_x) * blend_amount(dt)
            visual = getattr(self, "visual", None)
            self._hold_legs(.55 if airborne else (WALK_STANCE + (WALK_NARROW - WALK_STANCE) * stride if hasattr(visual, "walk") else 0.0), 0.0, dt)
            left_target, right_target = swing, -swing
            left_arm_target, right_arm_target = -swing * style.arm_swing, swing * style.arm_swing
            if hasattr(visual, "walk"):
                if airborne:
                    visual.set_gait(self._stride_phase, 0.0, 0.0, False)
                else:
                    position = SimVec3(self.x, self.y, self.z)
                    forward = planet.heading(position, self.local_yaw)
                    along_z = velocity.x * forward.x + velocity.y * forward.y + velocity.z * forward.z
                    along_x = velocity.x * forward.z - velocity.z * forward.x
                    turning = radians(((self.local_yaw - self._walk_yaw + 180.0) % 360.0) - 180.0) / max(dt, 1e-3)
                    left_target, right_target, left_arm_target, right_arm_target, running = visual.walk(dt, along_x, along_z, turning)
                    self._stride_phase = visual._gait_phase
                self._walk_yaw = self.local_yaw
            if pace > 1.0 and not airborne and int(self._stride_phase / pi) != int(before / pi):
                self._on_footfall(pace)
            for elbow in (self.left_elbow, self.right_elbow):
                # Never a straight arm at a walk, and bent hard to pump at a run.
                bent = min(style.walk_elbow, MIN_WALK_ELBOW) * stride * (1.0 - running) + style.run_elbow * running
                elbow.rotation_x += (bent - elbow.rotation_x) * min(1.0, dt * 8.0)
            # Just landed: ease out of the flying pose into the walk rather than snapping to it.
            self._pose_settling = max(0.0, self._pose_settling - dt)
            ease = blend_amount(dt) if self._pose_settling > 0.0 else 1.0
            if not airborne:
                self.left_leg.rotation_x += (left_target - self.left_leg.rotation_x) * ease
                self.right_leg.rotation_x += (right_target - self.right_leg.rotation_x) * ease
                if hasattr(visual, "walk"):  # the knees and feet follow what walking asked of them, even if the thigh stayed put
                    self.left_leg._follow()
                    self.right_leg._follow()
            self.left_arm.rotation_x += (left_arm_target - self.left_arm.rotation_x) * ease
            self.right_arm.rotation_x += (right_arm_target - self.right_arm.rotation_x) * ease
            self.cape.rotation_x = sin(self._animation_time * 3.0) * 4.0
        self._update_airflow(dt, local_up)
        # The torso goes with the arms: upright with hands on hips, along the travel when reaching.
        neutral_intent = self.flight_pose != REACHING
        self._update_flight_posture(dt, local_up, False, neutral_intent)
        self._deform_cape()

        wind = min(1.0, sqrt(self._airflow_forward ** 2
                             + self._airflow_right ** 2) / 240.0)
        for index, lock in enumerate(self.hair_locks):
            phase = self._animation_time * (5.0 + wind * 4.0) + index * .9
            swing = sin(phase) * (0.45 + wind * 3.2)
            lock.rotation_x = max(-12.0, min(12.0,
                                     self._airflow_forward * -.025 + swing))
            lock.rotation_z = max(-8.0, min(8.0,
                                    self._airflow_right * -.018
                                    + cos(phase * .83) * (0.35 + wind * 1.5)))

        final_pos = SimVec3(self.x, self.y, self.z)
        final_up = planet.normal(final_pos)
        radial_speed = (self.flight.velocity.x * final_up.x
                        + self.flight.velocity.y * final_up.y
                        + self.flight.velocity.z * final_up.z)
        heat = self.game.environment.reentry_heat(
            max(0.0, planet.altitude(final_pos)), self.flight.speed_mps, radial_speed)
        self.reentry_glow.color = color.rgba32(255, 90, 25, round(105 * heat))

    def _update_flight_pose(self, dt: float, up: SimVec3) -> None:
        """Arms and legs while flying, from the real velocity, blended and never snapped."""
        flight = self.flight
        if flight.phase is FlightPhase.LANDING:
            self.flight_pose = DESCENDING  # coming down to stand, not diving: the arms out for balance
        elif flight.phase is FlightPhase.TAKEOFF and not self.thrusting:
            self.flight_pose = ASCENDING
        else:
            forward = self.game.planet.heading(SimVec3(self.x, self.y, self.z), self.local_yaw)
            self.flight_pose = choose_pose(self.flight_pose, flight.velocity, forward, up, self.thrusting, self._vertical_input)
        pose = POSES[self.flight_pose]
        visual = getattr(self, "visual", None)
        if hasattr(visual, "walk"):
            visual.set_gait(self._stride_phase, 0.0, 0.0, False)  # a running take-off leaves the walk behind
        blend = blend_amount(dt)
        for arm, elbow, side in ((self.left_arm, self.left_elbow, 1.0), (self.right_arm, self.right_elbow, -1.0)):
            arm.rotation_x += (pose.shoulder_x - arm.rotation_x) * blend
            arm.rotation_z += (pose.shoulder_z * side - arm.rotation_z) * blend
            elbow.rotation_x += (pose.elbow_x - elbow.rotation_x) * blend
            elbow.rotation_z += (pose.elbow_z * side - elbow.rotation_z) * blend
        style = getattr(getattr(self, "visual", None), "style", DEFAULT_STYLE)
        reaching = self.flight_pose == REACHING
        if reaching:  # everyone reaches ahead; how they carry the other arm is their own
            self.right_arm.rotation_x += style.flight_right_x * blend
            self.right_arm.rotation_z += style.flight_right_z * blend
            self.right_elbow.rotation_x += style.flight_elbow * blend
        self.left_leg.rotation_x += (pose.left_leg_x - self.left_leg.rotation_x) * blend
        self.right_leg.rotation_x += (pose.right_leg_x - self.right_leg.rotation_x) * blend
        self._hold_legs(1.0, POINTED_BY_POSE[self.flight_pose], dt)
        self._pose_settling = POSE_SETTLE_SECONDS

    def _hold_legs(self, together: float, pointed: float, dt: float) -> None:
        """Only the skinned bodies have ankles and knees to hold."""
        visual = getattr(self, "visual", None)
        if hasattr(visual, "hold_legs"):
            visual.hold_legs(together, pointed, blend_amount(dt))

    def _relax_elbows(self, dt: float) -> None:
        """Back to straight arms, for walking and for attacks that pose the arm themselves."""
        blend = blend_amount(dt)
        for elbow in (self.left_elbow, self.right_elbow):
            elbow.rotation_x -= elbow.rotation_x * blend
            elbow.rotation_z -= elbow.rotation_z * blend

    def _update_flight_posture(self, dt: float, up: SimVec3,
                               backward_intent: bool = False,
                               neutral_intent: bool = False, velocity: SimVec3 | None = None) -> None:
        position = SimVec3(self.x, self.y, self.z)
        forward = self.game.planet.heading(position, self.local_yaw)
        pitch, bank = flight_posture(self.flight.velocity if velocity is None else velocity, forward, up,
                                     backward_intent=backward_intent,
                                     neutral_intent=neutral_intent)
        # Turning at speed the body rolls into the turn, as anything flying has to.
        rate = (((self.local_yaw - self._last_yaw + 180.0) % 360.0) - 180.0) / max(dt, 1e-3)
        self._last_yaw = self.local_yaw
        if self.flight.is_flying:
            bank += max(-MAX_TURN_BANK, min(MAX_TURN_BANK, rate * TURN_BANK)) * min(1.0, self.flight.speed_mps / BANK_FULL_SPEED)
        pitch_quat = LQuaternionf()
        pitch_quat.setFromAxisAngle(pitch, LVector3f(1, 0, 0))
        bank_quat = LQuaternionf()
        bank_quat.setFromAxisAngle(bank, LVector3f(0, 0, 1))
        target = pitch_quat * bank_quat
        current = self.pose_root.getQuat()
        current_values = (current.getR(), current.getI(), current.getJ(), current.getK())
        target_values = (target.getR(), target.getI(), target.getJ(), target.getK())
        blend = 1.0 - exp(-max(0.0, dt) * self._posture_rate)
        smooth = quaternion_slerp(current_values, target_values, blend)
        self.pose_root.setQuat(LQuaternionf(*smooth))

    def _update_airflow(self, dt: float, up: SimVec3) -> None:
        position = SimVec3(self.x, self.y, self.z)
        forward = self.game.planet.heading(position, self.local_yaw)
        right = cross(up, forward).normalized()
        if self.flight.is_flying:
            target_forward = -dot(self.flight.velocity, forward)
            target_right = -dot(self.flight.velocity, right)
        else:
            target_forward = target_right = 0.0
        blend = 1.0 - exp(-max(0.0, dt) * 3.5)
        self._airflow_forward += (target_forward - self._airflow_forward) * blend
        self._airflow_right += (target_right - self._airflow_right) * blend

    def _deform_cape(self) -> None:
        self._cape_progress += self._cape_step
        if self._cape_progress < 1.0:
            return
        self._cape_progress -= 1.0
        speed = self.flight.speed_mps if self.flight.is_flying else 0.0
        wind = min(1.0, speed / 150.0)
        if native.available:
            if self._native_cape is None:
                self._native_cape = native.CapeGrid(self._cape_rows, self._cape_cols, self._cape_vertices)
            vertices, trim_vertices = self._native_cape.deform(self._animation_time, wind, self._airflow_forward,
                                                               self._airflow_right)
            self.cape_mesh.vertices = vertices
            self.cape_mesh.generate()
            self.cape_trim_mesh.vertices = trim_vertices
            self.cape_trim_mesh.generate()
            return
        vertices = []
        for row in range(self._cape_rows):
            for col in range(self._cape_cols):
                original = self._cape_vertices[row * self._cape_cols + col]
                wave = sin(self._animation_time * 7.0 + col * .72 + row * .55)
                row_alpha = row / max(1, self._cape_rows - 1)
                vertices.append((original[0] + wave * .055 * wind * row_alpha,
                                 original[1], original[2]
                                 + max(-.34, min(.34, self._airflow_forward / 520.0))
                                 * row_alpha
                                 + max(-.22, min(.22, self._airflow_right / 520.0))
                                 * row_alpha
                                 - abs(wave) * .34 * wind * row_alpha
                                 - max(0.0, wave) * .045 * wind * row_alpha))
        self.cape_mesh.vertices = vertices
        self.cape_mesh.generate()
        trim_vertices, _ = self._cape_trim_geometry(vertices)
        self.cape_trim_mesh.vertices = trim_vertices
        self.cape_trim_mesh.generate()

    @property
    def has_super_jump(self) -> bool:
        return False

    @property
    def keeps_own_height(self) -> bool:
        """In the air on a super jump: the world leaves its height alone, and only stops it hitting things."""
        return self.has_super_jump and (self.jump_height > 0.0 or self.jump_velocity != 0.0)

    def start_jump(self, strength: float, power: float = 1.0) -> bool:
        """An ordinary hop from the ground, with no flight state involved."""
        if self.has_super_jump:
            if strength <= 0.0 or self.flight.is_flying:
                return False
            self.jump_power = max(.01, power)
            self.jump_velocity = min(MAX_JUMP_SPEED, max(self.jump_velocity, 0.0) + strength * SUPER_TAP_SCALE)
            self.jump_hold_left = SUPER_HOLD_SECONDS
            return True
        if (strength <= 0.0 or self.flight.is_flying or self.jump_height > 0.0
                or self.jump_velocity != 0.0):
            return False
        self.jump_velocity = float(strength)
        return True

    def super_launch(self, power: float = 1.0) -> None:
        """F on the ground. Straight up, and whatever he was doing across the ground carries on."""
        self.jump_power = max(.01, power)
        self.jump_velocity = min(MAX_JUMP_SPEED, SUPER_LAUNCH_SPEED * self.jump_power)
        self.jump_hold_left = SUPER_HOLD_SECONDS

    def leap(self, upward: float, across: SimVec3) -> None:
        """A launch worked out in advance, for AI: no key to hold, and it knows where it is going."""
        self.jump_velocity = max(-MAX_JUMP_SPEED, min(MAX_JUMP_SPEED, float(upward)))
        self.jump_hold_left = 0.0
        self.ground.velocity = across

    def _step_super_jump(self, dt: float, start: SimVec3, across: SimVec3) -> None:
        """One step of the leap along its real path, so the world can stop it at whatever it hits."""
        vertical = self.jump_velocity
        if self.jump_hold_left > 0.0:
            if self.jump_held:
                vertical += SUPER_THRUST * self.jump_power * dt
                self.jump_hold_left = max(0.0, self.jump_hold_left - dt)
            else:
                self.jump_hold_left = 0.0  # the key came up: this leap gets no more
        vertical = max(-MAX_JUMP_SPEED, min(MAX_JUMP_SPEED, fall_with_air(vertical, JUMP_GRAVITY, dt, SUPER_JUMP_TERMINAL)))
        world = self.game.world
        wanted_y = min(SAFE_ALTITUDE, start.y + vertical * dt)
        x, z = start.x + across.x * dt, start.z + across.z * dt
        self.position = Vec3(x, wanted_y, z)
        self.jump_height = max(0.0, wanted_y - (world.height_at(x, z) + .25))
        self.jump_velocity = vertical if vertical != 0.0 else -1e-6
        world.resolve_sentry(self, previous_position=start)
        y = float(self.y)
        if y > wanted_y + 1e-3 and vertical < 0.0:
            self.jump_velocity = -1e-6  # came down onto something
        elif y < wanted_y - 1e-3 and vertical > 0.0:
            self.jump_velocity = -1e-6  # came up under something
            self.jump_hold_left = 0.0
        floor = world.height_at(float(self.x), float(self.z)) + .25
        if y <= floor + 1e-3 and self.jump_velocity <= 0.0:
            self._land_super_jump(-vertical, floor)
        else:
            self.jump_height = max(0.0, y - floor)

    def _land_super_jump(self, speed: float, floor: float) -> None:
        self.y = floor
        self.jump_height = self.jump_velocity = self.jump_hold_left = 0.0
        if speed < SUPER_LANDING_SPEED:
            return
        game = self.game
        point = SimVec3(float(self.x), floor, float(self.z))
        game.world.terrain_impact(point, radius=min(9.0, 1.5 + speed * .015), depth=min(2.0, speed * .004),
                                  intensity=.7, surface="super-jump-landing")
        self.y = game.world.height_at(point.x, point.z) + .25
        combat = getattr(game, "combat", None)
        if combat is not None:
            combat.puffs.emit(point, SimVec3(0.0, 8.0, 0.0), (190, 170, 140, 210), size=2.0, grow=min(14.0, speed * .05),
                              life=.6)
        if getattr(self, "controlled", False):
            game.camera_impulse = max(game.camera_impulse, min(2.5, speed * .008))

    def _step_jump(self, dt: float) -> None:
        if self.jump_velocity == 0.0 and self.jump_height <= 0.0:
            return
        self.jump_height += self.jump_velocity * dt
        gravity = JUMP_GRAVITY * (JUMP_CUT_GRAVITY if self._jump_cut and self.jump_velocity > 0.0 else 1.0)
        self.jump_velocity = fall_with_air(self.jump_velocity, gravity, dt)
        if self.jump_height <= 0.0:
            self.jump_height = self.jump_velocity = 0.0
            self._jump_cut = False
        self.y += self.jump_height

    def cut_jump(self) -> None:
        """Jump released: an ordinary hop rising now comes down sooner, so a tap is lower than a press."""
        if self.jump_velocity > 0.0 and not self.has_super_jump:
            self._jump_cut = True

    def _on_footfall(self, pace: float) -> None:
        """Only the characters themselves know about steps: the older body has none to show."""

    @property
    def flight_status(self) -> str:
        return self.flight.phase.name.replace("_", " ")
