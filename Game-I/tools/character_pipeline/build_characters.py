"""Bake every character: skinned LOD meshes (.bam), hair and beard cards, costume textures.

Run with the game's interpreter:  python tools/character_pipeline/build_characters.py [NAME ...] [--size 2048]
Outputs go to assets/characters/<NAME>/. No Blender or paid tool is involved.
"""

from __future__ import annotations

import argparse
import heapq
import json
import os
from math import cos, pi, sin
from pathlib import Path
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import costumes  # noqa: E402
import gear  # noqa: E402
import mesh_source as ms  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets" / "characters"
HEIGHT = 3.10        # head top to soles, in game units: the old body's figure, so every gameplay offset still fits
FOOT_Y = -.25
CANONICAL = dict(muscle=1.0, weight=.5, height=.7)


def smooth(low, high, x):
    t = np.clip((x - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class Frame:
    """Object space to game space: x is flipped (the character's left is -x in the game) and feet stand at FOOT_Y."""

    def __init__(self, vertices: np.ndarray, body: np.ndarray) -> None:
        self.floor = vertices[body, 1].min()
        self.scale = HEIGHT / (vertices[body, 1].max() - self.floor)

    def __call__(self, points: np.ndarray) -> np.ndarray:
        out = np.array(points, dtype=np.float64) * self.scale
        out[..., 0] *= -1.0
        out[..., 1] += FOOT_Y - self.floor * self.scale
        return out


# -- mesh topology, shared by all characters --------------------------------------------------------------------
class Topology:
    def __init__(self, base: ms.BaseMesh) -> None:
        pairs = np.stack((base.quads.ravel(), base.quad_uvs.ravel()), axis=1)
        unique, inverse = np.unique(pairs, axis=0, return_inverse=True)
        self.position_index = unique[:, 0]
        self.uv = base.uvs[unique[:, 1]].astype(np.float32)
        q = inverse.reshape(-1, 4)
        # OBJ faces are counter-clockwise seen from outside; the game's handedness is flipped, and so is x.
        self.triangles = np.concatenate((q[:, [0, 1, 2]], q[:, [0, 2, 3]]), axis=0).astype(np.int32)


def vertex_normals(positions: np.ndarray, triangles: np.ndarray, position_index: np.ndarray | None = None) -> np.ndarray:
    a, b, c = positions[triangles[:, 0]], positions[triangles[:, 1]], positions[triangles[:, 2]]
    face = np.cross(b - a, c - a)
    normals = np.zeros_like(positions)
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], face)
    if position_index is not None:  # seams: split vertices share one smooth normal
        shared = np.zeros((position_index.max() + 1, 3))
        np.add.at(shared, position_index, normals)
        normals = shared[position_index]
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    return normals / np.maximum(length, 1e-9)


def simplify(positions: np.ndarray, triangles: np.ndarray, locked: np.ndarray, target: int) -> np.ndarray:
    """Quadric edge collapse on one body; the result is reused by all, since they share their topology."""
    n = len(positions)
    alive_tri = np.ones(len(triangles), dtype=bool)
    tris = triangles.copy()
    a, b, c = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
    normal = np.cross(b - a, c - a)
    area = np.linalg.norm(normal, axis=1, keepdims=True)
    normal = normal / np.maximum(area, 1e-12)
    plane = np.concatenate((normal, -(normal * a).sum(axis=1, keepdims=True)), axis=1)
    quadrics = np.zeros((n, 4, 4))
    outer = plane[:, :, None] * plane[:, None, :] * area[:, None]
    for corner in range(3):
        np.add.at(quadrics, tris[:, corner], outer)
    vertex_tris = [set() for _ in range(n)]
    for index, tri in enumerate(tris):
        for vertex in tri:
            vertex_tris[vertex].add(index)
    parent = np.arange(n)

    def cost(u: int, v: int) -> float:
        p = np.append(positions[v], 1.0)
        return float(p @ (quadrics[u] + quadrics[v]) @ p)

    heap = []
    for tri in tris:
        for u, v in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            for x, y in ((u, v), (v, u)):
                if not locked[x]:
                    heap.append((cost(x, y), int(x), int(y)))
    heapq.heapify(heap)
    count = len(tris)
    version = np.zeros(n, dtype=np.int32)
    stamped = [(c, u, v, 0, 0) for c, u, v in heap]
    heapq.heapify(stamped)
    while count > target and stamped:
        _, u, v, stamp_u, stamp_v = heapq.heappop(stamped)
        if parent[u] != u or parent[v] != v or version[u] != stamp_u or version[v] != stamp_v:
            continue
        # u collapses onto v. Refuse if it would flip a triangle.
        flips = False
        for t in vertex_tris[u]:
            if not alive_tri[t] or v in tris[t]:
                continue
            i, j, k = tris[t]
            old = np.cross(positions[j] - positions[i], positions[k] - positions[i])
            moved = [positions[v] if x == u else positions[x] for x in (i, j, k)]
            new = np.cross(moved[1] - moved[0], moved[2] - moved[0])
            if old @ new <= 1e-14:
                flips = True
                break
        if flips:
            continue
        for t in list(vertex_tris[u]):
            if not alive_tri[t]:
                continue
            if v in tris[t]:
                alive_tri[t] = False
                count -= 1
                for x in tris[t]:
                    vertex_tris[x].discard(t)
            else:
                tris[t][tris[t] == u] = v
                vertex_tris[v].add(t)
        parent[u] = v
        quadrics[v] += quadrics[u]
        version[v] += 1
        neighbours = set()
        for t in vertex_tris[v]:
            if alive_tri[t]:
                neighbours.update(int(x) for x in tris[t])
        neighbours.discard(v)
        for w in neighbours:
            version[w] += 1
        for w in neighbours:
            if not locked[w]:
                heapq.heappush(stamped, (cost(w, v), w, v, int(version[w]), int(version[v])))
            if not locked[v]:
                heapq.heappush(stamped, (cost(v, w), v, w, int(version[v]), int(version[w])))
    return tris[alive_tri]


# -- texture space ----------------------------------------------------------------------------------------------
class TexelMap:
    """For every texel: which triangle it lies in, and where. Any vertex channel can then be read off instantly."""

    def __init__(self, uv: np.ndarray, triangles: np.ndarray, size: int) -> None:
        self.size = size
        self.tri = np.full((size, size), -1, dtype=np.int32)
        self.bary = np.zeros((size, size, 3), dtype=np.float32)
        self.triangles = triangles
        px = np.empty_like(uv, dtype=np.float64)
        px[:, 0] = uv[:, 0] * size - .5
        px[:, 1] = (1.0 - uv[:, 1]) * size - .5
        corners = px[triangles]
        low = np.floor(corners.min(axis=1) - 1.0).astype(np.int32).clip(0, size - 1)
        high = np.ceil(corners.max(axis=1) + 1.0).astype(np.int32).clip(0, size - 1)
        for index, (t, lo, hi) in enumerate(zip(corners, low, high)):
            xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
            a, b, c = t
            det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(det) < 1e-12:
                continue
            w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / det
            w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / det
            w2 = 1.0 - w0 - w1
            pad = 1.2 / max(np.ptp(t[:, 0]), np.ptp(t[:, 1]), 1.0)
            inside = (w0 >= -pad) & (w1 >= -pad) & (w2 >= -pad)
            yy, xx = ys[inside], xs[inside]
            self.tri[yy, xx] = index
            self.bary[yy, xx, 0] = w0[inside]
            self.bary[yy, xx, 1] = w1[inside]
            self.bary[yy, xx, 2] = w2[inside]
        self.valid = self.tri >= 0

    def read(self, values: np.ndarray) -> np.ndarray:
        corners = self.triangles[np.clip(self.tri, 0, None)]
        if values.ndim == 1:
            return (values[corners[..., 0]] * self.bary[..., 0] + values[corners[..., 1]] * self.bary[..., 1]
                    + values[corners[..., 2]] * self.bary[..., 2]).astype(np.float32)
        return (values[corners[..., 0]] * self.bary[..., 0, None] + values[corners[..., 1]] * self.bary[..., 1, None]
                + values[corners[..., 2]] * self.bary[..., 2, None]).astype(np.float32)


def fractal_noise(size: int, seed: int, base: int = 4, octaves: int = 6, falloff: float = .55) -> np.ndarray:
    rng = np.random.default_rng(seed)
    total, amplitude, sum_amp = np.zeros((size, size), dtype=np.float32), 1.0, 0.0
    cells = base
    for _ in range(octaves):
        layer = Image.fromarray(rng.random((cells, cells), dtype=np.float32), mode="F").resize((size, size), Image.BICUBIC)
        total += np.asarray(layer, dtype=np.float32) * amplitude
        sum_amp += amplitude
        amplitude *= falloff
        cells = min(size, cells * 2)
    return total / sum_amp


