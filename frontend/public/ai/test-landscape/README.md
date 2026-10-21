# Original Igloo terrain assets — local Test preview

These are the publicly served terrain meshes, baked color textures, wind texture,
and color lookup table from https://www.igloo.inc/, retained for local comparison
while implementing the user's request for that exact landscape. No Igloo application
JavaScript is included. The renderer and integration code were written here.

**The artwork is not MIT, CC0, or otherwise known to be openly licensed.** The
original site states “Igloo, Inc. All Rights Reserved.” No public reuse license
was found on the site or its creators' case study. Ownership and copyright are
unchanged; this record does not grant rights or establish authorization for public
redistribution. `provenance.json` records source URLs, byte sizes and SHA-256 hashes.

The scene was created by Abeto and Bureaux for Igloo Inc. The creators describe
their workflow at https://www.awwwards.com/igloo-inc-case-study.html.

The original mesh transforms, camera position and 30-degree perspective are preserved;
the camera target is raised to keep the mountain summits visible above the assistant.
The Test view extends that forward composition with staggered, varied copies of the
same terrain around the camera, overlapping snowfields and a continuous ground base.
Landscape mode turns the camera in place through a full 360 degrees, with a bounded
vertical tilt; Face mode independently rotates the portrait. Reset returns only the
selected view to its starting orientation. This surrounding layout is our integration,
not an additional environment taken from the reference site. All placements share
the existing geometry and textures; rotation does not load additional assets.
The central igloo building, branding, copy, audio and interaction code are
not included. The ground texture is the original `ground_sansigloo_color.ktx2`.
Terrain detail is baked into the 2048×2048 color textures; the original mountain
mesh has 1,703 vertices/2,884 triangles, and ground has 2,780/4,959.

The `.bin` meshes contain the original decoded Float32 position/normal/UV values
and triangle indices without geometry edits. `grade-rgba16f.bin` contains the
original lookup table's unchanged texel bytes, decompressed from `grade.ktx2`.
The `.webp` images preserve every RGBA byte of the original base texture levels
decoded with Basis Universal; no resizing, flipping or color conversion is applied.
The offline build compares PNG and lossless WebP sizes and verifies pixel equality
after decoding the chosen image. The browser regenerates texture mipmaps.

This removes all decoder JavaScript, WASM and workers from the browser, avoiding
the stock Basis string evaluation and Zstd `data:` fetch while preserving the
existing CSP. Rebuild from `frontend/`
with `node scripts/decode-test-landscape.mjs`. Original sources remain alongside
the derived files, whose SHA-256 hashes are recorded in `provenance.json`.

## Decoder software

The offline build uses Draco, Basis Universal and Zstd decoders from the repository's
pinned `three@0.186.1` npm installation, not the Igloo application bundle, and the
existing `sharp@0.35.5` image encoder. Draco and Basis use Apache-2.0; their source
and license files remain in the installed package. No decoder files are shipped
with these public assets. The asset copyright statement above does not apply to
the open-source build tools. No security-policy or dependency-version changes
are required by this integration.
