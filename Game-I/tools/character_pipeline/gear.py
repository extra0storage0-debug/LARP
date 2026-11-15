"""Costume pieces in real geometry, on each body's own surface, so they always fit.

The same description of a piece does two jobs. On the mesh, the body swells smoothly under it, which changes the silhouette.
In the texture, where it can be far sharper than the mesh, it paints the piece's material, a crisp edge and a bevel.
Helmets, collars, feathers, buckles and pouches are separate solid meshes. Colours are sRGB; a mesh piece's vertex alpha
carries how metallic it is, and roughness follows from it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Shell:
    mask: np.ndarray       # per vertex of the body's topology
    lift: float            # how far it stands off the body
    color: tuple
    metal: float = 0.0
    node: str = "gear"     # "helmet" pieces can be switched off by the Helmet setting


def rgb(r: int, g: int, b: int) -> tuple:
    return (r / 255.0, g / 255.0, b / 255.0)


def shells_for(spec, C: dict, canon) -> list:
    """Each adaptation's armour. Written in the shared canonical pose, for vertices or texels alike, so it suits every body."""
    x, y, z, ax = C["x"], C["y"], C["z"], np.abs(C["x"])
    arm, leg = C["arm"] > .5, C["leg"] > .5
    s_arm, s_leg, head = C["s_arm"], C["s_leg"], C["head"]
    pelvis = canon.joints["pelvis"][1]
    torso = (~arm) & (~leg) & (head < .5)
    belt = (~arm) & (head < .3) & (np.abs(y - (pelvis + .075)) < .048)
    gloves = arm & (s_arm >= 1.74)
    boots = leg & (s_leg >= 1.56)
    cuffs = arm & (np.abs(s_arm - 1.74) < .05)
    boot_tops = leg & (np.abs(s_leg - 1.56) < .05)
    shoulders = (arm & (s_arm < .30)) | (torso & (ax > .17) & (y > 2.20))
    neck = (head < .55) & (y > 2.34) & (y < 2.47) & (~arm)
    name = spec.name
    shells: list = []

    if name == "RED":  # The Boys, on screen: olive, heavy armour, leather, a scarf at the throat.
        armour, dark, olive = rgb(52, 58, 44), rgb(36, 40, 34), rgb(60, 72, 48)
        leather, brass = rgb(96, 64, 40), rgb(160, 128, 70)
        for side in (x < -.012, x > .012):
            shells.append(Shell(torso & side & (y > 2.02) & (y < 2.30) & (z > -.02), .026, armour, .45))  # pectoral plate
            shells.append(Shell(torso & side & (y > 1.86) & (y < 1.99) & (z > -.02), .022, dark, .4))
            shells.append(Shell(torso & side & (y > 1.68) & (y < 1.83) & (z > -.02), .018, dark, .4))
        shells.append(Shell(torso & (y > 1.72) & (y < 2.30) & (z <= -.04), .018, dark, .3))                # back plate
        shells.append(Shell(shoulders & (y > 2.1), .03, armour, .45))
        shells.append(Shell(belt, .018, leather, .1))
        shells.append(Shell(gloves, .007, leather, .05))
        shells.append(Shell(cuffs, .016, dark, .35))
        shells.append(Shell(arm & (s_arm > 1.25) & (s_arm < 1.68) & (C["nz"] > -.3), .012, dark, .35))     # forearm guards
        shells.append(Shell(boots, .014, leather, .05))
        shells.append(Shell(boot_tops, .022, dark, .1))
        shells.append(Shell(leg & (np.abs(s_leg - 1.0) < .12) & (C["nz"] > -.1), .02, dark, .35))          # knee guards
        cap = (head > .5) & (y > canon.eye_y + .035)
        shells.append(Shell(cap, .03, rgb(62, 70, 48), .25, "helmet"))
    elif name == "WHITE":  # Man of Steel: dark, textured, one raised silver shield, nothing else on it.
        shells.append(Shell(belt & (z > -.03), .004, rgb(40, 54, 96), .45))
        shells.append(Shell(boots, .006, rgb(24, 38, 80), .15))
    elif name == "YELLOW":  # Blue and gold, Marvel's Sentry.
        gold = rgb(240, 186, 52)
        shells.append(Shell(belt, .01, gold, .8))
        shells.append(Shell(gloves, .006, gold, .55))
        shells.append(Shell(boots, .008, gold, .55))
        shells.append(Shell(cuffs | boot_tops, .012, gold, .8))
        shells.append(Shell(neck & (y < 2.45), .008, gold, .6))
    elif name == "GREEN":  # Invincible, animated: white, with red shoulders and chest and a big collar.
        red = rgb(176, 26, 38)
        shells.append(Shell(torso & (y > 2.09) & (y < 2.34) & (z > -.1), .006, red, .05))
        shells.append(Shell(shoulders, .008, red, .05))
        shells.append(Shell(gloves | cuffs, .007, red, .05))
        shells.append(Shell(boots | boot_tops, .009, red, .05))
        shells.append(Shell(belt, .006, red, .05))
    elif name == "BLACK":  # The Boys, on screen: royal blue, gold eagle at the shoulders, chest and waist, red at the ends.
        gold, red = rgb(208, 166, 70), rgb(160, 24, 32)
        shells.append(Shell(shoulders & (y > 2.12), .024, gold, .9))
        shells.append(Shell(neck & (y < 2.45), .012, gold, .85))
        shells.append(Shell(belt, .012, gold, .9))
        shells.append(Shell(gloves, .006, red, .1))
        shells.append(Shell(cuffs | boot_tops, .012, gold, .85))
        shells.append(Shell(boots, .009, red, .1))
    return [shell for shell in shells if shell.mask.any()]


