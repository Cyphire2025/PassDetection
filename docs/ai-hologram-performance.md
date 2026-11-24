# AI particle scene performance

The default Test scene downloads prepared particle attributes instead of sampling
the source head and loading anatomy volumes on each device. Its shader evaluates
eight recent pointer strokes around each particle's authored position. Movement
cannot accumulate drift: the offset is capped at 0.14 local units and returns to
zero within 0.65 seconds of the last stroke. Speech uses the original facial
morphs; listening and playback hold automatic rotation, retain 28% of ambient
motion, and playback adds a pale cyan response.

## Assets and rendering budgets

- Each appearance contains 43,264 deterministically ordered particles, with
  signed 16-bit positions and signed 8-bit normal/morph/detail attributes.
  Attribute scales are stored in the `GCPART02` header. Gzip transfer is about
  0.6 MB per appearance; the loader bounds expanded input to 3 MB.
- The initial scene asset budget is 1.8 MB, including a small still preview.
  Terrain color atlases are 1024 pixels. Source assets remain available for
  reproducible generation and the other appearance modes.
- Only content-hashed public files receive immutable cache headers. Particle
  and terrain binary files use HTTP gzip decoding, with an explicit decompression
  fallback for plain static preview servers. Account pages and APIs retain private caching.
- Native rendering starts with 43,264 particles, or 30,976 on smaller/low-core
  devices. Software rendering starts at 25,600. Pixel budgets are 2 million
  desktop / 1 million mobile, with adaptive resolution and draw counts.
- Reduced motion, hidden tabs, off-screen scenes, resource disposal, context
  restoration, and the still-image fallback remain supported. The enclosure
  renders cylindrical walls and rims without cap triangles or cap particles.

Regenerate assets from the repository's authored geometry and original terrain:

```sh
cd frontend
npm ci
node scripts/build-test-hologram-assets.mjs
```

Review and commit the generated manifests and referenced hash-named files
together. `next.config.ts` reads those manifests to scope static headers. Old
hash-named files can be retired deliberately after checking all references;
the generator does not delete files automatically.

## Verification

Run the ordinary frontend lint, type, unit, maintainability and build checks.
The hologram browser configuration adds bounded startup/transfer measurements,
real GPU silhouette recovery, voice playback color and rotation checks,
orientation, control, resource lifetime, and density regression coverage.

For production startup measurements, build with the isolated loopback API origins
from `frontend/config/e2e-isolation.ts`, then run in PowerShell:

```powershell
$env:HOLOGRAM_PRODUCTION = '1'
$env:HOLOGRAM_HARDWARE = '1' # Windows Chromium / ANGLE D3D11 native GPU
npx playwright test --config=playwright.hologram.config.ts
```

Set `HOLOGRAM_HARDWARE=0` for software-rendering functional checks. Production
startup timing is an explicit hardware benchmark; software GPU timing does not
represent a physical phone. Set `HOLOGRAM_WEBKIT=1` to run the portable WebKit
orientation and rendering suite. CDP input and performance tests use Chromium.

`performance.json` records navigation and component startup, transferred scene
bytes, renderer identity, frame intervals, and rendering errors. The phone-sized
benchmark uses a 390×844 viewport, DPR 3, 4× CPU throttling, and 20 Mbps / 40 ms
network emulation. API/session responses are synthetic and local; these results
do not measure production authentication latency, mobile GPU performance, or
every device/network. Real-device field measurements remain necessary for a
universal startup claim.

Startup measurement omits the detailed WebGL uniform/resource inspector used by
the interaction regressions. A lightweight counter observes actual GPU draw calls
after the first complete scene, so diagnostic readbacks do not inflate startup.
