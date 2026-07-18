# Public upload rate-limit policy

## Why this is separate from the staff API limit

The public passport workflow has two very different traffic shapes:

1. A delegate sends one large multipart upload.
2. The browser polls status and reads stored images while extraction runs.

The previous Nginx policy keyed the initial upload only by source IP at
`10 requests/minute` with a burst of `5`. Seven or more delegates sharing an
office, hotel, mobile carrier, or airport NAT could therefore receive a proxy
failure even though every delegate had a distinct secure upload link.

Public-upload requests now pass through both a per-session guard and a
per-network aggregate guard. The generic authenticated/staff API remains on its
own policy.

## Stable upload identity

The browser sends `X-Upload-Session-ID`:

- Public link bootstrap, qualifier selection, and fixed-enum flow telemetry:
  one opaque per-tab browser session id, retained in `sessionStorage` for
  refresh recovery.
- Initial multipart POST and every status, scan-again, stored-image, discard,
  and final client-submit call: the existing high-entropy
  `upload_idempotency_key`, retained with the durable submission id in the
  tab's recovery record.

The initial route requires the header and compares it exactly with the multipart
idempotency key. Every follow-up route independently compares the header with
the credential persisted on that submission. The public submission UUID is
routing data only and never proves ownership. Stored-image previews are fetched
as authenticated blobs because browser image tags cannot attach the credential
header, and public upload/status/rescan JSON does not contain redundant
presigned document URLs. Bootstrap session ids must be 8-128 characters and
upload recovery credentials must be 32-128 characters, both from
`A-Z a-z 0-9 . _ : -`.

Upload-link bearer tokens are never limiter keys. The app HMAC-hashes client IPs
and session ids with `APP_SECRET_KEY` before storing Redis keys, and limiter
warnings log only exception types.

## Default limits

| Layer | Traffic | Per session | Per source network |
| --- | --- | ---: | ---: |
| Nginx | Link bootstrap/qualifier choice/telemetry | 30/minute, burst 10 | 600/minute, burst 300 |
| App/Redis | Link bootstrap/qualifier choice/telemetry | 30/minute | 600/minute |
| Nginx | Initial upload | 6/minute, burst 5 | 120/minute, burst 100 |
| App/Redis | Initial upload | 6/minute | 180/minute |
| Nginx | Status/image/scan/discard/client-submit | 120/minute, burst 20 | 100/second, burst 200 |
| App/Redis | Status/image/scan/discard/client-submit | 120/minute | 6000/minute |
| Nginx | Other `/api/` traffic | n/a | 30/second, burst 20 |
| App/Redis | Other `/api/` traffic | n/a | 60/minute |

The per-session check runs before the aggregate app check so one misbehaving
delegate cannot consume the entire shared-NAT app budget. Rotating session ids
still reaches the aggregate guard. The Nginx initial burst admits at least 100
legitimate delegates arriving together while preserving a sustained network
cap.

The app settings are:

```dotenv
PUBLIC_UPLOAD_BOOTSTRAP_SESSION_RATE_LIMIT_PER_MINUTE=30
PUBLIC_UPLOAD_BOOTSTRAP_AGGREGATE_RATE_LIMIT_PER_MINUTE=600
PUBLIC_UPLOAD_SESSION_RATE_LIMIT_PER_MINUTE=6
PUBLIC_UPLOAD_AGGREGATE_RATE_LIMIT_PER_MINUTE=180
PUBLIC_UPLOAD_FOLLOWUP_SESSION_RATE_LIMIT_PER_MINUTE=120
PUBLIC_UPLOAD_FOLLOWUP_AGGREGATE_RATE_LIMIT_PER_MINUTE=6000
PUBLIC_UPLOAD_RATE_LIMIT_REQUIRE_REDIS=true
```

Nginx rates are static in `nginx/nginx.conf`; keep them coordinated with the app
settings when tuning.

The initial multipart route has a proxy-level `35M` body limit. This bounds the
three application-validated 10 MiB images (front, back, and optional Visa
Photo) plus multipart overhead. Public bootstrap/telemetry requests are capped
at `64K`, and public post-upload JSON follow-ups are capped at `128K`. The
application still enforces each individual image's size, decoded-pixel,
media-type, and content checks.