def extrude(positions: np.ndarray, normals: np.ndarray, triangles: np.ndarray, position_index: np.ndarray, shell: Shell):
    """One shell's vertices, normals, colours and triangles. Triangles here wind as the body's drawing order does."""
    keep = shell.mask[triangles].all(axis=1)
    faces = triangles[keep]
    if len(faces) == 0:
        return None
    used, compact = np.unique(faces, return_inverse=True)
    compact = compact.reshape(-1, 3)
    top = positions[used] + normals[used] * shell.lift
    base = positions[used] - normals[used] * .002
    count = len(used)
    # The edge: a side made from every edge used by one triangle only, joined across UV seams by true position.
    welded = position_index[used]
    edges: dict = {}
    for face in compact:
        for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            key = (min(welded[a], welded[b]), max(welded[a], welded[b]))
            edges.setdefault(key, []).append((a, b))
    sides = []
    for pairs in edges.values():
        if len(pairs) == 1:
            a, b = pairs[0]
            sides.extend(((a, b + count, b), (a, a + count, b + count)))
    vertices = np.concatenate((top, base))
    vertex_normals = np.concatenate((normals[used], normals[used]))
    colors = np.ones((count * 2, 4), dtype=np.float32)
    colors[:, :3] = shell.color
    colors[count:, :3] = np.array(shell.color) * .55  # it darkens into the crease against the body
    colors[:, 3] = shell.metal
    all_faces = np.concatenate((compact, np.array(sides, dtype=np.int64).reshape(-1, 3)))
    return vertices, vertex_normals, colors, all_faces, used


def box(center, axis_y, axis_x, half_width, half_length, half_thick, color, metal, taper=.25):
    """A small solid piece: feathers, buckles, pouches. Eight corners, six faces, flat-shaded by giving each face its own."""
    center, axis_y, axis_x = (np.asarray(v, dtype=np.float64) for v in (center, axis_y, axis_x))
    axis_y = axis_y / np.linalg.norm(axis_y)
    axis_x = axis_x - axis_y * (axis_x @ axis_y)
    axis_x = axis_x / np.linalg.norm(axis_x)
    axis_z = np.cross(axis_x, axis_y)
    corners = []
    for sy in (-1.0, 1.0):
        width = half_width * (taper if sy < 0 else 1.0)
        for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corners.append(center + axis_y * sy * half_length + axis_x * sx * width + axis_z * sz * half_thick)
    corners = np.array(corners)
    quads = ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0))
    vertices, normals, faces = [], [], []
    for quad in quads:
        points = corners[list(quad)]
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        length = np.linalg.norm(normal)
        normal = normal / length if length else axis_z
        base = len(vertices)
        vertices.extend(points)
        normals.extend((normal,) * 4)
        faces.extend(((base, base + 1, base + 2), (base, base + 2, base + 3)))
    colors = np.ones((len(vertices), 4), dtype=np.float32)
    colors[:, :3] = color
    colors[:, 3] = metal
    return np.array(vertices), np.array(normals), colors, np.array(faces)


