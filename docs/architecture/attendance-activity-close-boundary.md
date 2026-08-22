# Attendance Activity Ownership and Close Boundary

## Current invariant

A canonical attendance activity is created centrally before coordinator
scanning. Only an authorized client manager, agency manager, agency admin, or
super admin can choose its name and create its server-generated UUID. Creation
is tenant- and group-scoped, serialized on the group row, bounded by the mobile
activity-capacity setting, and audited. Repeating the same normalized open name
returns the existing canonical UUID; the database partial unique index remains
the final concurrency guard.

Coordinators can list and select canonical activities for groups assigned to
them, but cannot create or rename shared activities. The legacy web and mobile
coordinator creation routes remain temporarily for compatibility, are marked
deprecated, and always fail closed after coordinator group authorization. The
native coordinator data function also fails locally before any HTTP or SQLite
write. This prevents spelling differences on coordinator devices from creating
parallel global sessions while preserving existing canonical IDs in offline
queues and cached selections.

A coordinator can finish scanning only on the current device. That action clears
the device-local activity selection and does not mutate the shared attendance
activity. Only an authorized client manager, agency manager, agency admin, or
super admin can transition the canonical shared activity from `active` to
`completed`.

## Coordinator-account closeout fence

An active activity cannot close merely because the server count looks correct.
Every currently assigned coordinator account must publish a recent count-only
checkpoint for that canonical activity. The checkpoint contains only:

- `pending_count`
- `sending_count`
- `retryable_count`
- `needs_review_count`
- `unreviewed_rejected_count`
- `oldest_pending_age_seconds`
- the server-assigned `reported_at`

The authenticated coordinator identity, canonical activity ID, and server
report time are derived by the backend. The request cannot provide another
coordinator identity. Passenger IDs, QR values or hashes, client event IDs,
error messages, installation identifiers, device labels or hashes, IP data,
and mobile session IDs are not accepted or persisted.

There is one durable last-report row per canonical activity and coordinator
account. A report is valid only when it is no more than 120 seconds old and was
published after both the activity validity boundary and that coordinator's
latest active assignment. Each active assignment is classified as `ready`,
`missing`, `stale`, or `blocked`. `ready` requires a recent report with every
count equal to zero. No active assignments is not affirmative evidence and
therefore fails closed.

The native and PWA reporters publish immediately when the reconciliation
surface is active, every 30 seconds while visible, after manual synchronization,
and immediately after a durable scanner enqueue creates or re-observes unresolved
local work. The enqueue-triggered request is best effort and runs only after the
local transaction commits, so reporting failure cannot roll back the saved scan
or make the enqueue caller treat that durable write as failed. They bind the
local queue read to the same authenticated
account context used to start the request. An account change during collection
aborts the report. Per-account/activity publisher lanes serialize requests,
coalesce repeated interval/manual/remount/enqueue triggers, and recompute one
final snapshot after an in-flight request. The PWA additionally uses the Web
Locks API when available to serialize the publisher lane across tabs.

Native rejected queue records deliberately have their payload erased. Because
their activity ID can no longer be recovered, every unreviewed rejected
attendance row for the trip is conservatively counted against each active
activity checkpoint. This can overblock but cannot fabricate a clear report.

## Manager close and exception protocol

The close transition is tenant- and group-scoped and uses this lock order:

1. Lock the tenant-owned group row.
2. Lock the canonical attendance activity row exclusively.
3. Read the current active coordinator assignments and their checkpoints.
4. Close only when the status is ready, or when the manager supplied a valid
   audited exception.

Coordinator checkpoint publication takes a shared lock on the canonical
activity and never requests the group lock afterward. Scan ingestion uses the
same compatible shared activity lock. Assignment replacement and coordinator
account deactivation lock affected group rows before changing active
membership. Consequently, concurrent scans and checkpoints proceed together;
manager close serializes behind already-started work; and assignment-set
changes cannot silently alter the participant snapshot during close.

Web and native manager flows show the aggregate status and per-coordinator
count-only state. They refresh authoritative server counts and checkpoint
status immediately before confirmation. Missing, stale, nonzero, or
zero-assignment evidence returns a structured 409 and does not mutate the
activity.

An authorized manager can make an explicit exception with a whitespace-
normalized reason of 10 to 500 characters. The UI requires strong two-step
destructive confirmation and warns that the reason must contain operational
information only: not passenger names, QR values, passport details, or other
personal data. The durable close audit stores the reason, whether the exception
was used, the aggregate snapshot, and count-only coordinator states. It does
not store local queue records or device data.

An already-completed close replay remains idempotent and does not invent or
re-evaluate evidence for a second state transition. A completed activity stops
new camera capture.

Queued scans are not discarded by closure. A replay against a completed
activity is accepted only when it carries a capture timestamp at or before the
server's `completed_at` boundary. The web replay path additionally requires the
request to identify itself as an offline replay. Idempotency and passenger
deduplication rules still apply.

## Explicit trust and deployment limitation

`scanned_at` is currently supplied by the coordinator device. The server
validates timezone, future-time bounds, the activity window, tenant/group/QR
scope, and idempotency, but it does not have cryptographic proof that a device
created an offline event before closure. A malicious authorized coordinator
could create a new event after closure and backdate it. The current boundary is
therefore strong against accidental fresh capture and unauthorized global
closure, but it is not a cryptographic non-repudiation boundary against a
malicious coordinator controlling their client.

The checkpoint is intentionally coordinator-account-level, not physical-device
level. Mobile permits multiple active installations for one account, and the
same account can also have a PWA session. The latest accepted report for the
coordinator account is authoritative so retired or lost installations do not
become permanent ghost blockers. During final reconciliation, operations must
use one active scanning runtime per coordinator account and reconcile any other
runtime before the account's last report. Cross-tab Web Locks prevent overlap,
but cannot merge two tabs' independent queues into device-fleet proof.

The post-commit enqueue trigger minimizes the ordinary online race between a
recent zero report and newly queued work, but it is not atomic with the manager's
server-side close transaction. An offline runtime cannot notify the server, and
another device may close during network transit. The two-minute report TTL,
single-runtime operating rule, and audited exception path bound this operational
risk; only the device-registration protocol below can remove it cryptographically.

The backend also cannot prove that a malicious, already-authorized client
reported truthful aggregate counts. Authentication, strict schemas, account-
switch fencing, server time, and durable audit protect the accidental and
cross-account boundaries; they do not create hardware-backed non-repudiation.

Use the terms "coordinator checkpoints" or "latest coordinator-account report."
Do not describe global close as "fleet proven clear," "all devices clear," or
cryptographic proof that no unsent scan exists anywhere.

## Protocol required to remove the limitation

Hard enforcement requires a coordinated backend, database, and mobile protocol,
not another client-side timestamp check:

1. Register an attested, hardware-backed signing identity and monotonic counter
   for each authorized coordinator installation.
2. Issue a server-signed activity epoch/challenge and periodically anchor each
   device's signed scan hash chain and highest monotonic counter on the server.
3. Track per-device queue states (`pending`, `sending`, `retryable`,
   `needs_review`, and terminal) against that activity epoch, including an
   explicit retirement/revocation lifecycle so lost devices cannot block
   forever.
4. Require every assigned device to publish a signed final checkpoint before a
   manager can close, unless the manager records an explicit audited override.
5. Accept post-close replay only when its signed counter/hash position is
   provably at or below the device checkpoint included in the close decision.

A device signature without an attested monotonic counter or server-anchored
checkpoint is insufficient: the device could simply sign a newly created,
backdated event after closure.