def dilate(image: np.ndarray, valid: np.ndarray, passes: int = 10) -> np.ndarray:
    """Spread colour past the UV islands so mip maps and seams never show the empty background."""
    out, mask = image.copy(), valid.copy()
    for _ in range(passes):
        grown = np.zeros_like(out)
        count = np.zeros(mask.shape, dtype=np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            shifted = np.roll(np.roll(mask, dy, 0), dx, 1)
            grown += np.roll(np.roll(out * mask[..., None] if out.ndim == 3 else out * mask, dy, 0), dx, 1)
            count += shifted
        fill = (~mask) & (count > 0)
        if out.ndim == 3:
            out[fill] = grown[fill] / count[fill, None]
        else:
            out[fill] = grown[fill] / count[fill]
        mask = mask | fill
    return out


class Canon:
    """Canonical channels per vertex and per texel. Costume zones live here, so all bodies share one layout."""

    def __init__(self, base: ms.BaseMesh, topo: Topology, weights: np.ndarray, size: int) -> None:
        vertices = ms.build_body(base, **CANONICAL)
        self.frame = Frame(vertices, base.groups["body"])
        positions = self.frame(vertices)
        self.joints = {name: self.frame(p) for name, p in ms.joint_positions(base, vertices).items()}
        self.eye_y = float(self.frame(vertices[base.groups["joint-l-eye"]].mean(axis=0))[1])
        self.eye_x = abs(float(self.frame(vertices[base.groups["joint-l-eye"]].mean(axis=0))[0]))
        # The rig's mouth joint is the jaw's hinge. The real mouth is where the teeth meet.
        upper = self.frame(vertices[base.groups["helper-upper-teeth"]])
        lower = self.frame(vertices[base.groups["helper-lower-teeth"]])
        self.mouth = np.array((0.0, (upper[:, 1].min() + lower[:, 1].max()) * .5, upper[:, 2].max()))
        v = positions[topo.position_index]
        normals = vertex_normals(v, topo.triangles[:, [0, 2, 1]], topo.position_index)
        w = weights[topo.position_index]
        index = {name: i for i, name in enumerate(ms.GAME_JOINTS)}
        total = lambda *names: sum(w[:, index[n]] for n in names)
        arm = total("upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r")
        leg = total("thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r")
        head = total("head")
        neck = total("neck_01")
        s_arm = self._along(v, ("upperarm", "lowerarm", "hand"), positions, base)
        s_leg = self._along(v, ("thigh", "calf", "foot"), positions, base)
        self.vertex = dict(x=v[:, 0], y=v[:, 1], z=v[:, 2], nx=normals[:, 0], ny=normals[:, 1], nz=normals[:, 2], arm=arm, leg=leg,
                           head=head, neck=neck, s_arm=s_arm, s_leg=s_leg)
        self.positions = positions
        self.map = TexelMap(topo.uv, topo.triangles, size)
        self.texel = {name: self.map.read(np.asarray(channel, dtype=np.float32)) for name, channel in self.vertex.items()}
        self.size = size

    def _along(self, v, names, positions, base):
        """How far down a limb: 0 at its root, 1 at the second joint, 2 at the third, beyond that into the hand or foot."""
        out = np.zeros(len(v))
        for side, sign in (("l", -1.0), ("r", 1.0)):
            a, b, c = (self.joints[f"{n}_{side}"] for n in names)
            segs = ((a, b, 0.0), (b, c, 1.0))
            near = np.sign(v[:, 0]) == sign
            best = np.full(len(v), 1e9)
            value = np.zeros(len(v))
            for start, end, offset in segs:
                d = end - start
                t = ((v - start) @ d) / (d @ d)
                clamped = np.clip(t, 0.0, 1.0 if offset == 0.0 else 3.0)
                dist = np.linalg.norm(v - (start + clamped[:, None] * d), axis=1)
                hit = dist < best
                best[hit] = dist[hit]
                value[hit] = clamped[hit] + offset
            out[near] = value[near]
        return out


# -- costume painting -------------------------------------------------------------------------------------------
def font(size: int):
    for name in ("arialbd.ttf", "impact.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def emblem_image(kind: str, spec, resolution: int = 512) -> tuple[Image.Image, tuple, float]:
    """RGBA art, its centre (x, y) on the chest, and its width in game units. Sources: drawn shapes only."""
    n = resolution
    art = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)
    u = lambda c: tuple(int(v * 255) for v in c) + (255,)

    def letter(text, box_h, color, center=(.5, .5), skew=0.0):
        f = font(int(n * box_h))
        box = d.textbbox((0, 0), text, font=f)
        d.text((n * center[0] - (box[0] + box[2]) / 2, n * center[1] - (box[1] + box[3]) / 2), text, font=f, fill=color)

    if kind == "superman":  # silver: the shield's outline and the S stand out of a dark recess
        outer = [(.5, .94), (.04, .36), (.2, .1), (.8, .1), (.96, .36)]
        d.polygon([(x * n, y * n) for x, y in outer], fill=u(spec.trim))
        inner = [(.5, .85), (.11, .365), (.235, .165), (.765, .165), (.89, .365)]
        d.polygon([(x * n, y * n) for x, y in inner], fill=u(costumes.rgb(24, 42, 96)))
        letter("S", .56, u(spec.trim), (.5, .47))
        return art, (0.0, 2.085), .44
    if kind == "homelander":
        gold = u(spec.trim)
        d.polygon([(.5 * n, .86 * n), (.40 * n, .50 * n), (.0 * n, .16 * n), (.20 * n, .46 * n), (.05 * n, .42 * n), (.26 * n, .62 * n), (.42 * n, .66 * n)], fill=gold)
        d.polygon([(.5 * n, .86 * n), (.60 * n, .50 * n), (1.0 * n, .16 * n), (.80 * n, .46 * n), (.95 * n, .42 * n), (.74 * n, .62 * n), (.58 * n, .66 * n)], fill=gold)
        d.ellipse((.43 * n, .36 * n, .57 * n, .54 * n), fill=gold)
        return art, (0.0, 2.15), .66
    if kind == "sentry":  # a gold shield carrying a blue S, so that it is his and could not be taken for Superman's
        gold = u(spec.trim)
        d.ellipse((.05 * n, .05 * n, .95 * n, .95 * n), fill=gold)
        letter("S", .78, u(costumes.rgb(26, 58, 148)), (.5, .47))
        return art, (0.0, 2.09), .36
    if kind == "omni":
        d.ellipse((.06 * n, .06 * n, .94 * n, .94 * n), fill=(236, 236, 232, 255))
        d.ellipse((.28 * n, .28 * n, .72 * n, .72 * n), fill=u(spec.trim))
        return art, (0.0, 2.17), .24
    if kind == "soldier":  # a brass eagle: wings spread, head to one side
        brass = u(spec.trim)
        d.polygon([(.5 * n, .80 * n), (.42 * n, .50 * n), (.02 * n, .22 * n), (.14 * n, .44 * n), (.04 * n, .46 * n), (.22 * n, .60 * n), (.14 * n, .64 * n), (.42 * n, .68 * n)], fill=brass)
        d.polygon([(.5 * n, .80 * n), (.58 * n, .50 * n), (.98 * n, .22 * n), (.86 * n, .44 * n), (.96 * n, .46 * n), (.78 * n, .60 * n), (.86 * n, .64 * n), (.58 * n, .68 * n)], fill=brass)
        d.polygon([(.44 * n, .50 * n), (.5 * n, .30 * n), (.60 * n, .34 * n), (.56 * n, .50 * n)], fill=brass)
        return art, (0.0, 2.2), .42
    if kind == "viltrumite":
        grey = u(spec.trim)
        d.polygon([(.5 * n, .88 * n), (.08 * n, .22 * n), (.28 * n, .22 * n), (.5 * n, .6 * n), (.72 * n, .22 * n), (.92 * n, .22 * n)], fill=grey)
        return art, (0.0, 2.1), .3
    if kind == "invincible":
        letter("I", .9, (16, 16, 20, 255), (.5, .47))
        return art, (0.0, 2.08), .24
    return art, (0.0, 2.1), .1


def zone_pattern(cloth, T, weave, rng_scale=1.0):
    """Height and colour shift for a material, from canonical position so it runs continuously across UV seams."""
    x, y, z = T["x"], T["y"], T["z"]
    if cloth.pattern == "scales":
        s = .0105
        row = np.floor(y / (s * .87))
        u = (np.abs(x) * .85 + z * .5) / s + (row % 2) * .5
        fy = (y / (s * .87)) % 1.0
        fx = u % 1.0
        d = np.sqrt((fx - .5) ** 2 + (fy - .5) ** 2)
        height = 1.0 - smooth(.30, .56, d)
        return height * .0007, (.93 + .10 * height)
    if cloth.pattern == "ribbed":
        r = .5 + .5 * np.sin((y + np.abs(x) * .3) / .0075)
        return r * .0009, (.9 + .13 * r)
    if cloth.pattern == "leather":
        grain = weave["grain"]
        return grain * .0007, (.93 + .12 * grain)
    if cloth.pattern == "plate":
        return np.zeros_like(x), np.ones_like(x)
    return weave["weave"] * .00045, (.94 + .09 * weave["weave"])


def blurred(values: np.ndarray, radius: float) -> np.ndarray:
    image = Image.fromarray((np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(image, dtype=np.float32) / 255.0


def paint(spec, canon: Canon, noise: dict):
    T = canon.texel
    H = canon.size
    valid = canon.map.valid
    x, y, z, nz = T["x"], T["y"], T["z"], T["nz"]
    ax = np.abs(x)
    albedo = np.zeros((H, H, 3), dtype=np.float32)
    rough = np.ones((H, H), dtype=np.float32) * .6
    metal = np.zeros((H, H), dtype=np.float32)
    height = np.zeros((H, H), dtype=np.float32)
    skin_mask = np.zeros((H, H), dtype=np.float32)
    ao = np.ones((H, H), dtype=np.float32)
    raised = {}

    def apply(mask, cloth, soft=None):
        mask = mask.astype(np.float32) if soft is None else soft
        h, shade = zone_pattern(cloth, T, noise)
        color = np.array(cloth.color, dtype=np.float32) * shade[..., None]
        nonlocal_blend = mask[..., None]
        albedo[...] = albedo * (1.0 - nonlocal_blend) + color * nonlocal_blend
        rough[...] = rough * (1.0 - mask) + cloth.rough * mask
        metal[...] = metal * (1.0 - mask) + cloth.metal * mask
        height[...] = height * (1.0 - mask) + h * mask

    # Skin everywhere first, then zones over it.
    base_skin = np.array(spec.skin, dtype=np.float32)
    mottling = (noise["big"] - .5)[..., None]
    red_zones = (noise["mid"] - .5)[..., None]
    skin = base_skin * (1.0 + mottling * .22) + red_zones * np.array((.08, -.02, -.03), dtype=np.float32) + (noise["fine"] - .5)[..., None] * .04
    albedo[...] = skin
    rough[...] = .46 + (noise["mid"] - .5) * .18
    skin_mask[...] = 1.0
    height[...] = (noise["pores"] - .5) * .0009

    arm, leg = T["arm"] > .5, T["leg"] > .5
    head_area = (T["head"] + T["neck"]) > .5
    body_area = ~head_area
    s_arm, s_leg = T["s_arm"], T["s_leg"]

    def zone(mask, cloth):
        if cloth.pattern == "skin":
            return
        apply(mask, cloth)
        skin_mask[mask] = 0.0

    # The whole body below the neck is suit; the neckline is a smooth line round the throat.
    neck_y = 2.462 - np.clip(z * .12, -.02, .03)
    torso = (T["head"] < .5) & (~arm) & (~leg) & (y < neck_y)
    zone(torso, spec.torso)
    zone(arm & (s_arm < 1.0), spec.upper_arm)
    glove_from = 1.97 if spec.hand.pattern == "skin" else 1.74
    boot_from = 1.56
    zone(arm & (s_arm >= 1.0) & (s_arm < glove_from), spec.forearm)
    zone(arm & (s_arm >= glove_from), spec.hand)
    zone(leg & (s_leg < 1.0), spec.thigh)
    zone(leg & (s_leg >= 1.0) & (s_leg < boot_from), spec.shin)
    zone(leg & (s_leg >= boot_from), spec.foot)
    pelvis_y = canon.joints["pelvis"][1]
    if spec.trunks is not None:
        trunks = (~arm) & (y < pelvis_y + .03) & (leg & (s_leg < .2) | ~leg) & body_area
        zone(trunks, spec.trunks)
    if spec.belt is not None:
        belt = (~arm) & body_area & (np.abs(y - (pelvis_y + .075)) < .05)
        zone(belt, spec.belt)
        raised["belt"] = spec.belt
    if spec.cuff is not None:
        zone(arm & (np.abs(s_arm - glove_from) < .035), spec.cuff)
        zone(leg & (np.abs(s_leg - boot_from) < .03), spec.cuff)
    if spec.knee is not None:
        zone(leg & (np.abs(s_leg - 1.0) < .13) & (z > canon.joints["calf_l"][2] - .01), spec.knee)
    if spec.chest_plate is not None:
        plate = (~arm) & body_area & (y > pelvis_y + .24) & (y < 2.30) & (z > -.02)
        zone(plate, spec.chest_plate)
        # Plate seams and rivets.
        seams = ((np.abs(y - 1.86) < .004) | (np.abs(y - 1.99) < .004) | (ax < .004)) & plate
        height[seams] -= .004
        albedo[seams] *= .55
        back = (~arm) & body_area & (y > pelvis_y + .3) & (y < 2.3) & (z <= -.02)
        zone(back, spec.chest_plate)
    if spec.neck_wrap is not None:
        wrap = (y > 2.26) & (y < 2.48) & (T["head"] < .8) & body_area | ((T["neck"] > .3) & (y < 2.55) & (T["head"] < .7))
        zone(wrap, spec.neck_wrap)
        folds = np.sin((y + x * .3) / .012)
        height[wrap] += (folds[wrap] * .0035)
        albedo[wrap] *= (.9 + .1 * folds[wrap, None])
    if spec.collar is not None:
        band = (y > neck_y - .03) & (y < neck_y + .002) & (T["head"] < .5) & (~arm)
        zone(band, costumes.Cloth(spec.collar, .5, 0.0, "weave", .004))

    # Armour and other pieces: the material, a crisp edge, a bevel and a dark line where it meets the suit.
    for shell in gear.shells_for(spec, T, canon):
        if shell.node != "gear":
            continue
        area = shell.mask & valid
        color = np.array(shell.color, dtype=np.float32)
        wear = noise["mid"] * .22 + .89
        albedo[area] = color * wear[area, None]
        rough[area] = .66 - .39 * shell.metal
        metal[area] = shell.metal
        skin_mask[area] = 0.0
        soft = blurred(area.astype(np.float32), H / 512.0)
        height += soft * min(.012, shell.lift * .7)
        rim = np.clip(1.0 - np.abs(soft - .5) * 4.0, 0.0, 1.0)
        ao *= 1.0 - rim * .55

    # Anatomy reads through a tight suit: pectorals, abdominals and seam lines, as relief plus painted occlusion.
    suit = skin_mask < .5
    front = (nz > 0) & suit & (~arm) & (~leg)
    chest_y = 2.03
    pec = np.exp(-(((ax - .13) / .11) ** 2 + ((y - chest_y) / .085) ** 2))
    cleft = np.exp(-(x / .012) ** 2) * smooth(1.83, 1.95, y) * (1.0 - smooth(2.2, 2.26, y))
    pec_under = np.exp(-((y - (chest_y - .095 - .25 * (ax - .13) ** 2 * 4)) / .012) ** 2) * (ax < .25)
    ab_x = np.exp(-(x / .012) ** 2)
    abs_zone = smooth(pelvis_y + .08, pelvis_y + .17, y) * (1.0 - smooth(1.84, 1.91, y)) * smooth(.105, .07, ax)
    ab_rows = sum(np.exp(-((y - level) / .012) ** 2) for level in (1.70, 1.785, 1.86))
    relief = pec * .010 - cleft * .006 - pec_under * .005 - abs_zone * (ab_x * .004 + ab_rows * .0025)
    height[front] += relief[front]
    groove = np.clip(cleft * .18 + pec_under * .16 + abs_zone * (ab_x * .14 + ab_rows * .08), 0.0, .35)
    ao[front] *= 1.0 - groove[front]

    # Double-stitched seams down the flanks and the outer limbs.
    flank = suit & (~arm) & (~leg) & (np.abs(T["nz"]) < .14)
    stitch = (np.sin(y / .0035) > .2) & flank
    albedo[flank] *= .78
    albedo[stitch] *= 1.28
    height[flank] -= .0012
    limb_seam = suit & (arm | leg) & (np.abs(T["nz"]) < .05)
    albedo[limb_seam] *= .82
    height[limb_seam] -= .0008

    # Crease occlusion from the mesh: armpits, groin, hands.
    ao *= 1.0 - .28 * np.exp(-((T["s_arm"] - .02) / .04) ** 2) * arm
    # Head.
    head = (T["head"] > .5) & (skin_mask > .5)
    eye_y, mouth = canon.eye_y, canon.mouth
    eye_x = canon.eye_x
    face_front = nz > .1
    # Lips.
    lip_y = mouth[1]
    lips = np.exp(-((x / .031) ** 4 + ((y - lip_y) / .0145) ** 2)) * face_front * head
    lip_colour = np.array(spec.skin, dtype=np.float32) * np.array((.84, .54, .52), dtype=np.float32)
    albedo[...] = albedo * (1.0 - lips[..., None] * .86) + lip_colour * lips[..., None] * .86
    rough[...] = rough * (1.0 - lips * .4) + .32 * lips * .4
    mouth_line = np.exp(-((y - lip_y) / .0022) ** 2) * (ax < .028) * face_front * head
    albedo *= (1.0 - mouth_line[..., None] * .28)
    # Warmth on cheeks and nose, darker around the eyes.
    cheeks = np.exp(-(((ax - .07) / .04) ** 2 + ((y - (eye_y - .055)) / .03) ** 2)) * face_front * head
    albedo += cheeks[..., None] * np.array((.05, -.008, -.012), dtype=np.float32)
    sockets = np.exp(-(((ax - eye_x) / .034) ** 2 + ((y - eye_y) / .02) ** 2)) * face_front * head
    albedo *= (1.0 - sockets[..., None] * .22)
    ao *= 1.0 - sockets * .25
    # Eyebrows: strands of hair colour, thick and straight as men's are.
    brow_y = eye_y + .027 + .012 * np.clip((ax - .02) / .06, 0, 1) * (1.0 - np.clip((ax - .05) / .05, 0, 1))
    brows = np.exp(-(((ax - .055) / .036) ** 6 + ((y - brow_y) / .0085) ** 4)) * face_front * head
    hair_rgb = np.array(spec.hair, dtype=np.float32)
    brow_tone = hair_rgb * .75 if np.mean(hair_rgb) < .5 else hair_rgb * .62
    strand = .84 + .16 * np.sin((x * 1.7 + y * 4.0) / .0016)
    albedo[...] = albedo * (1.0 - brows[..., None] * strand[..., None] * .95) + brow_tone * brows[..., None] * strand[..., None] * .95
    # Hair colour under the cards, so no scalp shows through.
    scalp = scalp_mask(T, canon)
    scalp = np.clip(scalp * (1.5 - (noise["fine"] - .5) * 1.6), 0.0, 1.0) * head  # a hairline is not a ruled line; nothing grows where it is zero
    if spec.hair_style != "shaved":
        strands = .5 + .5 * np.sin((x + (noise["mid"] - .5) * .03) * 1900.0 + (z * 640.0))
        tone = hair_rgb * (.66 + .42 * noise["mid"] + .13 * strands)[..., None]
        albedo[...] = albedo * (1.0 - scalp[..., None]) + tone * scalp[..., None]
        rough[...] = rough * (1.0 - scalp) + .55 * scalp
    else:
        albedo[...] = albedo * (1.0 - scalp[..., None] * .22) + hair_rgb * scalp[..., None] * .22
    skin_mask[...] = skin_mask * (1.0 - scalp * .8)
    if spec.temple is not None:
        temple = np.exp(-(((ax - .1) / .035) ** 2 + ((y - (eye_y + .055)) / .05) ** 2)) * scalp
        albedo[...] = albedo * (1.0 - temple[..., None]) + np.array(spec.temple, dtype=np.float32) * temple[..., None]
    beard = beard_mask(T, canon, spec.beard) * head
    if spec.beard:
        fleck = (noise["pores"] > .78)[..., None]
        tone = np.array(spec.beard_color, dtype=np.float32) * (1.0 + (noise["mid"] - .5)[..., None] * .5)
        tone = np.where(fleck, np.array(spec.beard_streak, dtype=np.float32), tone)
        albedo[...] = albedo * (1.0 - beard[..., None]) + tone * beard[..., None]
        rough[...] = rough * (1.0 - beard) + .7 * beard
        skin_mask[...] = skin_mask * (1.0 - beard)
    elif spec.hair_style != "mark":
        shadow = np.exp(-(((T["y"] - (lip_y - .03)) / .035) ** 2)) * face_front * head * (1.0 - lips)
        albedo *= (1.0 - shadow[..., None] * .05)
    if spec.goggles is not None:
        goggle = np.exp(-(((ax - eye_x) / .05) ** 4 + ((y - eye_y) / .03) ** 4)) * face_front * head
        goggle = np.clip(goggle * 1.6, 0.0, 1.0)
        albedo[...] = albedo * (1.0 - goggle[..., None]) + np.array(spec.goggles, dtype=np.float32) * goggle[..., None]
        rough[...] = rough * (1.0 - goggle) + .18 * goggle
        skin_mask[...] = skin_mask * (1.0 - goggle)
        height[goggle > .5] += .003

    # Emblem, projected straight on to the chest.
    if spec.emblem:
        art, centre, width = emblem_image(spec.emblem, spec)
        pixels = np.asarray(art, dtype=np.float32) / 255.0
        n = pixels.shape[0]
        uu = (.5 - (x - centre[0]) / width)
        vv = (1.0 - ((y - centre[1]) / width + .5))
        inside = (uu >= 0) & (uu < 1) & (vv >= 0) & (vv < 1) & (nz > .1) & (~arm) & (T["head"] < .4)
        px = (uu[inside] * (n - 1)).astype(np.int32)
        py = (vv[inside] * (n - 1)).astype(np.int32)
        sample = pixels[py, px]
        alpha = sample[:, 3:4]
        albedo[inside] = albedo[inside] * (1.0 - alpha) + sample[:, :3] * alpha
        rough[inside] = rough[inside] * (1.0 - alpha[:, 0]) + .3 * alpha[:, 0]
        shine = .85 if spec.emblem in ("homelander", "soldier", "superman", "sentry") else .1
        recess = np.mean(sample[:, :3], axis=1, keepdims=True) < .25  # a dark inner field is suit, not metal
        metal[inside] = metal[inside] * (1.0 - alpha[:, 0]) + (np.where(recess, .1, shine) * alpha)[:, 0]
        relief = np.zeros((H, H), dtype=np.float32)
        relief[inside] = alpha[:, 0] * (1.0 - recess[:, 0] * .55)
        relief = blurred(relief, H / 700.0)
        height += relief * .009
        ao *= 1.0 - np.clip(1.0 - np.abs(relief - .5) * 4.0, 0.0, 1.0) * .35
    if spec.emblem == "homelander":
        # Gold eagle-feather yoke across both shoulders.
        yoke = (~arm | (s_arm < .24)) & body_area & (y > 2.20) & (y < 2.40) & (ax > .05)
        feather = np.sin((ax + y * .3) / .012)
        albedo[yoke] = np.array(spec.trim, dtype=np.float32) * (.82 + .16 * feather[yoke, None])
        rough[yoke] = .3
        metal[yoke] = .8
        height[yoke] += .006 + feather[yoke] * .0016
        skin_mask[yoke] = 0.0
    return dict(albedo=albedo, rough=rough, metal=metal, height=height, skin=skin_mask, ao=ao)


def scalp_mask(T, canon: Canon) -> np.ndarray:
    """Where hair grows: above a hairline that sweeps from the forehead, over the ear, round the nape."""
    y, z, ax = T["y"], T["z"], np.abs(T["x"])
    eye_y = canon.eye_y
    head_z = float(canon.vertex["z"][canon.vertex["head"] > .9].max())
    t = np.clip((head_z - z) / .30, 0.0, 1.0)          # 0 at the brow, 1 at the back of the skull
    line = eye_y + .083 - t * .23 - .28 * smooth(.0, .16, ax) * (1.0 - smooth(.25, .5, t)) * .1
    line = np.where(t > .6, eye_y - .19, line)
    edge = smooth(-.008, .012, y - line)
    behind_face = smooth(.2, .45, t)
    sides = smooth(eye_y - .02, eye_y + .04, y)
    ears = (ax > .118) & (y < eye_y + .045) & (y > eye_y - .12)
    return np.clip(edge * np.maximum(behind_face, sides), 0.0, 1.0) * (~ears)


def beard_mask(T, canon: Canon, style: str) -> np.ndarray:
    if not style:
        return np.zeros_like(T["x"])
    y, z, ax = T["y"], T["z"], np.abs(T["x"])
    mouth_y = canon.mouth[1]
    eye_y = canon.eye_y
    lips = np.exp(-((ax / .034) ** 4 + ((y - mouth_y) / .0125) ** 2))
    if style == "goatee":
        return np.clip(smooth(.05, .03, ax) * smooth(mouth_y - .012, mouth_y - .02, y) * smooth(mouth_y - .09, mouth_y - .075, y) * (T["nz"] > -.1), 0, 1)
    if style == "moustache":
        return np.clip(smooth(.062, .05, ax) * np.exp(-((y - (mouth_y + .021 - ax * .28)) / .014) ** 2) * (T["nz"] > .1), 0, 1)
    head_z = float(canon.vertex["z"][canon.vertex["head"] > .9].max())
    t = (head_z - z) / .30
    if style == "chops":
        return np.clip(smooth(.05, .075, ax) * smooth(.18, .1, t - .02) * smooth(eye_y - .02, eye_y - .05, y) * smooth(mouth_y - .1, mouth_y - .06, y), 0, 1)
    # Full: connected from sideburn, across the cheek and jaw, round the chin and over the top lip.
    # From the top lip, out along the cheek and up to the sideburns, in one connected line.
    cheek_top = mouth_y + .03 + (eye_y - .035 - mouth_y - .03) * smooth(.045, .135, ax)
    upper = smooth(cheek_top + .006, cheek_top - .012, y)
    front_of_ear = smooth(.42, .34, t)
    under = smooth(mouth_y - .135, mouth_y - .10, y)
    return np.clip(upper * front_of_ear * under * (1.0 - lips * 1.2), 0.0, 1.0)


# -- hair and beard cards ---------------------------------------------------------------------------------------
STYLES = {
    # cards, length, width, flow (back, down, out), lift, jitter
    "superman": (1000, .07, .0085, (1.0, .25, .05), .012, .35),
    "slick": (1200, .13, .0075, (1.0, .08, 0.0), .004, .10),
    "swept": (1500, .17, .009, (1.0, .3, .08), .010, .22),
    "omni": (1000, .06, .008, (.95, .35, .05), .010, .30),
    "rugged": (1000, .08, .0085, (.8, .5, .12), .012, .45),
    "crew": (900, .036, .0075, (.5, .4, .25), .008, .35),
    "long_back": (1300, .34, .010, (.9, 1.0, .03), .010, .2),
    "auburn": (1100, .09, .0085, (.3, .85, .1), .010, .3),
    "flat_top": (1100, .07, .0085, (.05, -1.0, .1), .010, .12),
    "mark": (1000, .075, .0085, (.75, -.1, .25), .014, .45),
    "shaved": (0, 0, 0, (0, 0, 0), 0, 0),
}


def strand_texture(path: Path) -> None:
    """One sheet of many tapered strands: colour multiplies by each card's tint, alpha cuts the strands out."""
    w, h = 256, 512
    rng = random.Random(7)
    alpha = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(alpha)
    shade = Image.new("L", (w, h), 170)
    draw_shade = ImageDraw.Draw(shade)
    for _ in range(90):
        x = rng.uniform(0, w)
        top = rng.uniform(0, h * .08)
        bottom = rng.uniform(h * .62, h)
        thick = rng.uniform(4.0, 11.0)
        drift = rng.uniform(-14, 14)
        value = rng.randint(120, 240)
        steps = 18
        for i in range(steps):
            t0, t1 = i / steps, (i + 1) / steps
            y0, y1 = top + (bottom - top) * t0, top + (bottom - top) * t1
            width = thick * (1.0 - t0 ** 2.2)
            x0 = x + drift * t0 * t0
            x1 = x + drift * t1 * t1
            draw.polygon([(x0 - width, y0), (x0 + width, y0), (x1 + width * .9, y1), (x1 - width * .9, y1)], fill=255)
            draw_shade.polygon([(x0 - width, y0), (x0 + width, y0), (x1 + width * .9, y1), (x1 - width * .9, y1)], fill=value)
    alpha = alpha.filter(ImageFilter.GaussianBlur(.7))
    shade = shade.filter(ImageFilter.GaussianBlur(.5))
    Image.merge("RGBA", (shade, shade, shade, alpha)).save(path)


def _strip(root, normal, direction, length, width, tint, segments, head_center, head_radii, lift, jitter, rng, out, free=False):
    """A ribbon growing from the scalp, kept outside the skull so it lies on the head instead of through it."""
    position = np.array(root, dtype=np.float64) + normal * .007  # outside the painted shell, or it would hide the strand
    heading = np.array(direction, dtype=np.float64)
    heading += normal * lift + rng.normal(0, jitter * .25, 3)
    heading /= max(np.linalg.norm(heading), 1e-6)
    side = np.cross(heading, normal)
    side /= max(np.linalg.norm(side), 1e-6)
    base = len(out["v"])
    step = length / segments
    # Each strand keeps to the level of the head its own root is at: skulls are not true ellipsoids.
    surface = float(np.linalg.norm((position - head_center) / head_radii)) * (1.0 + lift * .6)
    for i in range(segments + 1):
        t = i / segments
        w = width * (1.0 - t * .75)
        out["v"].append(position - side * w)
        out["v"].append(position + side * w)
        out["n"].append(normal)
        out["n"].append(normal)
        out["uv"].append((0.0, 1.0 - t))
        out["uv"].append((1.0, 1.0 - t))
        shade = .72 + .5 * t
        out["c"].append(tuple(c * shade for c in tint))
        out["c"].append(tuple(c * shade for c in tint))
        position = position + heading * step
        offset = (position - head_center) / head_radii
        distance = np.linalg.norm(offset)
        # A strand lies on the skull for as long as the skull is under it: pulled back whichever way it strays.
        if free:
            pass
        elif distance < surface or (distance < surface + .25 and t < .85):
            position = head_center + offset / distance * surface * head_radii
            outward = offset / distance
            heading = heading - outward * (heading @ outward)
        if free:
            heading = heading + np.array((.12, -.1, -.05))
        elif position[2] > head_center[2] + head_radii[2] * .1:  # still on the front of the head: it goes back, not down
            heading = heading + np.array((0.0, .55, -.45))
        else:
            heading = heading + np.array((0.0, -.25 * (t + .15), 0.0))
        heading /= max(np.linalg.norm(heading), 1e-6)
    for i in range(segments):
        a = base + i * 2
        out["t"].extend((a, a + 1, a + 3, a, a + 3, a + 2))


def grow_hair(spec, positions, normals, head_weight, canon_like, rng, density=1.0):
    cards, length, width, flow, lift, jitter = STYLES[spec.hair_style]
    out = {"v": [], "n": [], "uv": [], "c": [], "t": []}
    if not cards:
        return out
    # The skull: the upper part of the head, without the jaw, as an ellipsoid the strands can lie against.
    head = positions[head_weight > .8]
    top = head[:, 1].max()
    skull = head[head[:, 1] > top - .30]
    center = (skull.max(axis=0) + skull.min(axis=0)) * .5
    radii = (skull.max(axis=0) - skull.min(axis=0)) * .5
    radii = radii * np.array((1.02, 1.02, 1.0))
    scalp = canon_like["scalp"] > .5
    pool = np.nonzero(scalp)[0]
    if len(pool) == 0:
        return out
    hair = np.array(spec.hair)
    count = int(cards * density)
    eye_height = canon_like["eye_y"]
    for index in range(count):
        v = pool[int(rng.integers(len(pool)))]
        root = positions[v] + rng.normal(0, .004, 3)
        normal = normals[v]
        # Nothing grows beside the eyes or round the jaw: the hair starts above the ears and at the nape.
        if root[2] > center[2] - radii[2] * .1 and root[1] < eye_height + .075:
            continue
        if root[1] < eye_height - .16 and length < .3:
            continue
        back = np.array((0.0, 0.0, -1.0))
        down = np.array((0.0, -1.0, 0.0))
        outward = (root - center) / max(np.linalg.norm(root - center), 1e-6)
        heading = back * flow[0] + down * flow[1] + outward * flow[2]
        if root[2] > center[2]:  # from the hairline it rises over the crown; straight back would only slide down the brow
            heading = heading + np.array((0.0, 1.2, 0.0))
        heading = heading - normal * (heading @ normal) * .9
        if spec.hair_style == "superman" and root[2] > center[2] + radii[2] * .45 and abs(root[0]) < .04:
            heading = np.array((rng.normal(.0, .2), -.9, .35))
        tint = hair * float(rng.uniform(.74, 1.22))
        if spec.temple is not None and abs(root[0]) > radii[0] * .72 and root[1] < center[1] + radii[1] * .55:
            tint = np.array(spec.temple) * float(rng.uniform(.85, 1.15))
        _strip(root, normal, heading, length * float(rng.uniform(.65, 1.2)), width / max(density, .25) * float(rng.uniform(.8, 1.3)),
               tuple(tint), 3 if length < .1 else 5, center, radii, lift, jitter * .6, rng, out)
    if spec.hair_style == "superman":  # the loose curl on the forehead
        front = center[2] + radii[2]
        hairline = eye_height + .085
        for index in range(int(26 * density)):
            root = np.array((float(rng.normal(.008, .012)), hairline + float(rng.uniform(-.004, .016)), front + .012))
            _strip(root, np.array((0.0, .2, 1.0)), np.array((float(rng.normal(.2, .15)), -1.0, .55)), float(rng.uniform(.045, .075)), .0065 / max(density, .25),
                   tuple(hair * float(rng.uniform(.8, 1.15))), 3, center, radii, 0.0, .1, rng, out, free=True)
    return out


def grow_beard(spec, positions, normals, mask, rng, count=1300, density=1.0):
    out = {"v": [], "n": [], "uv": [], "c": [], "t": []}
    pool = np.nonzero(mask > .55)[0]
    if not spec.beard or len(pool) == 0:
        return out
    main, streak = np.array(spec.beard_color), np.array(spec.beard_streak)
    length = {"full": .036, "goatee": .03, "moustache": .026, "chops": .028}[spec.beard]
    center = positions[pool].mean(axis=0)
    for _ in range(int(count * density)):
        v = pool[int(rng.integers(len(pool)))]
        root = positions[v]
        normal = normals[v]
        heading = np.array((0.0, -1.0, .05)) + normal * .22 + rng.normal(0, .14, 3)
        tint = (streak if rng.random() < .22 else main) * float(rng.uniform(.85, 1.12))
        _strip(root, normal, heading, length * float(rng.uniform(.55, 1.15)), .0036 / max(density, .25) * float(rng.uniform(.8, 1.3)), tuple(tint), 2,
               center, np.array((.001, .001, .001)), .0, .25, rng, out)
    return out


# -- writing ----------------------------------------------------------------------------------------------------
def write_textures(spec, painted, folder: Path, sizes: tuple) -> None:
    valid = painted["valid"]
    albedo = dilate(np.clip(painted["albedo"] * painted["ao"][..., None] ** .6, 0, 1), valid)
    material = dilate(np.stack((np.clip(painted["rough"], .05, 1), np.clip(painted["metal"], 0, 1), np.clip(painted["skin"], 0, 1)), axis=2), valid)
    h = painted["height"] * 1.0
    # Normal from height. A texel is about 1/size of the sheet; the sheet spans about 3.2 units of body.
    texel = 3.2 / h.shape[0]
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) / (2.0 * texel)
    dy = (np.roll(h, 1, 0) - np.roll(h, -1, 0)) / (2.0 * texel)
    length = np.sqrt(dx * dx + dy * dy + 1.0)
    normal = np.stack((-dx / length, -dy / length, painted["ao"]), axis=2)
    normal[..., :2] = normal[..., :2] * .5 + .5
    normal = dilate(normal, valid)
    folder.mkdir(parents=True, exist_ok=True)
    full = h.shape[0]
    for size in sizes:
        suffix = "" if size == min(sizes) else "_hi"
        for name, data, quality in (("albedo", albedo, 93), ("material", material, 90), ("normal", normal, 95)):
            image = Image.fromarray((np.clip(data, 0, 1) * 255.0 + .5).astype(np.uint8), "RGB")
            if size != full:
                image = image.resize((size, size), Image.LANCZOS)
            image.save(folder / f"{name}{suffix}.jpg", quality=quality, subsampling=0 if name != "albedo" else 1, optimize=True)


def _star(draw, cx, cy, radius, fill):
    points = []
    for i in range(10):
        r = radius if i % 2 == 0 else radius * .4
        a = -pi / 2 + i * pi / 5
        points.append((cx + cos(a) * r, cy + sin(a) * r))
    draw.polygon(points, fill=fill)


CAPES = {"BLACK": "flag", "WHITE": ((150, 22, 30), (118, 16, 24), "", None), "YELLOW": ((236, 178, 44), (196, 140, 30), "", None),
         "GREEN": ((176, 26, 38), (136, 20, 30), "", None), "VILTRUMITE_1": ((234, 234, 232), (150, 154, 164), "", None),
         "VILTRUMITE_4": ((234, 234, 232), (150, 154, 164), "", None)}


def cape_sheet(spec, path: Path) -> None:
    """The cape's cloth, top of the picture at the shoulders and left of the picture on the wearer's left, seen from behind."""
    design = CAPES.get(spec.name)
    if design is None:
        return
    n = 1024
    art = Image.new("RGB", (n, n), (0, 0, 0))
    d = ImageDraw.Draw(art)
    if design == "flag":
        stripe = n / 13.0
        for row in range(13):
            colour = (178, 30, 40) if row % 2 == 0 else (236, 234, 226)
            d.rectangle((0, row * stripe, n, (row + 1) * stripe), fill=colour)
        field_w, field_h = int(n * .46), int(stripe * 7)
        d.rectangle((0, 0, field_w, field_h), fill=(26, 44, 104))
        for row in range(9):
            for col in range(6 if row % 2 == 0 else 5):
                x = (col + (.5 if row % 2 == 0 else 1.0)) * field_w / 6.0
                y = (row + 1) * field_h / 10.0
                _star(d, x, y, field_h / 26.0, (240, 238, 228))
    else:
        cloth, trim, letter, ink = design
        d.rectangle((0, 0, n, n), fill=cloth)
        if letter:
            shield = [(.5, .66), (.24, .34), (.32, .22), (.68, .22), (.76, .34)]
            d.polygon([(x * n, y * n) for x, y in shield], fill=ink)
            f = font(int(n * .3))
            box = d.textbbox((0, 0), letter, font=f)
            d.text((n * .5 - (box[0] + box[2]) / 2, n * .385 - (box[1] + box[3]) / 2), letter, font=f, fill=cloth)
        edge = int(n * .018)
        d.rectangle((0, 0, edge, n), fill=trim)
        d.rectangle((n - edge, 0, n, n), fill=trim)
        d.rectangle((0, n - edge, n, n), fill=trim)
    pixels = np.asarray(art, dtype=np.float32) / 255.0
    weave = 1.0 + .035 * np.sin(np.arange(n) * 2.1)[None, :, None] * np.sin(np.arange(n) * 1.9)[:, None, None]
    Image.fromarray((np.clip(pixels * weave, 0, 1) * 255).astype(np.uint8), "RGB").resize((512, 512), Image.LANCZOS).save(path, quality=90)


def eye_texture(path: Path, iris: tuple) -> None:
    n = 192
    image = np.zeros((n, n, 3), dtype=np.float32)
    ys, xs = np.mgrid[0:n, 0:n]
    r = np.sqrt((xs - n / 2 + .5) ** 2 + (ys - n / 2 + .5) ** 2) / (n / 2)
    angle = np.arctan2(ys - n / 2, xs - n / 2)
    fibres = .5 + .5 * np.sin(angle * 41.0) * np.sin(angle * 17.0 + r * 9.0)
    sclera = np.array((.86, .83, .80), dtype=np.float32) * (1.0 - .12 * smooth(.4, 1.0, r))[..., None]
    veins = (np.sin(angle * 67.0) > .985) * smooth(.45, .95, r)
    sclera = sclera * (1.0 - veins[..., None] * np.array((0.0, .35, .35), dtype=np.float32))
    colour = np.array(iris, dtype=np.float32)
    iris_map = colour * (.6 + .75 * fibres)[..., None] * (.75 + .5 * smooth(.42, .1, r))[..., None]
    mix = smooth(.40, .36, r)[..., None]
    image = sclera * (1.0 - mix) + iris_map * mix
    limbal = np.exp(-((r - .38) / .03) ** 2)[..., None]
    image = image * (1.0 - limbal * .75)
    pupil = smooth(.17, .14, r)[..., None]
    image = image * (1.0 - pupil) + .012 * pupil
    Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8), "RGB").save(path, quality=92)


