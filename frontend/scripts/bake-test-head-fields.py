"""Offline mesh-derived fields. Run through build-test-head-fields.mjs; no downloads.

NumPy/SciPy come from the existing pinned backend environment. Occupancy is the
same signed-union/optical-chamber subtraction used by the TypeScript sampler.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.spatial import cKDTree


def closest_points(points: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exact point/triangle distances and barycentrics for broadcast candidate sets."""
    a, b, c = (triangles[..., corner, :] for corner in range(3))
    ab, ac, ap = b - a, c - a, points - a
    d00, d01, d11 = (np.sum(u * v, axis=-1) for u, v in ((ab, ab), (ab, ac), (ac, ac)))
    d20, d21 = np.sum(ap * ab, axis=-1), np.sum(ap * ac, axis=-1)
    denominator = np.maximum(d00 * d11 - d01 * d01, 1e-24)
    v, w = (d11 * d20 - d01 * d21) / denominator, (d00 * d21 - d01 * d20) / denominator
    weights = np.stack((1 - v - w, v, w), axis=-1)
    projected = np.sum(triangles * weights[..., None], axis=-2)
    distance = np.sum((projected - points) ** 2, axis=-1)
    distance[np.min(weights, axis=-1) < 0] = np.inf
    for first, second in ((0, 1), (1, 2), (2, 0)):
        start, end = triangles[..., first, :], triangles[..., second, :]
        edge = end - start
        t = np.clip(np.sum((points - start) * edge, axis=-1) / np.maximum(np.sum(edge * edge, axis=-1), 1e-24), 0, 1)
        edge_distance = np.sum((start + t[..., None] * edge - points) ** 2, axis=-1)
        better = edge_distance < distance
        edge_weights = np.zeros_like(weights)
        edge_weights[..., first], edge_weights[..., second] = 1 - t, t
        distance = np.where(better, edge_distance, distance)
        weights = np.where(better[..., None], edge_weights, weights)
    return distance, weights


