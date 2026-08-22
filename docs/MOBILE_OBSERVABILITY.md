# Group Companion mobile observability contract

Status: crash/ANR implementation complete; production and SLO proof pending

## Purpose

Observability must make a failed or slow fleet diagnosable without becoming a
second database of passenger, account, document, trip, or credential data. The
mobile SDK is therefore configured as a crash-and-hang sensor plus a small
fixed-schema SLO metric channel. Generic performance tracing remains disabled.

## Collection boundary

Production release builds initialize the pinned React Native Sentry SDK only
when `EXPO_PUBLIC_SENTRY_DSN` is present. Production validation fails closed if
the DSN is absent or malformed. The DSN is a public ingestion identifier; it is
not a secret.

The source-map upload values are build-only:

- `SENTRY_ORG`
- `SENTRY_PROJECT`
- `SENTRY_AUTH_TOKEN`

`SENTRY_AUTH_TOKEN` must be stored as a protected EAS/build secret. It is never
placed in an `EXPO_PUBLIC_*` value, Expo `extra`, source control, or the app
bundle. Production validation checks that all three values exist, but never
returns or prints the token.

The Metro/Sentry integration emits deterministic debug IDs. Production Android
and iOS builds must upload matching Hermes/native source maps during the signed
build. A successful build alone is not evidence of symbolication; the release
gate includes a controlled test crash and inspection of the resulting issue.

## Privacy controls

The SDK configuration explicitly sets all of the following:

- default PII collection off;
- IP inference off;
- breadcrumbs disabled and bounded at zero;
- screenshots and view-hierarchy attachments off;
- session replay rates zero;
- console breadcrumbs and SDK log capture off;
- failed-request capture off;
- user-interaction tracing off;
- distributed trace propagation targets empty;
- performance traces and profiles sampled at zero;
- queues and offline envelopes bounded.

JavaScript error events pass through a fail-closed allowlist. If the scrubber
cannot safely project an event, the event is dropped. The allowlist retains only
release/environment metadata, bounded crash/thread frames, native/source-map
debug identifiers, a small non-identifying device/runtime context, and the
fixed `diagnostic_code` and `recovery_attempt` tags. It removes:

- exception messages and mechanism data;
- request URLs, headers, bodies, and query strings;
- users, account/trip/passenger/document identifiers, email, and phone values;
- breadcrumbs, arbitrary tags, extra data, route transactions, and SQL;
- local absolute paths, source context, frame variables, and device names or
unique identifiers.

## Fixed-schema SLO metrics

Metric envelopes use a second fail-closed allowlist. Callers select a compile-
time metric key rather than supplying a name. The final send hook independently
rejects unknown names, wrong metric types, negative/non-finite/over-cap values,
unknown attributes, and unknown attribute values. Arbitrary strings cannot
become metric names, tags, or attributes.

Current measurements are:

- `gc.mobile.bootstrap_to_interactive.duration`;
- `gc.mobile.sync.duration` and `gc.mobile.sync.run`;
- `gc.mobile.background_sync.duration` and
  `gc.mobile.background.expiration`;
- `gc.mobile.realtime.reconnect` and
  `gc.mobile.realtime.reconnect_delay`;
- `gc.mobile.realtime.connection` and
  `gc.mobile.realtime.connection.duration`;
- `gc.mobile.queue.depth` for synchronization, attendance, and document work;
- `gc.mobile.attendance.needs_review.depth`;
- `gc.mobile.attendance.acknowledgement_latency`,
  `gc.mobile.attendance.retry`, and
  `gc.mobile.attendance.refresh_recovery`;
- `gc.mobile.attendance.discarded` (count only, explicit destructive action);
- `gc.mobile.attendance.scan.local_result` for the completed local durable-
  queue decision;
- `gc.mobile.attendance.scan.confirmed` for server `accepted` versus
  idempotent `already_applied` rows;
- `gc.mobile.attendance.queue.oldest_pending_age` and
  `gc.mobile.attendance.delivery.batch_size`;
- `gc.mobile.attendance.delivery.failure`, with request failures reduced to a
  fixed operational class;
- `gc.mobile.attendance.scan.terminal_rejection`, whose reason is projected
  onto a fixed safe category rather than retaining a server or local error;