def eyeball(center, radius, rings=10, sectors=14):
    verts, norms, uvs, tris = [], [], [], []
    for i in range(rings + 1):
        polar = pi * i / rings
        for j in range(sectors):
            a = 2.0 * pi * j / sectors
            d = np.array((sin(polar) * cos(a), sin(polar) * sin(a), cos(polar)))
            verts.append(np.array(center) + d * radius)
            norms.append(d)
            uvs.append((d[0] * .46 + .5, d[1] * .46 + .5))
    for i in range(rings):
        for j in range(sectors):
            n = (j + 1) % sectors
            a, b, c, d = i * sectors + j, i * sectors + n, (i + 1) * sectors + n, (i + 1) * sectors + j
            tris.extend((a, c, b, a, d, c))
    return np.array(verts), np.array(norms), np.array(uvs), np.array(tris)


def fist_curl(base, vertices, names, dense):
    """Fingers half-closed, as a fighter's are, baked into the mesh: the game's rig ends at the wrist."""
    joints = ms.joint_positions(base, vertices)
    parents = ms.rig_parents()
    out = vertices.copy()
    for side in "lr":
        hand = joints[f"hand_{side}"]
        across = joints[f"pinky_01_{side}"] - joints[f"index_01_{side}"]
        across /= np.linalg.norm(across)
        fingers = joints[f"middle_01_{side}"] - hand
        fingers /= np.linalg.norm(fingers)
        palm = np.cross(across, fingers)
        if side == "r":
            palm = -palm
        axis = across if side == "l" else -across
        for finger, angles in (("thumb", (10.0, 15.0, 15.0)), ("index", (38.0, 52.0, 38.0)), ("middle", (42.0, 56.0, 40.0)),
                               ("ring", (46.0, 58.0, 42.0)), ("pinky", (50.0, 60.0, 44.0))):
            for bone_index in range(3, 0, -1):
                name = f"{finger}_0{bone_index}_{side}"
                column = names.index(name)
                affected = {name}
                for later in range(bone_index + 1, 4):
                    affected.add(f"{finger}_0{later}_{side}")
                weight = sum(dense[:, names.index(a)] for a in affected)
                if not weight.any():
                    continue
                theta = np.radians(angles[bone_index - 1])
                head = joints[name]
                k = axis
                rel = out - head
                c, s = np.cos(theta), np.sin(theta)
                rotated = rel * c + np.cross(k, rel) * s + k[None, :] * (rel @ k)[:, None] * (1.0 - c)
                out += (rotated - rel) * weight[:, None]
    return out


