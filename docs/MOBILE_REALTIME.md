# Mobile realtime freshness contract

## Purpose and correctness boundary

The realtime channel reduces foreground dashboard-to-phone latency. It is not a second data plane and it never applies data directly to SQLite or React Query.

1. A dashboard/mobile write commits its ordinary PostgreSQL transaction, including the append-only `mobile_sync_changes` row.
2. A SQLAlchemy post-commit observer submits one compact hint to a bounded process queue. Redis is never awaited by, and can never roll back, the database transaction.
3. One Redis subscriber per API worker receives process-wide hints and fans them out through a tenant-and-trip index. There is no Redis connection per phone.
4. The foreground phone coalesces duplicate, reordered, and bursty hints into the existing `sync-trigger` coordinator.
5. Cursor sync reads the durable journal, validates the live access generation, and atomically publishes authoritative local state. Missed Redis messages are recovered by reconnect, foreground, push, and periodic cursor reconciliation.

Only this client hint shape is allowed:

```json
{"type":"sync_hint","trip_id":"<uuid>","cursor":123,"invalidation":"documents"}
```

No passenger name, phone, email, document/file identifier, document body, notification text, token, account identifier, agency identifier, or journal payload is sent to a phone. The internal Redis envelope adds only the agency UUID needed for server-side tenant routing. Redis and WebSocket hints are lossy by design.

## Authentication and live authorization

- The native Android/iOS WebSocket sends the ordinary short-lived mobile bearer in the `Authorization` header. Tokens are rejected in all query strings, so they do not enter URLs, access logs, referrers, or analytics.
- The server validates JWT issuer, audience, signature, expiry, device session status/generation, account identity, role status, tenant, trip lifecycle, group access, and passenger/manager/coordinator assignment before accepting a connection.
- A short database transaction refreshes that authorization on the configured interval. Session revocation closes the socket; trip revocation or assignment removal deletes the trip from the process fanout index.
- Browser Origins, when present, must match `ALLOWED_ORIGINS` or the API origin. Native clients normally omit Origin and rely on the header that browser WebSocket JavaScript cannot set.
- Pre-authentication database work, deployment-wide connections, per-process connections, per-session connections, subscribed trips, pending trips, send time, message size, idle time, and heartbeat cadence are bounded. Uvicorn rejects frames above 1 KiB and retains at most four incoming frames before the application applies its stricter 128-byte client contract. Excess handshakes are rejected before any JWT/session query; a slow consumer is disconnected and recovers through its durable cursor.

## Deployment-wide admission and crash recovery

`MOBILE_REALTIME_MAX_CONNECTIONS` and `MOBILE_REALTIME_MAX_AUTHENTICATING_CONNECTIONS` are last-resort safety rails for one API process. They are not capacity claims and must not be multiplied by the number of Gunicorn workers.

Every admitted socket and every in-progress authorization now owns an atomic Redis sorted-set lease. `MOBILE_REALTIME_GLOBAL_MAX_CONNECTIONS` (default 1,000) and `MOBILE_REALTIME_GLOBAL_MAX_AUTHENTICATING_CONNECTIONS` (default 32) are therefore shared across all API workers and replicas using the same environment namespace. Acquisition removes expired leases and checks/inserts the new lease in one Lua operation, so concurrent replicas cannot over-admit. Normal disconnects release immediately. A killed process cannot release, so its ownership expires after `MOBILE_REALTIME_LEASE_TTL_SECONDS`; another admission reclaims the expired slot atomically.

Active ownership is renewed every `MOBILE_REALTIME_LEASE_RENEW_INTERVAL_SECONDS`, and settings require the TTL to cover at least three renewal intervals. If Redis renewal fails or an active lease has disappeared, the affected process fails closed: it stops accepting sockets, disconnects its active clients with retryable code 1013, clears authorization reservations, fails readiness when Redis is required, and relies on durable cursor reconciliation after reconnect. This prevents a partitioned process from continuing to serve sockets it can no longer count globally.

The default 1,000-connection admission ceiling is a guarded initial rollout limit, not evidence of 1,000-user capacity. Raising it requires the production-like load gate below. The future 10,000 target should normally be spread across measured API replicas while retaining one deployment-wide Redis ceiling; do not set 10,000 independently on every replica.

## Required reverse-proxy behavior

