# Spatial adult-head fields

These are original, offline-generated volume fields derived exclusively from
the CC0 human-head geometry documented in this folder's `README.md` and
`sources.json`, plus the repository's adult-head and hair preparation. No Igloo
or tutorial source, volume, model, or shader is included in these files.

Rebuild from `frontend/` using the reviewed Node runtime and the existing pinned
backend Python environment (NumPy and SciPy):

```text
node scripts/build-test-head-fields.mjs --work <absolute-temporary-build-folder>
```

`--python` can select that environment explicitly. The exporter calls the same
`prepareTestHead(mesh, appearance)` used by the renderer. It computes signed
solid-union occupancy using `createHeadVolume`, including its subtraction of
the clear chamber between the iris and cornea. SciPy computes an anisotropic
Euclidean distance transform and a mildly smoothed gradient. Surface normals,
eye labels, hair metadata and six morph vectors are interpolated from the exact
nearest triangle, with barycentric coordinates. Centroid-tree pruning is bounded
by each radius bucket, so large triangles are not silently skipped by a fixed
nearest-centroid candidate count.

Each appearance is a gzip-compressed binary. The selected appearance uses nine
64×64×64 RGBA16F textures, exactly 18 MiB of GPU field storage. Other appearances
are not loaded or cached as GPU resources. `fields-v1.json` records compressed
hashes, sizes, bounds, source head hash and every preparation module hash.

## Binary format, version 1

All numeric data is little-endian. The header is 128 bytes:

| Offset | Value |
| --- | --- |
| 0 | Eight-byte ASCII `GCHSDF01` |
| 8 | uint32 version, `1` |
| 12 | uint32 cubic resolution, `64` |
| 16 | uint32 field count, `9` |
| 20 | uint32 appearance: female `0`, male `1` |
| 24 | uint32 payload byte count |
| 32 | float32×3 minimum XYZ of the texture's outer bounds |
| 44 | float32×3 XYZ size of those bounds |
| 64 | 32 bytes: SHA-256 of the source `head-v1.bin` |

The payload is nine contiguous RGBA16F arrays, X fastest and Z outermost. A
voxel center is `min + (index + 0.5) * size / 64`; canonical positions map to
texture coordinates with `(position - min) / size`.

1. RGB outward distance-field gradient, A signed distance in head units
   (negative inside).
2. Jaw morph XYZ, A closest-surface normal X.
3. Round morph XYZ, A closest-surface normal Y.
4. Wide morph XYZ, A closest-surface normal Z.
5. Closure morph XYZ, A reserved.
6. Fricative morph XYZ, A reserved.
7. Blink morph XYZ, A reserved.
8. Eye-region XYZ (local eye coordinates and component label), A reserved.
9. Hair metadata XY, Z normalized interior depth, A reserved.

## Resolution and usage limits

The fields approximate a continuous surface on a finite grid; sub-voxel eye
chambers, eyelid rims and fine hair edges cannot be geometrically exact at 64³.
Optical exclusions are applied before voxelization, and eye labels are limited
to the nearby boundary rather than extending through the skull. Surface normals
are stored separately from the coarser distance gradient to preserve anatomical
lighting. Morph vectors are spatially sampled displacement fields; they are not
independently baked signed-distance volumes for each facial pose.

The browser validates the layout and finite samples before creating textures,
bounds both compressed and expanded reads, supports cancellation and a 25-second
preparation deadline, and releases each owned texture once. It uses standard
`DecompressionStream` only; no worker, external decoder, dynamic JavaScript
evaluation or CSP exception is required.