def make_blend_table(joint_transforms, weights):
    from panda3d.core import TransformBlend, TransformBlendTable
    table = TransformBlendTable()
    index = {}
    columns = np.argsort(-weights, axis=1)[:, :4]
    picked = np.take_along_axis(weights, columns, axis=1)
    picked = picked / np.maximum(picked.sum(axis=1, keepdims=True), 1e-6)
    picked = np.round(picked, 2)
    ids = np.zeros(len(weights), dtype=np.uint16)
    for row in range(len(weights)):
        key = tuple((int(c), float(w)) for c, w in zip(columns[row], picked[row]) if w > 0.0)
        found = index.get(key)
        if found is None:
            blend = TransformBlend()
            for c, w in key:
                blend.addTransform(joint_transforms[c], w)
            blend.normalizeWeights()
            found = index[key] = table.addBlend(blend)
        ids[row] = found
    return table, ids


def make_geom(name, positions, normals, uvs, colors, triangles, joint_transforms, weights):
    from panda3d.core import (Geom, GeomEnums, GeomNode, GeomTriangles, GeomVertexAnimationSpec, GeomVertexArrayFormat, GeomVertexData,
                              GeomVertexFormat, InternalName, SparseArray)
    array = GeomVertexArrayFormat()
    array.addColumn(InternalName.getVertex(), 3, GeomEnums.NT_stdfloat, GeomEnums.C_point)
    array.addColumn(InternalName.getNormal(), 3, GeomEnums.NT_stdfloat, GeomEnums.C_normal)
    array.addColumn(InternalName.getTexcoord(), 2, GeomEnums.NT_stdfloat, GeomEnums.C_texcoord)
    array.addColumn(InternalName.getColor(), 4, GeomEnums.NT_uint8, GeomEnums.C_color)
    blends = GeomVertexArrayFormat()
    blends.addColumn(InternalName.getTransformBlend(), 1, GeomEnums.NT_uint16, GeomEnums.C_index)
    fmt = GeomVertexFormat()
    fmt.addArray(array)
    fmt.addArray(blends)
    spec = GeomVertexAnimationSpec()
    spec.setPanda()
    fmt.setAnimation(spec)
    registered = GeomVertexFormat.registerFormat(fmt)
    data = GeomVertexData(name, registered, Geom.UHStatic)
    data.setNumRows(len(positions))
    packed = np.zeros(len(positions), dtype=[("p", "<f4", 3), ("n", "<f4", 3), ("t", "<f4", 2), ("c", "u1", 4)])
    packed["p"], packed["n"], packed["t"] = positions, normals, uvs
    packed["c"] = np.clip(colors * 255.0, 0, 255).astype(np.uint8)
    handle = data.modifyArrayHandle(0)
    handle.copyDataFrom(packed.tobytes())
    table, ids = make_blend_table(joint_transforms, weights)
    table.setRows(SparseArray.lowerOn(len(positions)))  # without this, Panda skins no vertices at all
    data.setTransformBlendTable(table)
    data.modifyArrayHandle(1).copyDataFrom(ids.astype(np.uint32).tobytes())  # this array has a stride of four
    prim = GeomTriangles(Geom.UHStatic)
    prim.setIndexType(GeomEnums.NT_uint32 if len(positions) > 65000 else GeomEnums.NT_uint16)
    index = np.asarray(triangles, dtype=np.uint32 if len(positions) > 65000 else np.uint16).ravel()
    prim.modifyVertices(len(index)).modifyHandle().copyDataFrom(index.tobytes())
    geom = Geom(data)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


