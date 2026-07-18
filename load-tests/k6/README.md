# Controlled passport-extraction burst test

This harness starts 100 independent public-link bootstrap requests and uploads
at approximately the same time, then polls each durable submission until
extraction is terminal. It records bootstrap, upload and end-to-end latency
failures, 429 origin, proxy failures, polling retries, duplicates, and success
count. Every tenth virtual user also repeats its exact upload idempotency key
after the extraction burst drains and requires the same durable submission ID.

It is intentionally not bundled with real passport data. Use only approved,
synthetic or otherwise non-production fixtures in an isolated staging copy.

Create a manifest with at least 100 entries. The first 100 entries must point
to 100 distinct approved front/back fixture pairs; repeating one pair across
several virtual users is rejected before traffic starts. Paths are resolved by
k6 from the working directory:

```json
[
  {
    "front": "./fixtures/001-front.jpg",
    "back": "./fixtures/001-back.jpg"
  }
]
```

Pre-seed a realistic post-submission verification backlog, then run:

```powershell
$env:BASE_URL = "https://staging.example.test"
$env:UPLOAD_TOKEN = "<staging upload link token>"
$env:FIXTURE_MANIFEST = "./load-tests/k6/fixtures/manifest.json"
$env:LOAD_TEST_ID = "release-candidate-001"
$env:IDEMPOTENCY_PROBE = "true"
k6 run .\load-tests\k6\passport-extraction.js
```

Use a staging upload link with `Relation with Qualifier` disabled for this
extraction-capacity run. Qualifier-enabled links have an additional user choice
and one-time bearer selection that should be tested separately as a functional
flow rather than fabricated by the load harness.

Before treating the result as a release gate, capture the matching server-side
metrics for queue wait, Gemini duration and retries, active extraction and
verification counts, Redis usage, database-pool saturation, CPU, memory, and open
connections. The script’s p99 threshold is 40 seconds, leaving five seconds of
the 45-second objective for browser and network overhead.

The release threshold counts only `extraction_complete` as success. Partial
field extraction and the manual-review fallback are reported separately and
fail this 100/100 capacity gate even though they remain valid product fallbacks
for an individual traveller.

Do not claim the concurrency objective from a dry run, mocked provider, or the
published Gemini RPM limit. A passing result requires the production-like worker
topology, Redis coordinator, Nginx configuration, and controlled Gemini project
to be active together.
