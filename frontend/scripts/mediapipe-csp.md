# MediaPipe face detection and strict CSP

The vendored `@mediapipe/face_detection` version is **0.4.1646425229**.
Its Emscripten JavaScript bindings originally generate three kinds of functions
from strings. Production permits `wasm-unsafe-eval` for WebAssembly, but does not
permit JavaScript `unsafe-eval`; unmodified bindings therefore fail before a
photograph can be checked.

The same pinned package's main API is also served as
`/mediapipe/face_detection/face_detection.js`. Its initializer loads the graph,
model and JavaScript/WASM concurrently. On failure it now waits for every started
branch to settle before rejecting with the first original error. This includes
nested data and loader groups: an early graph failure can no longer leave an old
loader mutating globals during a retry. Successful loading remains concurrent.
The asset fetcher rejects HTTP errors before interpreting their bodies as model
data, and script load errors reject instead of resolving as if loading succeeded.
`mediapipe-main-loader-bindings.mjs` contains the static drain and script helpers;
the patch script applies the narrowly checked changes to the pinned main API.

`mediapipe-csp-bindings.mjs` implements those same bindings using ordinary static
closures. Both the SIMD and non-SIMD loaders are patched. Argument conversions,
receivers, return conversion, destructor order, names, arity and method caches
remain compatible. The existing short-range model, graph, WASM binaries and
detection algorithm are unchanged. No CSP relaxation is required.

After `npm ci`, run from `frontend`:

```sh
node scripts/patch-mediapipe-csp.mjs --check
node --test scripts/patch-mediapipe-csp.test.mjs
```

To intentionally regenerate the committed assets from the installed upstream
package after editing a binding, use `node scripts/patch-mediapipe-csp.mjs --write`.
Generation checks the package version and upstream SHA-256 hashes before writing;
it refuses an unreviewed package update. It also checks that the graph, model and
WASM hashes still match upstream. Review all dynamic-code sites before changing
those pins for a new release. Commit all three generated JS assets with the source
binding change. Public assets are served directly by Next.js, so deployment must
include the generated files.

The generated JavaScript comparison accepts Git's Windows CRLF checkouts. Source
package hash checks are always byte-exact; line-ending normalization applies only
to our binding replacements and the generated target comparison.

The parity tests compare upstream bindings against the patched ones inside a
Node VM that blocks string code generation. They exercise both loader variants
and reproduce the upstream CSP exception. Main-loader tests verify successful
ordering, draining of delayed nested work, original failure propagation, script
errors, HTTP status validation and successful fetch caching. These tests do not measure browser
inference latency or recognition accuracy; real browser tests under the deployed
CSP cover that integration separately.