def soften(values, triangles, position_index, passes):
    """A per-vertex value blurred over the mesh's own edges, seams together."""
    count = position_index.max() + 1
    field = np.zeros(count)
    np.maximum.at(field, position_index, values)
    ids = position_index[triangles]
    a = np.concatenate((ids[:, 0], ids[:, 1], ids[:, 2]))
    b = np.concatenate((ids[:, 1], ids[:, 2], ids[:, 0]))
    for _ in range(passes):
        total, seen = np.zeros(count), np.zeros(count)
        np.add.at(total, a, field[b])
        np.add.at(seen, a, 1.0)
        field = field * .5 + total / np.maximum(seen, 1.0) * .5
    return field[position_index]


def smooth_region(positions, triangles, position_index, mask, passes, flatten=(True, True, True)):
    """Laplacian smoothing of one part of the mesh, seams together: it melts toes into the shape of a boot.

    Only the chosen axes move: across the foot is enough to close the gaps between toes without shrinking the boot."""
    count = position_index.max() + 1
    place = np.zeros((count, 3))
    place[position_index] = positions
    moving = np.zeros(count, dtype=bool)
    moving[position_index[mask]] = True
    ids = position_index[triangles]
    a = np.concatenate((ids[:, 0], ids[:, 1], ids[:, 2]))
    b = np.concatenate((ids[:, 1], ids[:, 2], ids[:, 0]))
    for _ in range(passes):
        total = np.zeros((count, 3))
        seen = np.zeros(count)
        np.add.at(total, a, place[b])
        np.add.at(seen, a, 1.0)
        average = total / np.maximum(seen, 1.0)[:, None]
        for axis, chosen in enumerate(flatten):
            if chosen:
                place[moving, axis] = place[moving, axis] * .4 + average[moving, axis] * .6
    return place[position_index]


