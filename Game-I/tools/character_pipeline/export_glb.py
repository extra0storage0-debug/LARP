"""Write a baked character's top LOD as a standard skinned .glb, for the Godot prototype.

    python export_glb.py <dump folder with NAME.npz> <assets/characters> <output folder> NAME...
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys

import numpy as np

PARENTS = {"pelvis": None, "spine_01": "pelvis", "spine_02": "spine_01", "spine_03": "spine_02", "neck_01": "spine_03", "head": "neck_01",
           "upperarm_l": "spine_03", "lowerarm_l": "upperarm_l", "hand_l": "lowerarm_l", "upperarm_r": "spine_03", "lowerarm_r": "upperarm_r",
           "hand_r": "lowerarm_r", "thigh_l": "pelvis", "calf_l": "thigh_l", "foot_l": "calf_l", "thigh_r": "pelvis", "calf_r": "thigh_r", "foot_r": "calf_r"}


def export(dump: Path, textures: Path, out: Path, name: str, lod: str | None = None) -> None:
    data = np.load(dump / f"{name}.npz")
    # Back to a right-handed space: the character's left is +x again, and winding goes with it.
    flip = np.array((-1.0, 1.0, 1.0))
    positions = (data["positions"] * flip).astype(np.float32)
    normals = (data["normals"] * flip).astype(np.float32)
    uv = data["uv"].astype(np.float32).copy()
    uv[:, 1] = 1.0 - uv[:, 1]
    triangles = (data[lod] if lod else data["triangles"])[:, [0, 2, 1]].astype(np.uint32)
    weights = data["weights"]
    order = np.argsort(-weights, axis=1)[:, :4]
    picked = np.take_along_axis(weights, order, axis=1).astype(np.float32)
    picked /= np.maximum(picked.sum(axis=1, keepdims=True), 1e-6)
    joints = order.astype(np.uint16)
    names = [str(n) for n in data["joint_names"]]
    at = (data["joint_at"] * flip).astype(np.float32)

    blob = bytearray()
    views, accessors = [], []

    def add(array: np.ndarray, kind: str, component: int, target=None, bounds: bool = False) -> int:
        offset = len(blob)
        raw = array.tobytes()
        blob.extend(raw)
        blob.extend(b"\0" * ((4 - len(raw) % 4) % 4))
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        accessor = {"bufferView": len(views) - 1, "componentType": component, "count": len(array), "type": kind}
        if bounds:
            accessor["min"] = [float(v) for v in array.min(axis=0)]
            accessor["max"] = [float(v) for v in array.max(axis=0)]
        accessors.append(accessor)
        return len(accessors) - 1

    primitive = {"attributes": {"POSITION": add(positions, "VEC3", 5126, 34962, True), "NORMAL": add(normals, "VEC3", 5126, 34962),
                                "TEXCOORD_0": add(uv, "VEC2", 5126, 34962), "JOINTS_0": add(joints, "VEC4", 5123, 34962),
                                "WEIGHTS_0": add(picked, "VEC4", 5126, 34962)},
                 "indices": add(triangles.ravel(), "SCALAR", 5125, 34963), "material": 0}
    inverse = np.tile(np.eye(4, dtype=np.float32), (len(names), 1, 1))
    inverse[:, 3, :3] = -at
    nodes = []
    for index, joint in enumerate(names):
        parent = PARENTS[joint]
        local = at[index] - (at[names.index(parent)] if parent else 0.0)
        node = {"name": joint, "translation": [float(v) for v in local]}
        children = [names.index(other) for other, up in PARENTS.items() if up == joint]
        if children:
            node["children"] = children
        nodes.append(node)
    skin_at = len(nodes)
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    images = []
    for stem in ("albedo", "material", "normal"):
        bytes_ = (textures / name / f"{stem}.jpg").read_bytes()
        offset = len(blob)
        blob.extend(bytes_)
        blob.extend(b"\0" * ((4 - len(bytes_) % 4) % 4))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(bytes_)})
        images.append({"bufferView": len(views) - 1, "mimeType": "image/jpeg", "name": stem})
    document = {
        "asset": {"version": "2.0", "generator": "sentry character pipeline"}, "scene": 0,
        "scenes": [{"nodes": [names.index("pelvis"), skin_at]}], "nodes": nodes,
        "meshes": [{"primitives": [primitive]}],
        "skins": [{"joints": list(range(len(names))), "inverseBindMatrices": add(inverse.reshape(-1, 16), "MAT4", 5126), "skeleton": names.index("pelvis")}],
        "materials": [{"name": "body", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": 1}},
                       "normalTexture": {"index": 2}}],
        "textures": [{"source": 0}, {"source": 1}, {"source": 2}], "images": images,
        "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
    }
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{name}.glb", "wb") as file:
        file.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(payload) + 8 + len(blob)))
        file.write(struct.pack("<II", len(payload), 0x4E4F534A))
        file.write(payload)
        file.write(struct.pack("<II", len(blob), 0x004E4942))
        file.write(bytes(blob))
    print("wrote", out / f"{name}.glb", len(blob) // 1024, "KB")


if __name__ == "__main__":
    for character in sys.argv[4:]:
        export(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), character)
