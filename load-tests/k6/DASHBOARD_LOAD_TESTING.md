# Dashboard 100/200-user load and bounded-soak runbook

## Evidence boundary

`dashboard-load.js` is a staging-only test instrument. Its presence in the repository, its syntax checks, and its contract tests are **not** a passing load result. A dashboard-capacity claim requires dated live runs against the approved deployed revision, all automatic thresholds passing, and matching proxy/application/database/Redis evidence.

The harness models one active dashboard user per VU. Each VU performs two bounded authenticated reads and repeatedly holds the existing same-origin, cookie-only dashboard WebSocket:

- `GET /api/v1/dashboard/stats` (the server bounds recent submissions to five);
- `GET /api/v1/notifications/feed?unread_only=false&limit=10`;
- `WSS /api/v1/dashboard/realtime`, using `Origin` and the ambient `access_token` cookie only.

Response bodies are discarded. Run only against a synthetic staging tenant: those read responses can otherwise contain client or notification data even though the harness never prints or exports them. The harness performs no login, mutation, refresh, upload, delete, or PII-bearing request.

## Mandatory staging controls

Before authorizing a run:

1. Deploy the exact revision under test to a production-like staging stack. Match production proxy, application replica, worker, PostgreSQL, Redis, TLS, connection-pool, index, rate-limit, and observability configuration as closely as possible; use sanitized/synthetic data at representative volume.
2. Confirm `GET /api/v1/health/live` reports `environment: "staging"` and the expected revision. The harness verifies both again before it sends any session cookie.
3. Firewall or route the load generator to the staging origin only. The contract independently requires distinct staging and production HTTPS origins and refuses every non-staging target declaration.
4. Record an approved change/ticket reference and a unique run ID. Never reuse a manifest or run ID.
5. Provision exactly 100 or 200 least-privilege synthetic dashboard principals. Use reserved synthetic addresses in the staging identity store; do not copy real employee, traveler, client, phone, or email data.
6. Mint one different access session per VU immediately before the run. The run manifest accepts no passwords, refresh tokens, emails, names, account IDs, or extra fields. Each session must remain valid through the selected profile plus two minutes, and its total lifetime may not exceed 45 minutes.
7. Place the manifest outside the repository with OS permissions limited to the operator and k6 process. The harness refuses a manifest path beneath the declared repository root and verifies the operator-supplied SHA-256 digest before parsing it.
8. Arm staging-only monitoring for reverse-proxy upstream failures, application latency/errors/restarts, realtime connection/capacity rejection, database pool waits and slow queries, Redis latency/evictions, CPU, memory, and network saturation.

Do not enable k6 HTTP debug/header logging, shell tracing, proxy capture, or verbose request dumps:
those modes can expose the cookie header. Use one adequately sized dedicated generator for this
100/200-user gate where possible. If execution is distributed, use coordinated execution segments
with globally unique `vu.idInTest` values and run the configured profile only once; launching the
complete profile independently on multiple generators multiplies traffic and reuses authority.

## External credential manifest

Name the file exactly `dashboard-credentials.<run-id>.json`. Use canonical UTC timestamps with milliseconds. `principal_ref` is only an opaque sequence from `load-vu-001` through `load-vu-100` or `load-vu-200`.

```json
{
  "schema_version": 1,
  "run_id": "dash-load-20300102-a",
  "target_origin": "https://staging.passdetection.example",
  "generated_at": "2030-01-02T03:04:05.000Z",
  "sessions": [
    {
      "principal_ref": "load-vu-001",
      "session_cookie_value": "REDACTED_UNIQUE_ACCESS_COOKIE_VALUE",
      "issued_at": "2030-01-02T03:04:05.000Z",
      "expires_at": "2030-01-02T03:34:05.000Z"
    }
  ]
}
```

The example shows the shape only. The real array must contain exactly the selected profile count and must never be committed. Generate the file through the approved staging identity/session procedure or secret manager, not by embedding passwords in a script or k6 environment variables.

## Run from PowerShell

Set explicit values for the approved deployment. The example leaves those operational values visibly replaceable; do not paste a real cookie or manifest content into the shell history.

```powershell
$dashboardRunId = 'dash-load-20300102-a'
$dashboardManifest = "C:\PassDetection-load-secrets\dashboard-credentials.$dashboardRunId.json"
$dashboardEvidence = "C:\PassDetection-load-evidence\$dashboardRunId-summary.json"

$env:DASHBOARD_LOAD_APPROVED = 'true'
$env:DASHBOARD_LOAD_TARGET_ENVIRONMENT = 'staging'
$env:DASHBOARD_LOAD_EXPECTED_ORIGIN = 'https://staging.passdetection.example'
$env:DASHBOARD_LOAD_PRODUCTION_ORIGIN = 'https://app.passdetection.example'
$env:DASHBOARD_BASE_URL = 'https://staging.passdetection.example/api/v1'
$env:DASHBOARD_LOAD_RUN_ID = $dashboardRunId
$env:DASHBOARD_LOAD_APPROVAL_REFERENCE = 'change-20300102-17'
$env:DASHBOARD_LOAD_EXPECTED_REVISION = 'abcdef1234567'
$env:DASHBOARD_LOAD_PROFILE = '100'
$env:DASHBOARD_LOAD_MODE = 'load'
$env:DASHBOARD_LOAD_REPOSITORY_ROOT = (Resolve-Path '.').Path
$env:DASHBOARD_LOAD_CREDENTIALS_PATH = $dashboardManifest
$env:DASHBOARD_LOAD_CREDENTIALS_SHA256 = (Get-FileHash -LiteralPath $dashboardManifest -Algorithm SHA256).Hash.ToLowerInvariant()

k6 run --summary-export $dashboardEvidence load-tests/k6/dashboard-load.js
```