def add_gear(group, spec, shells, positions, normals, triangles, position_index, joints, transforms, level) -> None:
    """All of one character's armour as a single draw call per kind, cut from this level of detail's mesh."""
    from_weights = {}
    for node in ("gear", "helmet"):
        parts = []
        offset = 0
        for shell in shells:
            if shell.node != node:
                continue
            built = gear.extrude(positions, normals, triangles, position_index, shell)
            if built is None:
                continue
            vertices, vertex_normals, colors, faces, used = built
            parts.append((vertices, vertex_normals, colors, faces + offset, np.concatenate((WEIGHTS_NOW[used], WEIGHTS_NOW[used]))))
            offset += len(vertices)
        if node == "gear":
            around = positions[(np.abs(C_NOW["y"] - NECK_RING_Y) < .03) & (C_NOW["head"] < .6) & (C_NOW["arm"] < .5)]
            neck = ((0.0, float(np.percentile(around[:, 1], 50)), float((around[:, 2].max() + around[:, 2].min()) * .5)),
                    float(np.abs(around[:, 0]).max()), float((around[:, 2].max() - around[:, 2].min()) * .5))
            for bone, (vertices, vertex_normals, colors, faces) in gear.ornaments_for(spec, joints, neck):
                parts.append((vertices, vertex_normals, colors, faces + offset, cone_weights(len(vertices), bone)))
                offset += len(vertices)
        if not parts:
            continue
        vertices = np.concatenate([part[0] for part in parts])
        uvs = np.zeros((len(vertices), 2), dtype=np.float32)
        built_node = make_geom(f"{spec.name}-{node}-{level}", vertices, np.concatenate([part[1] for part in parts]), uvs, np.concatenate([part[2] for part in parts]),
                               np.concatenate([part[3] for part in parts])[:, [0, 2, 1]], transforms, np.concatenate([part[4] for part in parts]))
        group.attachNewNode(built_node).setName(node)


