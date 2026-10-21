# Human head geometry

`head-v1.bin` is derived from **Vitruvian for CharMorph**, by **Sean Buckley and
Olaf Delgado-Friedrichs**, licensed **CC0 1.0 Universal**. The upstream metadata
explicitly identifies the model and its morphs as CC0; its add-on code is not used.
See `upstream-config.yaml`, `sources.json`, and `LICENSE-CC0.txt`.
The metadata snapshot has trailing whitespace removed; source hashes describe
the original upstream bytes checked by the rebuild script.

Source: https://github.com/Upliner/CharMorph-Vitruvian/tree/c252d1fc7f00ba59d87b66b3d32fa3471fc6ee44
License: https://creativecommons.org/publicdomain/zero/1.0/

Only geometry is included: a full head with ears, eyes, lips, mouth interior and
short neck. No portraits, textures, third-party runtime or downloaded executable
is required. The asset is hosted locally. It contains 16,911 vertices, two shape
variants and six authored facial morph channels; `geometry.json` records counts,
bounds and the output checksum. There are no source body meshes in the bundle.

## Rebuild

From repository root, use the pinned backend Python environment (which includes
NumPy). Choose a separate source cache, outside the public asset directory:

```powershell
backend/.venv/Scripts/python.exe frontend/scripts/build-human-head.py --cache "$env:TEMP/passdetection-head-research"
```

The script downloads the small arrays listed in `sources.json` at a fixed commit,
checks every SHA-256, rejects pickled NumPy data, preserves the original vertex
mapping and quad edges, and produces the binary deterministically. It crops at
source Z=1.47, applies the authored Gender_Female/Gender_Male shape deltas, rotates
to Y-up/+Z-forward, recenters at source (0, .016, 1.61) and scales by 7.

The transparent `female-still.png` and `male-still.png` fallbacks are rendered from
that same binary with a depth buffer and its original quad edges. Rebuild them
with `backend/.venv/Scripts/python.exe frontend/scripts/render-human-head-stills.py`.
They are luminous white for dark backgrounds; tint them with CSS for a light theme.

## Renderer contract

`loadHumanHead(appearance, signal)` returns positions, unit normals, triangle and
original quad-edge indices, and additive `jaw`, `round`, `wide`, `closure`,
`fricative`, `blink` morph deltas. All arrays use identical vertex ordering.
X is screen-right, Y is up and +Z faces the camera. Height is approximately 1.94.
Fade the lower neck below Y=-.7 to hide the cropped boundary.

The channels derive from aa_02, ow_08, four corner-widening shapes, p_b_m_21,
f_v_18 and Eyes_Closed_Max respectively. Blend with bounded weights. Attenuate
jaw opening when closure is active; adding full jaw and closure simultaneously
does not represent a closed mouth. These are geometrical facial controls;
phoneme timing must come from the playback controller.

## Binary format v1

All numbers are little endian. The 64-byte header contains ASCII `GCHEAD01`, four
uint32 values (vertex count, triangle-index count, edge-index count, array count
10), then ten float32 quantization scales. Ten XYZ arrays follow as signed int16:
female positions/normals, male positions/normals, jaw, round, wide, closure,
fricative, blink. Multiply each by its header scale. The final two arrays are
uint16 triangle indices and uint16 quad-edge indices. The browser decoder checks
lengths, finite scales, capacity and every index before GPU upload.