- `gc.mobile.attendance.camera_to_local_queue` and
  `gc.mobile.attendance.queue_to_confirmation`;
- `gc.mobile.attendance.reconciliation`, which records only a fixed
  count-assessment outcome;
- `gc.mobile.authentication.lock` and
  `gc.mobile.authentication.quarantine.depth`;
- `gc.mobile.storage.maintenance.duration`,
  `gc.mobile.storage.maintenance.run`, and
  `gc.mobile.storage.maintenance.changed_rows`.

Only these attributes are accepted:

- `outcome`: `success`, `partial`, `failure`, `cancelled`, `timeout`, or
  `offline`;
- `trigger`: `startup`, `foreground`, `background`, `realtime`, `push`,
  `manual`, or `mutation`;
- `queue`: `sync`, `attendance`, or `documents`;
- `attendance_result`: `queued`, `already_queued`, `already_confirmed`,
  `needs_review`, `previously_rejected`, `capacity_reached`, `accepted`, or
  `already_applied`;
- `terminal_reason`: `authorization`, `assignment`, `activity_state`,
  `timestamp`, `idempotency`, `qr_evidence`, `local_payload`,
  `local_expired`, `client_request`, or `other`;
- `reconciliation`: `ready`, `count_mismatch`, `pending_queue`,
  `needs_review`, or `unverifiable`;
- `delivery_failure`: `rate_limited`, `server_error`, `timeout`, `network`, or
  `other`.

Attendance and authentication helpers accept counts, durations, and these
fixed enums only. They do not accept or forward passenger, coordinator,
account, trip, activity, queue-row, client-event, QR, device, URL, or raw-error
values. Terminal server codes are classified locally and the original code is
discarded before the metric envelope is built.

The bootstrap metric begins when the observability module loads and ends after
the existing application-session bootstrap resolves. It is therefore a stable
"JavaScript bootstrap to interactive shell" boundary, not a substitute for
native process-start, first-frame, or fully-drawn measurements. Native launch
and frame metrics remain device/performance-test evidence.

Native process crashes and ANRs are serialized by the native SDK so they can
survive termination. They use the same no-PII, no-breadcrumb, no-attachment
configuration. Production acceptance must inspect raw native envelopes because
the JavaScript `beforeSend` hook cannot post-process a process that has already
terminated.

## Operational acceptance

Before enabling a broad rollout, complete all of these gates in a non-production
project containing no real passenger data:

1. Build signed Android and iOS release artifacts with protected source-map
   credentials.
2. Trigger one controlled JavaScript render failure on each platform and prove
   that source filenames and line numbers symbolicate.
3. Trigger an Android native test crash and a controlled Android ANR; verify the
   next-launch upload and grouping.
4. Trigger an iOS native test crash, watchdog termination, and app hang; verify
   next-launch upload and grouping.
5. Export the raw envelopes and confirm that no token, request URL, name, phone,
   email, passenger/document/trip/account identifier, local path, screenshot,
   view hierarchy, console line, or breadcrumb appears.
6. Test airplane mode, a full 20-envelope cache, app restart, and recovery;
   confirm bounded storage and eventual delivery without blocking startup.
7. Configure release alerts for crash-free sessions below 99.95%, Android ANR
   rate at or above 0.1%, a new regression issue, and an observability-ingestion
   outage.
8. Run the alert drill and record ownership, acknowledgement, escalation, and
   rollback timestamps.

The current metrics establish startup/sync/background/reconnect distributions,
local and server attendance outcomes, camera-to-durable-queue and
queue-to-confirmation latency, retry/recovery counts, queue age/depth, safe
terminal-reason classes, authentication fencing, and count-only reconciliation
assessments. A `reconciliation=ready` envelope is an observation from one app
assessment, not authoritative proof that an entire event or physical-device
fleet is clear. The metrics also do not by themselves prove dashboard-visible
freshness, document-open latency, production capacity, paging delivery, or
on-call response. Those require the external staging/device/load/alert gates in
`MOBILE_ATTENDANCE_EVENT_RUNBOOK.md` and `load-tests/k6/MOBILE_LOAD_TESTING.md`.
Generic tracing remains disabled until it has an equally strict privacy
contract.