def ring(center, half_x: float, half_z: float, height: float, flare: float, color: tuple, metal: float, folds: float = 0.0, segments: int = 22):
    """A band round the neck: a collar or a wrapped scarf, wider at the top by ``flare``, thick enough to have an inside."""
    center = np.asarray(center, dtype=np.float64)
    profile = ((0.0, 0.0, 1.0), (.5, .35, 1.0), (1.0, 1.0, 1.0), (1.0, .82, .86), (0.0, 0.0, .86))  # height, flare, thickness share
    vertices, normals, faces = [], [], []
    rows = len(profile)
    for column in range(segments):
        angle = 2.0 * np.pi * column / segments
        fold = 1.0 + folds * np.sin(angle * 7.0)
        for up, out, share in profile:
            radius_x = (half_x + flare * out) * share * fold
            radius_z = (half_z + flare * out) * share * fold
            vertices.append(center + np.array((np.cos(angle) * radius_x, up * height, np.sin(angle) * radius_z)))
            normal = np.array((np.cos(angle), .25 if share == 1.0 else -.25, np.sin(angle))) * (1.0 if share == 1.0 else -1.0)
            normals.append(normal / np.linalg.norm(normal))
    for column in range(segments):
        following = (column + 1) % segments
        for row in range(rows - 1):
            a, b = column * rows + row, following * rows + row
            c, d = following * rows + row + 1, column * rows + row + 1
            faces.extend(((a, b, c), (a, c, d)))
    colors = np.ones((len(vertices), 4), dtype=np.float32)
    colors[:, :3] = color
    colors[:, 3] = metal
    return np.array(vertices), np.array(normals), colors, np.array(faces)


def ornaments_for(spec, joints: dict, neck: tuple) -> list:
    """Pieces that are not the body's surface: (bone, mesh). Positions are this body's own, in the bind pose."""
    pieces = []
    center, half_x, half_z = neck
    low = (center[0], center[1] - .045, center[2])
    if spec.name == "GREEN":  # the large red collar
        pieces.append(("spine_03", ring(low, half_x - .004, half_z - .004, .07, .028, rgb(176, 26, 38), .05)))
    elif spec.name == "RED":  # the wrapped scarf, in folds
        pieces.append(("spine_03", ring(low, half_x + .004, half_z + .004, .07, .008, rgb(62, 74, 50), .0, folds=.035)))
    if spec.name == "BLACK":
        gold = rgb(214, 172, 74)
        for side, sign in (("l", -1.0), ("r", 1.0)):
            shoulder = joints[f"upperarm_{side}"]
            elbow = joints[f"lowerarm_{side}"]
            along = (elbow - shoulder) / np.linalg.norm(elbow - shoulder)
            outward = np.array((sign, 0.0, 0.0))
            for index in range(5):  # eagle feathers fanned over the top of the arm
                fan = (index - 2) * .34
                spot = shoulder + along * .12 + np.array((0.0, .055, fan * .15)) + outward * .025
                pieces.append((f"upperarm_{side}", box(spot, -along + np.array((0.0, 0.0, fan * .5)), np.array((0.0, 0.0, 1.0)), .036, .085, .010, gold, .9)))
    elif spec.name == "RED":
        leather, brass = rgb(84, 56, 36), rgb(166, 134, 74)
        pelvis = joints["pelvis"]
        front = pelvis[2] + .21
        y = pelvis[1] + .075
        pieces.append(("pelvis", box((0.0, y, front), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), .045, .036, .012, brass, .9, taper=1.0)))  # buckle
        for sign in (-1.0, 1.0):  # equipment pouches
            pieces.append(("pelvis", box((sign * .19, y - .012, front - .055), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), .042, .05, .026, leather, .05, taper=1.0)))
            pieces.append(("pelvis", box((sign * .27, y - .012, front - .15), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), .036, .046, .024, leather, .05, taper=1.0)))
    return pieces
