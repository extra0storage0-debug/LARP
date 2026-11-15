"""Read the CC0 MakeHuman base mesh, its morph targets and its game rig. Data only: no addon code runs.

The source folder is MPFB2's data directory, unpacked by hand, passed in by SENTRY_MPFB_DATA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip
import json
import os
from pathlib import Path

import numpy as np

DATA = Path(os.environ.get("SENTRY_MPFB_DATA", r"C:\Users\raoha\SENTRY_tools\mpfb_data\data"))

# Joints the game drives. Everything else is merged into its nearest kept ancestor.
GAME_JOINTS = ("pelvis", "spine_01", "spine_02", "spine_03", "neck_01", "head",
               "upperarm_l", "lowerarm_l", "hand_l", "upperarm_r", "lowerarm_r", "hand_r",
               "thigh_l", "calf_l", "foot_l", "thigh_r", "calf_r", "foot_r")
_MERGE = {"Root": "pelvis", "clavicle_l": "spine_03", "clavicle_r": "spine_03", "ball_l": "foot_l", "ball_r": "foot_r"}


@dataclass
class BaseMesh:
    vertices: np.ndarray                 # object space, every vertex including helpers and joint cubes
    uvs: np.ndarray
    quads: np.ndarray                    # (n, 4) position indexes of the "body" group
    quad_uvs: np.ndarray                 # (n, 4) uv indexes of the same faces
    groups: dict = field(default_factory=dict)  # group name -> sorted unique position indexes
    group_quads: dict = field(default_factory=dict)  # group name -> [(positions, uvs)]


def load_base() -> BaseMesh:
    positions, uvs, group = [], [], None
    groups, faces = {}, {}
    with open(DATA / "3dobjs" / "base.obj", encoding="utf-8") as source:
        for line in source:
            head = line[:2]
            if head == "v ":
                positions.append([float(x) for x in line.split()[1:4]])
            elif head == "vt":
                uvs.append([float(x) for x in line.split()[1:3]])
            elif head == "g ":
                group = line.split()[1]
            elif head == "f ":
                corners = [corner.split("/") for corner in line.split()[1:]]
                faces.setdefault(group, []).append(([int(c[0]) - 1 for c in corners],
                                                    [int(c[1]) - 1 for c in corners]))
    for name, entries in faces.items():
        groups[name] = np.unique(np.array([e[0] for e in entries], dtype=np.int32))
    body = faces["body"]
    return BaseMesh(np.array(positions, dtype=np.float64), np.array(uvs, dtype=np.float64),
                    np.array([f[0] for f in body], dtype=np.int32), np.array([f[1] for f in body], dtype=np.int32),
                    groups, faces)


_target_cache: dict = {}


def read_target(relative: str) -> tuple[np.ndarray, np.ndarray]:
    if relative not in _target_cache:
        indexes, offsets = [], []
        with gzip.open(DATA / "targets" / f"{relative}.target.gz", "rt", encoding="utf-8") as source:
            for line in source:
                parts = line.split()
                if len(parts) == 4 and not line.startswith("#"):
                    indexes.append(int(parts[0]))
                    offsets.append([float(v) for v in parts[1:]])
        _target_cache[relative] = (np.array(indexes, dtype=np.int32), np.array(offsets, dtype=np.float64))
    return _target_cache[relative]


def add_target(vertices: np.ndarray, relative: str, weight: float) -> None:
    if abs(weight) < 1e-5:
        return
    indexes, offsets = read_target(relative)
    if len(indexes) == 0:  # a few combinations are stored empty: they add nothing
        return
    vertices[indexes] += offsets * weight


def _blend(value: float) -> list[tuple[str, float]]:
    """A 0-1 slider over min, average and max target names."""
    if value >= .5:
        return [("max", (value - .5) * 2.0), ("average", 1.0 - (value - .5) * 2.0)]
    return [("min", (.5 - value) * 2.0), ("average", 1.0 - (.5 - value) * 2.0)]


def build_body(base: BaseMesh, *, muscle: float = 1.0, weight: float = .5, height: float = .5, proportions: float = .9,
               age: str = "young", details: dict | None = None) -> np.ndarray:
    """An adult male from MakeHuman's macro sliders, then any named detail targets on top."""
    vertices = base.vertices.copy()
    add_target(vertices, f"macrodetails/caucasian-male-{age}", 1.0)
    for muscle_name, muscle_share in _blend(muscle):
        for weight_name, weight_share in _blend(weight):
            share = muscle_share * weight_share
            stem = f"male-{age}-{muscle_name}muscle-{weight_name}weight"
            add_target(vertices, f"macrodetails/universal-{stem}", share)
            add_target(vertices, f"macrodetails/proportions/{stem}-idealproportions", share * proportions)
            if height >= .5:
                add_target(vertices, f"macrodetails/height/{stem}-maxheight", share * (height - .5) * 2.0)
            else:
                add_target(vertices, f"macrodetails/height/{stem}-minheight", share * (.5 - height) * 2.0)
    for relative, amount in (details or {}).items():
        add_target(vertices, relative, amount)
    return vertices


def joint_positions(base: BaseMesh, vertices: np.ndarray) -> dict[str, np.ndarray]:
    """Every rig joint's head, from the helper cubes that travel with the morphs."""
    rig = json.loads((DATA / "rigs" / "standard" / "rig.game_engine.json").read_text(encoding="utf-8"))
    heads = {}
    for name, bone in rig.items():
        head = bone["head"]
        if head.get("strategy") == "CUBE":
            heads[name] = vertices[base.groups[head["cube_name"]]].mean(axis=0)
        else:
            heads[name] = vertices[np.array(head["vertex_indices"])].mean(axis=0)
    return heads


def rig_parents() -> dict[str, str]:
    rig = json.loads((DATA / "rigs" / "standard" / "rig.game_engine.json").read_text(encoding="utf-8"))
    return {name: bone["parent"] for name, bone in rig.items()}


def raw_weights(vertex_count: int) -> tuple[list[str], np.ndarray]:
    """Bone names and a dense (vertices, bones) weight table from the rig's weight file."""
    table = json.loads((DATA / "rigs" / "standard" / "weights.game_engine.json").read_text(encoding="utf-8"))["weights"]
    names = sorted(table)
    dense = np.zeros((vertex_count, len(names)), dtype=np.float32)
    for column, name in enumerate(names):
        pairs = np.array(table[name], dtype=np.float64)
        if len(pairs):
            dense[pairs[:, 0].astype(np.int32), column] = pairs[:, 1]
    return names, dense


def merge_to_game_joints(names: list[str], dense: np.ndarray) -> np.ndarray:
    """Fingers go to the hand; clavicles to the chest; toes to the foot. Rows sum to 1 where weighted."""
    merged = np.zeros((dense.shape[0], len(GAME_JOINTS)), dtype=np.float32)
    parents = rig_parents()
    for column, name in enumerate(names):
        current = name
        while current not in GAME_JOINTS:
            current = _MERGE.get(current) or parents.get(current) or "pelvis"
        merged[:, GAME_JOINTS.index(current)] += dense[:, column]
    return merged
