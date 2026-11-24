"""Build the first-party particle head asset from pinned CC0 source geometry.

Run with the backend's pinned Python/NumPy environment. Downloads only the
reviewed source arrays into --cache; the browser does not contact upstream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import urllib.request
from pathlib import Path

import numpy as np

ASSET = Path(__file__).resolve().parents[1] / "public/ai/human-head"
MORPHS = {
    "jaw": ["aa_02"],
    "round": ["ow_08"],
    "wide": [
        "Lips_Up_Corner_Wide_Left", "Lips_Up_Corner_Wide_Right",
        "Lips_Dn_Corner_Wide_Left", "Lips_Dn_Corner_Wide_Right",
    ],
    "closure": ["p_b_m_21"],
    "fricative": ["f_v_18"],
    "blink": ["Eyes_Closed_Max"],
}


def source_arrays(cache: Path) -> dict[str, Path]:
    manifest = json.loads((ASSET / "sources.json").read_text(encoding="utf-8"))
    cache.mkdir(parents=True, exist_ok=True)
    result = {}
    for source in manifest["files"]:
        path = cache / Path(source["path"]).name
        if not path.exists():
            url = f"{manifest['raw_base']}/{source['path']}"
            request = urllib.request.Request(url, headers={"User-Agent": "GlobalConnects-asset-build"})
            with urllib.request.urlopen(request, timeout=30) as response:
                path.write_bytes(response.read())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != source["sha256"]:
            raise ValueError(f"Source checksum mismatch: {source['path']}")
        result[path.stem] = path
    return result


def delta(path: Path, count: int) -> np.ndarray:
    with np.load(path, allow_pickle=False) as source:
        result = np.zeros((count, 3), dtype=np.float64)
        result[source["idx"]] = source["delta"]
    return result


def normals(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    a, b, c = (vertices[triangles[:, i]] for i in range(3))
    areas = np.cross(b - a, c - a)
    result = np.zeros_like(vertices)
    for i in range(3):
        np.add.at(result, triangles[:, i], areas)
    return result / np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-12)


def build(cache: Path) -> None:
    sources = source_arrays(cache)
    base = np.load(sources["Default"], allow_pickle=False)
    faces = np.load(sources["faces"], allow_pickle=False)
    # Retain the complete head, ears, eyes, mouth interior and a short neck.
    # The quad topology and all FACS shapes keep the original vertex mapping.
    faces = faces[np.all(base[faces, 2] > 1.47, axis=1)]
    original, inverse = np.unique(faces, return_inverse=True)
    quads = inverse.reshape((-1, 4))
    triangles = np.concatenate((quads[:, [0, 1, 2]], quads[:, [0, 2, 3]])).astype("<u2")
    edges = np.concatenate([quads[:, [i, (i + 1) % 4]] for i in range(4)])
    edges = np.unique(np.sort(edges, axis=1), axis=0).astype("<u2")
    # Proper-handed rotation: source Z-up/-Y-forward -> Y-up/+Z-forward.
    rotation = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)
    center = np.array([0.0, 0.016, 1.61])
    scale = 7.0
    arrays = []
    for appearance in ("Female", "Male"):
        positions = ((base + delta(sources[f"Gender_{appearance}"], len(base)))[original] - center) @ rotation * scale
        arrays.extend((positions, normals(positions, triangles)))
    for names in MORPHS.values():
        shape = sum((delta(sources[name], len(base)) for name in names), np.zeros_like(base))
        arrays.append(shape[original] @ rotation * scale)
    if len(original) >= 65536:
        raise ValueError("Head exceeds WebGL1 index capacity")
    scales = [max(float(np.abs(array).max()), 1e-9) / 32767 for array in arrays]
    header = b"GCHEAD01" + struct.pack("<4I10f", len(original), triangles.size, edges.size, len(arrays), *scales)
    assert len(header) == 64
    payload = b"".join(np.rint(array / unit).astype("<i2").tobytes() for array, unit in zip(arrays, scales))
    output = header + payload + triangles.tobytes() + edges.tobytes()
    destination = ASSET / "head-v1.bin"
    destination.write_bytes(output)
    stats = {
        "bytes": len(output), "sha256": hashlib.sha256(output).hexdigest(),
        "vertices": len(original), "triangles": len(triangles), "edges": len(edges),
        "female_bounds": [arrays[0].min(0).tolist(), arrays[0].max(0).tolist()],
        "male_bounds": [arrays[2].min(0).tolist(), arrays[2].max(0).tolist()],
    }
    (ASSET / "geometry.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    build(parser.parse_args().cache)