Run the four profiles separately, with newly minted sessions and a new run ID each time:

| Profile | `DASHBOARD_LOAD_PROFILE` | `DASHBOARD_LOAD_MODE` | Shape | Purpose |
| --- | ---: | --- | --- | --- |
| 100-user load | `100` | `load` | 2-minute ramp, 5-minute plateau, 2-minute ramp-down | Baseline target |
| 200-user load | `200` | `load` | 100 then 200 ramp, 5-minute plateau, ramp-down | Peak target |
| 100-user bounded soak | `100` | `soak` | 2-minute ramp, 20-minute plateau, 2-minute ramp-down | Stability at target |
| 200-user bounded soak | `200` | `soak` | 100 then 200 ramp, 20-minute plateau, ramp-down | Stability at peak |

The controlled pacing overrides are `DASHBOARD_SOCKET_LIFETIME_SECONDS=15..60` and
`DASHBOARD_THINK_TIME_SECONDS=1..15`. Keep the defaults for release evidence unless the
approved workload model records a justified change. The two-minute graceful drain and credential
expiry margin cover the maximum permitted in-flight iteration.

The bounded-soak modes intentionally fit the application's current short-lived access-cookie model without storing a refresh token. They do not prove one-hour, multi-hour, daily, failover, or disaster-recovery endurance. Those require a separately approved renewable-session/endurance design and longer infrastructure observation window.

## Automatic acceptance gates

Any breached k6 threshold fails the run. Do not average away a failed 200-user run with a passing 100-user run.

| Surface | Required result |
| --- | --- |
| All checks and authenticated reads | success rate greater than 99.5% |
| Dashboard stats | p95 under 750 ms; p99 under 1,500 ms |
| Notification feed | p95 under 500 ms; p99 under 1,000 ms |
| Overall HTTP errors | below 0.5% |
| Authentication/authorization | zero HTTP 401/403 and zero realtime 4401/4403 failures |
| Legitimate-user rate limiting | zero HTTP 429 responses |
| Proxy/upstream failures | zero HTTP 502/503/504 responses |
| Client connection failures | zero status-0 failures; HTTP connect p95 under 250 ms and p99 under 750 ms |
| TLS setup | p95 under 500 ms; p99 under 1,000 ms |
| Realtime | connection-and-ready success above 99.5%; ready p95 under 1,500 ms and p99 under 3,000 ms |
| Realtime protocol/disconnects | zero malformed frames; unexpected disconnect rate below 0.5% |
| Load generator | zero dropped iterations |

`dashboard_realtime_hints` is informational because this read-only run intentionally creates no application mutations. Zero hints does not fail the run and does not prove event propagation correctness; that needs a separate synthetic write-to-invalidation latency test.

## Infrastructure acceptance matrix

Correlate every observation to the run ID and plateau interval. These checks are outside k6 and remain mandatory for an enterprise capacity decision.

| Layer | Pass condition during each plateau |
| --- | --- |
| Reverse proxy/load balancer | zero upstream connect failures, resets, timeouts, or rejected WebSocket upgrades; no retry storm |
| Application replicas | zero crashes/OOM kills/restarts; no monotonic memory growth; mean CPU below 70% and peak below 85% per replica after warm-up |
| Realtime hub | active connections reach the profile target; zero capacity rejections; connection count returns to baseline after ramp-down |
| PostgreSQL | zero pool timeouts; pool utilization below 70% at p95; pool wait p95 below 50 ms; database CPU below 70%; no sustained lock queue or new slow-query outlier |
| Redis | zero evictions/reconnect storms; command p95 below 5 ms; memory and connection headroom remain above 30% |
| Network/runtime | no ephemeral-port exhaustion, file-descriptor pressure, event-loop stall, or load-generator CPU saturation |
| Recovery | error rate, active connections, database sessions, CPU, and memory return to the pre-run range within five minutes |

If staging topology or representative data volume differs materially from production, record the difference and treat capacity as unproven rather than extrapolating linearly.

## Abort, cleanup, and retained evidence

Abort immediately on any production-origin traffic, unexpected real data, security alert, 401/403 cascade, 429 response, proxy failure, database saturation, replica restart, or impact to another staging test. Stop k6, preserve metrics, and do not retry until the cause is understood.

After every run:

1. Revoke/disable all synthetic sessions through the existing staging account/session administration control and verify a sample cookie is rejected.
2. Delete the external manifest and any shell/session copy through the approved secure disposal process.
3. Retain the non-secret k6 summary, run ID, approval reference, manifest SHA-256 (never its content), deployed revision, k6 version/checksum, exact non-secret environment allowlist, generator telemetry, staging topology/config snapshot, proxy/application/database/Redis telemetry, and incident notes.
4. Mark the result `pass`, `fail`, or `invalid`. `Invalid` includes wrong revision, incomplete telemetry, load-generator saturation, topology drift, or any threshold bypass.

A 100-200-user objective is accepted only when all four live profiles pass on the same release candidate and the infrastructure matrix shows the stated headroom. Source-only CI proves that the safety and metric contract remains checked in; it proves no live capacity.
