"""Render transparent wire/particle fallbacks directly from the shipped 3D mesh.

Uses only pinned NumPy/Pillow from backend/.venv; no image-generation service,
portraits or external renderer. The z-buffer hides edges behind the face.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ASSET = Path(__file__).resolve().parents[1] / "public/ai/human-head"
WIDTH, HEIGHT = 720, 900


def project(vertices: np.ndarray) -> np.ndarray:
    return vertices * np.array([HEIGHT * .45, -HEIGHT * .45, 1]) + np.array([WIDTH / 2, HEIGHT * .48, 0])


def depth_buffer(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    depth = np.full((HEIGHT, WIDTH), -np.inf)
    for triangle in vertices[triangles]:
        x0, y0 = np.maximum(np.floor(triangle[:, :2].min(0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(triangle[:, :2].max(0)).astype(int), [WIDTH - 1, HEIGHT - 1])
        if x1 < x0 or y1 < y0:
            continue
        a, b, c = triangle
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-8:
            continue
        y, x = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        wa = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / denominator
        wb = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / denominator
        wc = 1 - wa - wb
        z = wa * a[2] + wb * b[2] + wc * c[2]
        inside = (wa >= -.015) & (wb >= -.015) & (wc >= -.015)
        target = depth[y0:y1 + 1, x0:x1 + 1]
        np.maximum(target, np.where(inside, z, -np.inf), out=target)
    return depth


def render(positions: np.ndarray, normals: np.ndarray, triangles: np.ndarray, edges: np.ndarray, name: str) -> None:
    yaw = -.24
    rotation = np.array([[np.cos(yaw), 0, -np.sin(yaw)], [0, 1, 0], [np.sin(yaw), 0, np.cos(yaw)]])
    world = positions @ rotation
    vertices = project(world)
    normals = normals @ rotation
    depth = depth_buffer(vertices, triangles)
    pixels = np.zeros((HEIGHT, WIDTH), dtype=np.float64)
    for batch in np.array_split(edges, 10):
        fraction = np.linspace(0, 1, 36)[None, :, None]
        a, b = vertices[batch[:, 0]][:, None], vertices[batch[:, 1]][:, None]
        points = a * (1 - fraction) + b * fraction
        na, nb = normals[batch[:, 0]][:, None], normals[batch[:, 1]][:, None]
        facing = (na * (1 - fraction) + nb * fraction)[:, :, 2]
        points = points.reshape((-1, 3))
        x = np.clip(np.rint(points[:, 0]).astype(int), 0, WIDTH - 1)
        y = np.clip(np.rint(points[:, 1]).astype(int), 0, HEIGHT - 1)
        visible = points[:, 2] >= depth[y, x] - .006
        fade = np.clip((HEIGHT * .91 - y) / (HEIGHT * .13), 0, 1)
        fade = fade * fade * (3 - 2 * fade)
        brightness = (.3 + .5 * np.maximum(0, facing.reshape(-1))) * fade * visible
        np.maximum.at(pixels, (y, x), brightness)
    alpha = Image.fromarray(np.clip(pixels * 255, 0, 255).astype(np.uint8))
    glow = np.asarray(alpha.filter(ImageFilter.GaussianBlur(2.2)), dtype=float) * .55
    opacity = Image.fromarray(np.clip(np.asarray(alpha, dtype=float) + glow, 0, 255).astype(np.uint8))
    output = Image.new("RGBA", (WIDTH, HEIGHT), (238, 245, 255, 0))
    output.putalpha(opacity)
    output.save(ASSET / f"{name}-still.png", optimize=True)


if __name__ == "__main__":
    data = (ASSET / "head-v1.bin").read_bytes()
    count, triangle_count, edge_count, array_count, *scales = struct.unpack_from("<4I10f", data, 8)
    arrays = np.frombuffer(data, dtype="<i2", count=array_count * count * 3, offset=64).reshape((array_count, count, 3))
    arrays = arrays * np.array(scales)[:, None, None]
    offset = 64 + array_count * count * 6
    triangles = np.frombuffer(data, dtype="<u2", count=triangle_count, offset=offset).reshape((-1, 3))
    edges = np.frombuffer(data, dtype="<u2", count=edge_count, offset=offset + triangle_count * 2).reshape((-1, 2))
    render(arrays[0], arrays[1], triangles, edges, "female")
    render(arrays[2], arrays[3], triangles, edges, "male")
