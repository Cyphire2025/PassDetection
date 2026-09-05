# Visa photo browser regression

Run from `frontend` with Node dependencies and Playwright Chromium installed:

```sh
node scripts/verify-visa-photo-browser.mjs --baseline
node scripts/verify-visa-photo-browser.mjs
```

The baseline command loads the untouched installed MediaPipe 0.4.1646425229
API and WASM loaders. It **passes when it reproduces the original CSP failure**
on both scalar and SIMD loaders. The normal command loads the patched files in
`public` through the application's real `loadVisaFaceDetection()` script loader
and fails if real face inference or upload validation fails.

The harness serves a private, temporary localhost HTTP server. It extracts the
actual production CSP builder from `proxy.ts`, supplies a nonce, and never permits
JavaScript `unsafe-eval`. It bundles the real upload validation and script-loading
modules and uses the actual local graph, model, and WASM assets. The normal page
does not preload the API: the application loader downloads it as it would in
production. The server chooses scalar or SIMD loader files explicitly and records
the served asset names. The detector and background evaluator are not mocked.

Checks include:

- Original loader failure with a browser `securitypolicyviolation` for `eval`.
- Patched scalar and SIMD inference: a detectable face, a blank image without a
  face, and five stable repeated detections, with no CSP violations.
- Full upload processing after prewarming: face plus white outer background
  passes, blank image fails, colored background fails, and later valid images
  still pass. Every returned file is an 800 × 1200 JPEG below 2 MB.
- A real HTTP 503 on the graph fetch rejects the first validation. A subsequent
  retry in the same page loads the model successfully and passes.
- A graph network failure while its sibling WASM script is delayed by 500 ms
  waits for that script to settle before reporting failure. An immediate retry
  then passes without the original `Module.arguments` initialization race.
- A real HTTP 522 on the WASM loader script rejects within the bounded timeout;
  an immediate retry passes. Network cases inspect both CSP violations and
  uncaught page errors after the retry.

`test-results/visa-photo-browser/baseline.json` and `verification.json` contain
timings, policy, asset requests, assertions, and output metadata. The directory is
ignored by Git. The only external fixture is the [official MediaPipe test
portrait](https://storage.googleapis.com/mediapipe-assets/portrait.jpg), pinned to
SHA-256 `a6f11efaa834706db23f275b6115058fa87fc7f14362681e6abe14e82749de3e`.
It is downloaded once to the ignored test directory. Synthetic composites of its
face region provide controlled white and colored outer backgrounds. These are
test inputs only; they are not published as product sample images.

For a focused network regression, append one of
`--scenario=graph-http503`, `--scenario=graph-network-failure-delayed-loader`, or
`--scenario=loader-http522`. This runs that scenario only. Generated browser entry
code uses `.mjs` so Next's TypeScript project does not include it.

On 5 September 2026, local headless Chromium 151 with SwiftShader passed all
checks. Cold API/model initialization plus inference took 1.08–1.31 seconds;
prewarming took 1.11–1.28 seconds; complete file validation after prewarming took
70–136 milliseconds. The delayed network failure rejected after 625 milliseconds
and its immediate retry passed in 994 milliseconds. HTTP 522 rejected after 45
milliseconds, with a successful retry in 1.02 seconds. These are local fixture
measurements, not a production network, physical-device performance, or broad
photo-accuracy claim.