The ordinary `/api/` envelope is `16M`; it no longer inherits the historical
server-wide `512M` ceiling. A `512M` exception exists only for the exact
authenticated passport archive-import and multi-document distribution/rename
routes that require it. Those exceptions retain the staff API rate limiter.

## Failure contract

Nginx limit responses are HTTP 429 JSON with `Cache-Control: no-store`,
`Retry-After`, `X-Request-ID`, and one of:

- `PROXY_UPLOAD_BOOTSTRAP_RATE_LIMITED`
- `PROXY_UPLOAD_RATE_LIMITED`
- `PROXY_UPLOAD_FOLLOWUP_RATE_LIMITED`
- `PROXY_RATE_LIMITED`

The sanitized Nginx access log includes `limit_req_status`, `upstream_status`,
and `request_time`. This lets the production collector distinguish an Nginx
rejection (`limit_req_status=REJECTED`) from an application/Gemini response
without logging the upload-link token or query string. Alert/dashboard
provisioning remains an external deployment step. Built-in `limit_req`
messages contain the original bearer-token URI, so their log level is
deliberately kept below the configured Nginx error-log threshold; use the
sanitized access record for rate-limit diagnosis. Nginx cannot redact the
request line in its error-log format, so the TLS virtual host discards its
request-context error stream. Preserve the sanitized access log and backend
metrics in the production collector; do not re-enable proxy error logging until
public credentials have moved out of request URLs or an independently tested
redaction layer is present.

App responses use:

- `UPLOAD_SESSION_ID_REQUIRED` (400)
- `UPLOAD_SESSION_ID_INVALID` (400)
- `UPLOAD_SESSION_ID_MISMATCH` (400)
- `UPLOAD_BOOTSTRAP_SESSION_RATE_LIMITED` (429)
- `UPLOAD_BOOTSTRAP_AGGREGATE_RATE_LIMITED` (429)
- `UPLOAD_SESSION_RATE_LIMITED` (429)
- `UPLOAD_AGGREGATE_RATE_LIMITED` (429)
- `RATE_LIMIT_SERVICE_UNAVAILABLE` (503)
- `APP_RATE_LIMITED` (429)

Public-upload counters fail closed with 503 if Redis cannot enforce the shared
policy. Error CORS headers are reflected only for an exact configured
`ALLOWED_ORIGINS` entry.

`OPTIONS` preflight requests bypass limiter enforcement and never require an
upload session id; the actual request remains fully enforced.

The public telemetry endpoint accepts only server-owned event/reason enums and
stores aggregate counts. It does not accept identifiers, free text, image
statistics, user-agent strings, or traveller data. Invalid, expired, or
inactive upload links receive the same empty 204 response without recording,
which avoids exposing a bearer-link validity oracle.

## Proxy trust boundary

The app intentionally ignores `X-Forwarded-For` and uses Nginx's overwritten
`X-Real-IP`. The backend port must not be internet-accessible. If another trusted
load balancer is placed in front of Nginx, configure its real-IP chain at Nginx
and keep Nginx as the only caller allowed to reach the backend service.

## Deployment and checks

Run these from the host PowerShell terminal in the repository root, not inside a
running container:

```powershell
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
python scripts/verify_compose_runtime.py
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build backend frontend nginx
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python -m unittest tests.unit.presentation.test_rate_limit_middleware -v
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec nginx nginx -t
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec nginx nginx -s reload
```

After deployment, verify one initial request without the header returns the
structured 400, 100 upload-page bootstrap requests and 100 qualifier choices
from one test source IP are admitted, 100 unique initial-upload sessions are
admitted, the seventh request for one initial session returns 429, and the
181st rotating initial session reaches the app aggregate 429. Do not put
upload-link tokens, raw session ids, or passport data into load-test result
names or logs.

If rollback is necessary, roll back the backend, frontend, and Nginx changes as
one unit. Removing only the client header while retaining the required app guard
will make initial uploads fail safely with `UPLOAD_SESSION_ID_REQUIRED`.