The repository Nginx configuration has an exact `/api/v1/mobile/realtime` location before generic API locations. Preserve these properties in any Cloudflare, load balancer, ingress, or replacement proxy:

- HTTP/1.1 upstream and `Upgrade`/`Connection` forwarding;
- `Authorization` forwarding without logging its value;
- buffering and request buffering disabled;
- an idle/read timeout greater than `MOBILE_REALTIME_IDLE_TIMEOUT_SECONDS` (the repository uses 90 seconds for a 65-second application timeout);
- TLS at the public edge (`wss://` outside loopback development);
- no URL-token rewrite and no caching;
- enough open-file and connection capacity for both the client and upstream descriptor for every socket.

The bundled Nginx uses `worker_connections 32768`, `worker_rlimit_nofile 65536`, and Compose `nofile` limits for Nginx and the API. The host/container runtime must be checked after deployment because platform-level limits can still be lower. Cloudflare/ingress WebSocket support, connection duration, and plan-specific concurrent-connection ceilings are external gates.

## Rollout and failure modes

Keep both flags off until the proxy and Redis checks pass:

```text
MOBILE_REALTIME_ENABLED=false
EXPO_PUBLIC_REALTIME_ENABLED=false
```

Enable the backend first in one environment, verify `/api/v1/health/ready`, then enable the mobile build flag. `MOBILE_REALTIME_REQUIRE_REDIS=true` makes an initial Redis failure fail API startup and makes a runtime outage fail readiness. Setting it to `false` is an explicit cursor-only degradation policy: readiness stays serviceable but reports `mobile_realtime=degraded_cursor_fallback`, the WebSocket refuses new connections, and foreground/push/periodic cursor sync continues. It must never report instant freshness while Redis is unavailable.

Operational alerts should fire on required-unreachable status, sustained cursor-only degradation, dropped post-commit hints, invalid Redis frames, authentication/connection-cap rejection, slow-consumer disconnects, Redis subscriber/publisher failures, and reconnect storms. These non-sensitive process counters are registered under the existing protected metrics snapshot as `shared.mobile_realtime`. Hint drops do not imply data loss; they do imply freshness-SLO risk.

Also alert on `lease_backend_failures`, `lease_renewal_failures`, and `lease_forced_disconnects`. Compare `leased_connections` with `connections`; a sustained mismatch outside a brief admission transition is unhealthy.

## External 10k concurrent-user release gate

The unit/integration suite proves scoping, revocation, bounded coalescing, post-commit independence, and reconnect policy. It does not prove production capacity. Before claiming support for 10,000 simultaneous users, run a production-like distributed WebSocket soak through the real CDN/proxy with realistic dashboard writes and cursor API traffic.

Required gate:

1. Ramp 1k -> 5k -> 10k authenticated foreground sockets, including a realistic shared-NAT distribution and at least one connection per active session. For distributed k6 execution, use coordinated execution segments or a managed coordinator with globally unique VU identities; never start the complete 5k/10k profile independently on multiple generators.
2. Hold 10k for at least 60 minutes; run a 24-hour soak before general release.
3. Publish mixed itinerary, document, announcement, roster, attendance, and access-revocation journal events while also exercising push and reconnect recovery.
4. Inject Redis restart/network loss, one API-worker restart, Nginx reload, token expiry/refresh, mobile offline/online transitions, duplicated/reordered hints, and a slow-consumer cohort.
5. Verify dashboard commit -> visible phone state p95 <= 2 seconds and p99 <= 5 seconds; reconnect -> consistent p95 <= 5 seconds; no cross-tenant/cross-trip delivery; no post-commit write failure due to Redis; no unbounded queue/memory growth; API/Redis/DB error rate < 1%; and cursor convergence after every injected hint loss.
6. Record API-worker CPU/RSS/event-loop lag, Redis pub/sub lag/clients/output buffers, PostgreSQL authorization-query load, Nginx active connections/file descriptors, OS `nofile`, CDN disconnects, mobile reconnect rate, hint drop counters, sync latency, and battery/network impact on representative low/mid Android and current iOS devices.
7. Size API workers/replicas, the process-local safety rails, and `MOBILE_REALTIME_GLOBAL_MAX_CONNECTIONS` from measured headroom, not from a configured theoretical maximum. A release fails if any infrastructure limit, mobile device test, or 10k soak is missing.

This external load/device/CDN gate remains unverified until executed in the target environment.