WEIGHTS_NOW = None
C_NOW = None
NECK_RING_Y = 2.43


def cone_weights(count, joint):
    out = np.zeros((count, len(ms.GAME_JOINTS)), dtype=np.float32)
    out[:, ms.GAME_JOINTS.index(joint)] = 1.0
    return out


def build_one(spec, base, topo, weights, canon, lods, names, dense, noise, sizes, shared_paths):
    from panda3d.core import Character, CharacterJoint, Filename, JointVertexTransform, LMatrix4f, LODNode, NodePath, PartGroup

    rng = np.random.default_rng(spec.seed)
    details = {key: value for key, value in spec.details.items() if value}
    vertices = ms.build_body(base, **spec.body, details=details)
    joints_obj = ms.joint_positions(base, vertices)
    curled = fist_curl(base, vertices, names, dense)
    frame = Frame(vertices, base.groups["body"])
    positions_all = frame(curled)
    joints = {name: frame(p) for name, p in joints_obj.items()}
    eye_l = frame(vertices[base.groups["joint-l-eye"]].mean(axis=0))
    eye_r = frame(vertices[base.groups["joint-r-eye"]].mean(axis=0))
    pid = topo.position_index
    positions = positions_all[pid].astype(np.float64)
    tri_game = topo.triangles[:, [0, 2, 1]]
    w = weights[pid]
    global WEIGHTS_NOW, C_NOW
    WEIGHTS_NOW = w
    C_NOW = canon.vertex
    normals = vertex_normals(positions, tri_game, pid)
    C = canon.vertex

    # Painted zones first, so each can raise its own stretch of the mesh.
    painted = paint(spec, canon, noise)
    painted["valid"] = canon.map.valid
    write_textures(spec, painted, OUT / spec.name, sizes)

    # Stand costume parts off the body, so boots, belts and armour change the silhouette instead of just the colour.
    arm, leg = C["arm"] > .5, C["leg"] > .5
    raise_by = np.zeros(len(positions))
    y, z, ax = C["y"], C["z"], np.abs(C["x"])
    s_arm, s_leg = C["s_arm"], C["s_leg"]

    def stand(mask, cloth):
        if cloth is not None and cloth.raised:
            raise_by[mask] = np.maximum(raise_by[mask], cloth.raised)

    pelvis_y = canon.joints["pelvis"][1]
    stand(arm & (s_arm >= (1.97 if spec.hand.pattern == "skin" else 1.74)), spec.hand)
    if spec.foot.raised:
        raise_by[leg & (s_leg >= 1.56)] = spec.foot.raised + .016
    if spec.belt is not None:
        stand((~arm) & (np.abs(y - (pelvis_y + .075)) < .05) & (C["head"] < .3), spec.belt)
    if spec.knee is not None:
        stand(leg & (np.abs(s_leg - 1.0) < .13) & (z > canon.joints["calf_l"][2] - .01), spec.knee)
    if spec.chest_plate is not None:
        stand((~arm) & (y > pelvis_y + .24) & (y < 2.30) & (C["head"] + C["neck"] < .5), spec.chest_plate)
    if spec.neck_wrap is not None:
        stand((y > 2.26) & (y < 2.5) & (C["head"] < .7) & (~arm), spec.neck_wrap)

    # Under each costume piece the body swells, feathered off at the edge, so that it changes the outline.
    swell = np.zeros(len(positions))
    for shell in gear.shells_for(spec, C, canon):
        if shell.node != "gear":
            continue
        field = soften(shell.mask.astype(np.float64), tri_game, pid, 2)
        swell = np.maximum(swell, field * shell.lift)
    raise_by = raise_by + swell

    # Beards and hair need a little volume of their own under the cards.
    v_scalp = scalp_mask(C, canon) * (C["head"] > .5)
    v_beard = beard_mask(C, canon, spec.beard) * (C["head"] > .5)
    if spec.foot.pattern != "skin":
        toes = leg & (y < canon.joints["foot_l"][1] + .03) & (z > canon.joints["foot_l"][2] + .11)
        positions = smooth_region(positions, tri_game, pid, toes, 30)
        normals = vertex_normals(positions, tri_game, pid)
    positions = positions + normals * (raise_by + (v_scalp * (0.0 if spec.hair_style == "shaved" else .005)) + v_beard * .012)[:, None]
    normals = vertex_normals(positions, tri_game, pid)

    # Skeleton: all translations, so a joint's rotation is simply the game's rotation in model axes.
    character = Character(spec.name.lower())
    bundle = character.getBundle(0)
    skeleton = PartGroup(bundle, "<skeleton>")
    parents = {"pelvis": None, "spine_01": "pelvis", "spine_02": "spine_01", "spine_03": "spine_02", "neck_01": "spine_03", "head": "neck_01",
               "upperarm_l": "spine_03", "lowerarm_l": "upperarm_l", "hand_l": "lowerarm_l", "upperarm_r": "spine_03", "lowerarm_r": "upperarm_r", "hand_r": "lowerarm_r",
               "thigh_l": "pelvis", "calf_l": "thigh_l", "foot_l": "calf_l", "thigh_r": "pelvis", "calf_r": "thigh_r", "foot_r": "calf_r"}
    made, transforms = {}, []
    layout = {}
    for name in ms.GAME_JOINTS:
        parent = parents[name]
        at = joints[name]
        local = at - (joints[parent] if parent else np.zeros(3))
        joint = CharacterJoint(character, bundle, made[parent] if parent else skeleton, name, LMatrix4f.translateMat(*local))
        made[name] = joint
        transforms.append(JointVertexTransform(joint))
        layout[name] = {"parent": parent, "offset": [float(v) for v in local], "at": [float(v) for v in at]}

    white = np.ones((len(positions), 4), dtype=np.float32)
    root = NodePath(character)
    shells = [shell for shell in gear.shells_for(spec, C, canon) if shell.node == "helmet"]
    lod = LODNode("lod")
    lod_path = root.attachNewNode(lod)
    switches = ((0.0, 16.0), (16.0, 46.0), (46.0, 1e6))
    # Hair and beard, tinted per card, heavier and fewer with distance.
    hair_vertex = {"scalp": v_scalp * (positions[:, 1] > canon.eye_y - .28), "eye_y": float(eye_l[1])}
    built = {}
    for level, (near, far) in enumerate(switches):
        group = NodePath(f"level-{level}")
        tris = tri_game if level == 0 else lods[level - 1]
        used, compact = np.unique(tris, return_inverse=True)  # a lower detail stores, and so skins, only what it draws
        body_node = make_geom(f"{spec.name}-body-{level}", positions[used], normals[used], topo.uv[used], white[used],
                              compact.reshape(-1, 3)[:, [0, 2, 1]], transforms, w[used])  # drawn the other way round: the game is left-handed
        group.attachNewNode(body_node).setName("body")
        if level < 2:
            density = 1.0 if level == 0 else .5
            hair_rng = np.random.default_rng(spec.seed + 100 + level)
            cards = grow_hair(spec, positions, normals, C["head"], hair_vertex, hair_rng, density)
            beard = grow_beard(spec, positions, normals, v_beard, hair_rng, density=density)
            offset = len(cards["v"])
            cards["t"].extend(index + offset for index in beard["t"])
            for key in ("v", "n", "uv", "c"):
                cards[key].extend(beard[key])
            if cards["v"]:
                count = len(cards["v"])
                colors = np.concatenate((np.array(cards["c"], dtype=np.float32), np.ones((count, 1), dtype=np.float32)), axis=1)
                node = make_geom(f"{spec.name}-hair-{level}", np.array(cards["v"]), np.array(cards["n"]), np.array(cards["uv"]), colors,
                                 np.array(cards["t"]), transforms, cone_weights(count, "head"))
                group.attachNewNode(node).setName("hair")
            eye_verts, eye_norms, eye_uvs, eye_tris = [], [], [], []
            radius = float(np.ptp(frame(vertices[base.groups["helper-l-eye"]]), axis=0).max()) * .5
            for center in (eye_l, eye_r):
                ev, en, eu, et = eyeball(center, radius)
                eye_tris.append(et + sum(len(e) for e in eye_verts))
                eye_verts.append(ev)
                eye_norms.append(en)
                eye_uvs.append(eu)
            ev = np.concatenate(eye_verts)
            node = make_geom(f"{spec.name}-eyes-{level}", ev, np.concatenate(eye_norms), np.concatenate(eye_uvs), np.ones((len(ev), 4), dtype=np.float32),
                             np.concatenate(eye_tris)[:, ...].reshape(-1, 3)[:, [0, 2, 1]], transforms, cone_weights(len(ev), "head"))
            group.attachNewNode(node).setName("eyes")
        if level < 2:
            add_gear(group, spec, shells, positions, normals, tri_game if level == 0 else lods[0], pid, joints, transforms, level)
        group.reparentTo(lod_path)
        lod.addSwitch(far, near)
    dump = os.environ.get("SENTRY_MESH_DUMP")
    if dump:
        Path(dump).mkdir(parents=True, exist_ok=True)
        np.savez_compressed(Path(dump) / f"{spec.name}.npz", positions=positions, normals=normals, uv=topo.uv, triangles=tri_game, weights=w,
                            lod1=lods[0], lod2=lods[1], joint_names=np.array(ms.GAME_JOINTS),
                            joint_at=np.array([joints[n] for n in ms.GAME_JOINTS]))
    (OUT / spec.name).mkdir(parents=True, exist_ok=True)
    cape_sheet(spec, OUT / spec.name / "cape.jpg")
    eye_texture(OUT / spec.name / "eye.jpg", spec.eyes)
    root.writeBamFile(Filename.fromOsSpecific(str(OUT / spec.name / "model.bam")))
    (OUT / spec.name / "rig.json").write_text(json.dumps({
        "joints": layout, "eyes": [[float(v) for v in eye_l], [float(v) for v in eye_r]],
        "chest": [0.0, 2.1, float(positions[(np.abs(C["x"]) < .02) & (np.abs(C["y"] - 2.1) < .03), 2].max())],
        "neck_back": [0.0, float(joints["neck_01"][1]), float(joints["neck_01"][2])],
        "triangles": [int(len(tri_game)), int(len(lods[0])), int(len(lods[1]))]}, indent=0), encoding="utf-8")
    print(f"{spec.name}: built ({len(tri_game)} / {len(lods[0])} / {len(lods[1])} body triangles)", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*")
    parser.add_argument("--size", type=int, default=2048)
    args = parser.parse_args()
    from panda3d.core import loadPrcFileData
    loadPrcFileData("", "coordinate-system y-up-left")
    OUT.mkdir(parents=True, exist_ok=True)
    base = ms.load_base()
    topo = Topology(base)
    names, dense = ms.raw_weights(len(base.vertices))
    weights = ms.merge_to_game_joints(names, dense)
    canon = Canon(base, topo, weights, args.size)
    # Seams stay put, and so do the head and hands' fine shapes for as long as possible.
    lod_cache = OUT / "lods.npz"
    if lod_cache.exists():
        stored = np.load(lod_cache)
        lods = (stored["lod1"], stored["lod2"])
    else:
        locked_pos = np.zeros(len(base.vertices), dtype=bool)
        count = np.bincount(topo.position_index, minlength=len(base.vertices))
        split = count[topo.position_index] > 1
        tri = topo.triangles[:, [0, 2, 1]]
        lod1 = simplify(canon.positions[topo.position_index], tri, split, 6500)
        lod2 = simplify(canon.positions[topo.position_index], tri, split, 1800)
        lods = (lod1, lod2)
        np.savez_compressed(lod_cache, lod1=lod1, lod2=lod2)
    print("lod triangles", len(lods[0]), len(lods[1]), flush=True)
    noise = {"big": fractal_noise(args.size, 1, 3, 3), "mid": fractal_noise(args.size, 2, 24, 3), "fine": fractal_noise(args.size, 3, 256, 2),
             "pores": fractal_noise(args.size, 4, 800, 2, .6), "grain": fractal_noise(args.size, 5, 500, 2, .7) ,
             "weave": (np.sin(np.arange(args.size) * 2.0 * pi / 3.0)[None, :] * np.sin(np.arange(args.size) * 2.0 * pi / 3.0)[:, None]).astype(np.float32)}
    strand_texture(OUT / "strands.png")
    wanted = set(args.names)
    for spec in costumes.ALL:
        if wanted and spec.name not in wanted:
            continue
        sizes = (1024, args.size) if spec.name in costumes.ROSTER_NAMES and args.size > 1024 else (1024,)
        build_one(spec, base, topo, weights, canon, lods, names, dense, noise, sizes, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
