# Mobile API and realtime capacity gate

These k6 harnesses exercise the authenticated cursor API and foreground WebSocket channel with
unique, pre-provisioned staging sessions. They are release-gate tools, not proof by their mere
presence. A capacity claim requires a recorded run through the actual staging CDN, reverse proxy,
API replicas, Redis, PostgreSQL, and object-storage topology that mirrors production.

## Non-production safety contract

The harnesses fail closed unless all of these values are present and mutually consistent:

- `LOAD_TEST_APPROVED=true`
- `LOAD_TEST_TARGET_ENVIRONMENT=staging`
- `LOAD_TEST_APPROVAL_REFERENCE` is the authorized change/ticket identifier
- `LOAD_TEST_EXPECTED_ORIGIN` is the exact staging HTTPS origin
- `LOAD_TEST_PRODUCTION_ORIGIN` is the exact, different production HTTPS origin
- `BASE_URL` is exactly the staging origin plus `/api/v1`
- `LOAD_TEST_ID` is a unique operational correlation identifier

Do not weaken these controls to test production. Use a dedicated staging environment, approved
traffic ceilings, synthetic data, monitoring coverage, an operator stop condition, and a rollback
owner. The scripts perform a readiness preflight before opening authenticated traffic; the realtime
test additionally requires the server's `mobile_realtime` readiness check to be `ok`. Both tests
also require the target liveness response to identify itself as `APP_ENV=staging`; a production or
misconfigured environment is rejected before authenticated traffic starts.

## Fixture contract

Never commit the credential file. Generate short-lived synthetic staging accounts and one active
mobile session per virtual user. The scripts reject duplicate access tokens because reusing one
session would exercise the per-session socket limit instead of the intended population. The JSON
file is:

```json
[
  {
    "access_token": "short-lived-staging-mobile-access-token",
    "trip_id": "11111111-1111-4111-8111-111111111111",
    "authorized_trip_ids": ["11111111-1111-4111-8111-111111111111"],
    "cursor": 0
  }
]
```

`trip_id` selects the API reconciliation trip. `authorized_trip_ids` must contain every trip that
the same token may receive through realtime; it defaults to the one `trip_id` when omitted. This
prevents legitimate multi-trip manager/coordinator hints from being mislabeled as cross-scope data.
The cursor should be a valid starting watermark for that synthetic session. The 1k, 5k, and 10k
profiles require at least that many unique entries. Keep the file outside Git, encrypt it at rest,
restrict its permissions, delete it after the run, and revoke every generated session. Never place
tokens, trip identifiers, passenger identifiers, or document identifiers in k6 tags or logs.

## Profiles and traffic model

| Profile | Peak stateful VUs | Ramp and hold |
| --- | ---: | --- |
| `smoke` | 10 | 15-second ramp, 2-minute hold, 15-second ramp-down |
| `1k` | 1,000 | 5-minute ramp, 60-minute hold, 5-minute ramp-down |
| `5k` | 5,000 | 1k in 5 minutes, 5k in 10 minutes, 60-minute hold |
| `10k` | 10,000 | 1k/5k/10k staged ramps, then a 60-minute hold |

Both scripts use stateful VUs and assign one unique session by the globally unique k6 VU ID. The
API VU maintains and advances its own cursor, drains at most 20 bounded pages, and defaults to a
30-second reconciliation cadence with jitter. It validates response size, JSON shape, strict
sequence ordering, cursor monotonicity, trip scope, convergence, and manifest scope. It fetches a
manifest at startup and every 20 cycles by default.

The realtime VU validates the ready frame, heartbeat exchange, trip-scoped monotonic hints, and
planned socket closure. The default connection lifetime is 45 seconds for smoke and 15 minutes for
larger profiles, with jitter so reconnects are not synchronized. Supported controlled overrides are:

- `MOBILE_SYNC_INTERVAL_SECONDS=5..300`
- `MOBILE_SYNC_MAX_PAGES_PER_CYCLE=1..20`
- `MOBILE_MANIFEST_EVERY_CYCLES=1..120`
- `MOBILE_SOCKET_LIFETIME_SECONDS=30..3600`

## Authorized run sequence

k6 is an external prerequisite; it is not installed by this repository. Use a dedicated load
generator and monitor its CPU, memory, network, and file descriptors. Use distributed generators
for 5k/10k and whenever one generator cannot preserve at least 20% idle CPU and safe memory
headroom. Start with smoke, then 1k, and promote only after every previous gate passes.

Distributed execution must use coordinated k6 execution segments or a managed/cloud run that
preserves globally unique `vu.idInTest` values and partitions the configured profile once. Do not
start the complete 5k or 10k profile independently on multiple machines: that multiplies the
intended traffic, reuses fixture identities, and invalidates both authorization and capacity
evidence. Record the segment allocation and aggregate generator telemetry with the result.

Example PowerShell configuration:

```powershell
$env:BASE_URL = "https://mobile-staging.example.com/api/v1"
$env:LOAD_TEST_EXPECTED_ORIGIN = "https://mobile-staging.example.com"
$env:LOAD_TEST_PRODUCTION_ORIGIN = "https://mobile.example.com"
$env:LOAD_TEST_TARGET_ENVIRONMENT = "staging"
$env:LOAD_TEST_APPROVAL_REFERENCE = "change-12345"
$env:LOAD_TEST_ID = "mobile-rc-2026-08-19"
$env:LOAD_TEST_APPROVED = "true"
$env:MOBILE_LOAD_DATA = "C:\secure\mobile-load-data.json"
$env:MOBILE_LOAD_PROFILE = "smoke"

k6 run --summary-export ".\evidence\$($env:LOAD_TEST_ID)-realtime.json" .\load-tests\k6\mobile-realtime.js
k6 run --summary-export ".\evidence\$($env:LOAD_TEST_ID)-api.json" .\load-tests\k6\mobile-api.js
```

Do not run the API and realtime peak profiles concurrently until each has passed independently and
the combined concurrency is part of the approved scenario. A separate 24-hour soak is required
before a sustained-capacity claim.

## Pass/fail evidence

The scripts make these test-breaking conditions: authorization or rate-limit failures, proxy
failures, malformed/oversized responses, cross-trip data, cursor regression, an API cycle that
cannot converge within 20 pages, invalid WebSocket frames, connection success at or below 99%,
unexpected disconnects at or above 1%, HTTP failures at or above 1%, API/ready p95 at or above two
seconds, or p99 at or above five seconds.

Retain the immutable k6 summary, generator telemetry, exact fixture-generation audit (without
secrets), Git revision, deployment/image revision, configuration snapshot, and matching time-window
dashboards for API p50/p95/p99, errors, event-loop lag, process CPU/RSS, active connections,
slow-consumer closures, authorization-query latency, PostgreSQL connection-pool wait/saturation and
query plans, Redis pub/sub lag/output buffers, Nginx/CDN connections and file descriptors, hint
drops, reconnects, and cursor convergence.

Run separately approved failure scenarios for a Redis restart, one API-worker restart, Nginx
reload, token expiry, hint loss/reorder, slow consumers, and a reconnect burst. A successful
transport run does not prove dashboard-to-device freshness: use a separate test-only dashboard
mutation fixture with a unique commit marker and measure commit-to-visible metadata latency at p95
at or below two seconds and p99 at or below five seconds. The scripts intentionally do not publish
dashboard mutations because that requires separately controlled operator credentials.
