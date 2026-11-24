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

The original mesh transforms are preserved. The reference composition uses a
31-degree perspective from world `(-20, 3.5, 20)`, aimed at `(0, 2.5, 0)`.
In its unconstrained desktop framing, the distant main summit is near 15.4% of
the screen height and the original building's ground contact is near 69.2%.
Responsive framing fits the scene between the actual header and microphone and
inside the available portrait width, including a visible conversation panel.
The Test view extends that forward composition with staggered, varied copies of the
same terrain around the camera, overlapping snowfields and a continuous ground base.
Subtle global pointer parallax and an ambient drift orbit a fixed scene target.
Shift-drag, two-finger drag, or Shift-arrow keys explore the full 360-degree
landscape; an ordinary drag or arrow key independently turns the face. There is
no rotation-mode toolbar. Home or double-click restores both views together.
This surrounding layout is our integration,
not an additional environment taken from the reference site. All placements share
the existing geometry and textures; rotation does not load additional assets.
The central igloo building, branding, copy, audio and interaction code are
not included. The ground texture is the original `ground_sansigloo_color.ktx2`.
The circular platform occupies the original building's ground position in the
same world scene as the terrain. Its buried lower flange intersects the snow,
and its contact shading conforms to the original ground triangles. The platform,
terrain and particle head share one camera, depth buffer and colour grade. The
stone borrows the terrain's existing texture; it does not load another atlas.
The sculpture's world scale is 4. The platform's horizontal scale is 1.045, giving
a 9.3632-unit footprint; its vertical dimensions and ground anchor stay fixed.
The face uses a local scale of 0.95 to preserve clearance within the composition.
Its idle turn pauses during microphone speech and audible playback, while shared
smooth deformation keeps the granular volume moving. The head renders only
depth-writing particle spheres, with no opaque support mesh or authored wire pass.
Sixty percent of its fixed particle budget samples the detailed outer anatomy;
forty percent fills the actual closed volume using accelerated signed scanlines.
Interior grains inherit facial morphs from their real bounding surfaces. The
transparent chamber between each iris and cornea stays clear. Neighboring grains
throughout the volume follow the same flow with small independent detail. Pointer
strokes transport a local patch through its depth and brighten displaced grains.
All particles remain bounded by the cylinder during manual tilt and zoom.
A localized counterclockwise ripple reveals the closed cylindrical lattice only
where its wave passes. Its short irregular cells avoid long radial cap spokes.
The centered projector aperture and short rays below the neck remain visible at
rest; their intensity responds to interaction and voice. The two valley haze
layers have denser white wisps without changing their advection speed.
The face and recessed light band also illuminate nearby snow with a bounded
diffuse-light approximation. Terrain, floor and powder collar share the same
world-space light uniforms, surface-normal response and distance falloff; this
adds no rendering pass or shadow map. It is not a ray-traced lighting pipeline.
The microphone samples an interior snow-atlas patch with a subtle bevel and glow.
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