def nearest_surface(points: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exact nearest triangles, pruning centroid trees by each triangle's radius.

    Radius buckets prevent small, dense hair triangles inheriting the larger neck
    triangles' search radius. Every omitted candidate has a proven lower bound
    above the current best; this is not a fixed-k nearest-centroid approximation.
    """
    centers = triangles.mean(axis=1)
    radii = np.linalg.norm(triangles - centers[:, None, :], axis=2).max(axis=1)
    groups = np.searchsorted([.005, .01, .02, .04, .08, .16, .32], radii)
    buckets = []
    for group in np.unique(groups):
        indices = np.flatnonzero(groups == group)
        buckets.append((indices, cKDTree(centers[indices]), radii[indices].max()))
    ids = np.zeros(len(points), dtype=np.int32)
    weights = np.zeros((len(points), 3), dtype=np.float64)
    for offset in range(0, len(points), 512):
        p = points[offset:offset + 512]
        best = np.full(len(p), np.inf)
        for indices, tree, radius in reversed(buckets):
            active = np.arange(len(p))
            count = min(4, len(indices))
            while len(active):
                distances, candidates = tree.query(p[active], k=count, workers=1)
                distances, candidates = distances.reshape(len(active), count), candidates.reshape(len(active), count)
                candidate_ids = indices[candidates]
                squared, bary = closest_points(p[active, None, :], triangles[candidate_ids])
                chosen = np.argmin(squared, axis=1)
                candidate_best = squared[np.arange(len(active)), chosen]
                changed = candidate_best < best[active]
                rows = active[changed]
                best[rows] = candidate_best[changed]
                ids[offset + rows] = candidate_ids[changed, chosen[changed]]
                weights[offset + rows] = bary[changed, chosen[changed]]
                if count == len(indices):
                    break
                unresolved = distances[:, -1] - radius <= np.sqrt(best[active]) + 1e-10
                active = active[unresolved]
                count = min(len(indices), count * 2)
    return ids, weights


def bake(folder: Path, output: Path, appearance: str, manifest: dict) -> dict:
    started = time.monotonic()
    spec, side = manifest["appearances"][appearance], manifest["side"]
    arrays = {name: np.fromfile(folder / entry["file"], dtype=f"<{ 'u2' if entry['type'] == 'uint16' else 'f4' }").reshape(-1, 3)
              for name, entry in spec["arrays"].items()}
    indices = arrays.pop("triangles").astype(np.int32)
    triangles = arrays["positions"][indices].astype(np.float64)
    minimum, size = np.array(spec["min"]), np.array(spec["size"])
    spacing = size / side
    z, y, x = np.meshgrid(*(np.arange(side) + .5 for _ in range(3)), indexing="ij")
    points = minimum + np.stack((x, y, z), axis=-1).reshape(-1, 3) * spacing
    occupancy = np.fromfile(folder / f"{appearance}-occupancy.bin", dtype=np.uint8).reshape(side, side, side).astype(bool)
    outside = distance_transform_edt(~occupancy, sampling=spacing[::-1])
    inside = distance_transform_edt(occupancy, sampling=spacing[::-1])
    sdf = gaussian_filter(outside - inside, sigma=.45, mode="nearest")
    gradient = np.stack(np.gradient(sdf, *spacing[::-1])[::-1], axis=-1).reshape(-1, 3)
    gradient /= np.maximum(np.linalg.norm(gradient, axis=1, keepdims=True), 1e-10)
    nearest, bary = nearest_surface(points, triangles)
    vertices = indices[nearest]
    interpolated = {name: np.sum(values[vertices] * bary[..., None], axis=1) for name, values in arrays.items() if name != "positions"}
    normals = interpolated["normals"]
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-10)
    fields = np.zeros((9, side ** 3, 4), dtype=np.float32)
    fields[0, :, :3], fields[0, :, 3] = gradient, sdf.ravel()
    for index, name in enumerate(spec["morphs"]):
        fields[index + 1, :, :3] = interpolated[name]
        if index < 3:
            fields[index + 1, :, 3] = normals[:, index]
    fields[7, :, :3] = interpolated["eyes"]
    fields[8, :, :2] = interpolated["detail"][:, :2]
    fields[8, :, 2] = np.clip(-sdf.ravel() / .25, 0, 1)
    # Anatomy metadata describes nearby surfaces, not an iris tag carried through
    # the whole skull. Deliberately retain morphs/normals through the interior.
    fields[7, np.abs(sdf.ravel()) > spacing.max() * 1.5, :3] = 0
    if not np.isfinite(fields).all():
        raise ValueError("Non-finite baked field")
    payload = fields.astype("<f2").tobytes()
    header = bytearray(128)
    struct.pack_into("<8sIIIII", header, 0, b"GCHSDF01", 1, side, 9, int(appearance == "male"), len(payload))
    struct.pack_into("<6f", header, 32, *minimum, *size)
    header[64:96] = bytes.fromhex(manifest["sourceHash"])
    binary = bytes(header) + payload
    compressed = gzip.compress(binary, compresslevel=9, mtime=0)
    filename = f"fields-{appearance}-v1.bin.gz"
    (output / filename).write_bytes(compressed)
    report = {"file": filename, "sha256": hashlib.sha256(compressed).hexdigest(), "bytes": len(compressed),
              "decodedBytes": len(binary), "gpuBytes": len(payload), "min": spec["min"], "size": spec["size"],
              "occupiedVoxels": int(occupancy.sum()), "distanceRange": [float(sdf.min()), float(sdf.max())],
              "fieldOrder": ["gradient-distance", *spec["morphs"], "eyes", "detail"]}
    print(f"{appearance}: {len(compressed):,} bytes gzip; {len(payload):,} GPU bytes; baked in {time.monotonic() - started:.1f}s", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.input / "input.json").read_text(encoding="utf-8"))
    report = {"version": 1, "resolution": manifest["side"], "sourceHeadSha256": manifest["sourceHash"],
              "sourceModules": manifest["sources"], "assets": {}}
    for appearance in ("female", "male"):
        report["assets"][appearance] = bake(args.input, args.output, appearance, manifest)
    (args.output / "fields-v1.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
