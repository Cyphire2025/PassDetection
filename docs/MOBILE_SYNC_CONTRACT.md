# Group Companion sync and capacity contract

Status: additive backend contract, implemented during the enterprise mobile hardening work

## Guarantees

- Every mobile sync read remains scoped by the authenticated agency, authorized group-access row, group, access generation, role audience, and passenger identity where applicable.
- Change pages are ordered by the monotonic journal sequence and contain at most 500 entries.
- Resource endpoints return metadata and paginated projections. Document bytes are never embedded in a manifest, change page, or snapshot descriptor; they remain behind the existing per-document authorization and content routes.
- A group may contain at most `MOBILE_MAX_GROUP_PASSENGERS` passenger records. The default is 10,000. The API enforces the same value for public uploads, bulk Excel additions, and enabling a group in GC App.
- A normal incremental pass may contain at most `MOBILE_SYNC_MAX_INCREMENTAL_CHANGES` deliverable entries. The default is 10,000.

## Normal incremental synchronization

1. Read `GET /api/v1/mobile/trips/{group_id}/manifest`.
2. Starting from the durable local cursor, read `GET /api/v1/mobile/sync/changes?trip_id={group_id}&cursor={cursor}&limit=500` until `has_more` is false.
3. Apply resource-version changes to local staging or the current projection.
4. Atomically commit metadata, versions, and the returned cursor before starting optional encrypted document downloads.
5. Post the committed versions and cursor to `POST /api/v1/mobile/sync/ack`.

The server can advance `next_cursor` over expired or permanently invisible journal gaps. A client must reject a page whose cursor does not advance while `has_more` is true.

## Oversized backlog and snapshot rebase

When more than the configured incremental limit is visible after a device cursor, `/sync/changes` returns one schema-compatible checkpoint:

- `entity_type`: `snapshot_rebase`
- `sequence` and `next_cursor`: the scoped journal high-water cursor
- `has_more`: `false`
- `payload.resource_path`: the authorized snapshot descriptor route

The checkpoint is an HTTP 200 response and preserves the existing page and
change schemas exactly:

```json
{
  "changes": [
    {
      "sequence": 12345,
      "group_id": "00000000-0000-0000-0000-000000000000",
      "entity_type": "snapshot_rebase",
      "entity_id": null,
      "operation": "upsert",
      "version": 7,
      "occurred_at": "2026-08-19T12:00:00Z",
      "payload": {
        "resource_path": "/api/v1/mobile/sync/snapshot?trip_id=00000000-0000-0000-0000-000000000000"
      }
    }
  ],
  "next_cursor": 12345,
  "has_more": false
}
```

`sequence` and `next_cursor` are the same scoped high-water value. The client
must not commit that cursor merely because it received the event: it must first
finish either its normal authoritative-version reconciliation (legacy behavior)
or the explicit rebase (preferred behavior below).

This avoids repeatedly downloading the same first 10,000 entries without committing progress. It is intentionally compatible with the already-released strict response schema. Current clients still reconcile authoritative manifest versions; updated clients should explicitly perform the full rebase below.

The snapshot descriptor has this exact top-level shape. It is metadata only;
none of the resource paths is inlined or fetched by the descriptor request.

```json
{
  "strategy": "full_rebase",
  "trip": {
    "id": "00000000-0000-0000-0000-000000000000",
    "name": "Trip name",
    "destination": null,
    "travel_date": null,
    "return_date": null,
    "role": "passenger",
    "access_generation": 3,
    "itinerary_version": 2,
    "common_document_version": 4,
    "announcement_version": 5
  },
  "baseline_cursor": 12345,
  "access_generation": 3,
  "server_time": "2026-08-19T12:00:01Z",
  "access_expires_at": null,
  "versions": {
    "manifest": 7,
    "itinerary": 2,
    "common_documents": 4,
    "personal_documents": 8,
    "announcements": 5,
    "rooming": 2,
    "meals": 1,
    "qr": 3,
    "readiness": 0,
    "roster": 0
  },
  "resources": {
    "manifest": "/api/v1/mobile/trips/{group_id}/manifest",
    "itinerary": "/api/v1/mobile/trips/{group_id}/itinerary",
    "announcements": "/api/v1/mobile/trips/{group_id}/announcements",
    "common_documents": "/api/v1/mobile/trips/{group_id}/common-documents",
    "personal_documents": "/api/v1/mobile/trips/{group_id}/documents",
    "room": "/api/v1/mobile/trips/{group_id}/room",
    "meals": "/api/v1/mobile/trips/{group_id}/meals",
    "qr": "/api/v1/mobile/trips/{group_id}/qr",
    "readiness": null,
    "roster": null,
    "attendance_sessions": null,
    "sync_changes": "/api/v1/mobile/sync/changes?trip_id={group_id}",
    "acknowledge": "/api/v1/mobile/sync/ack"
  },
  "resource_counts": {
    "announcements": 3,
    "common_documents": 6,
    "personal_documents": 4,
    "roster": null,
    "attendance_sessions": null
  },
  "max_incremental_changes": 10000,
  "max_group_passengers": 10000,
  "max_attendance_sessions_per_group": 10000
}
```

The example is for a passenger. A client manager instead receives non-null
`readiness`, manager `roster`, and manager `attendance_sessions` paths. A
coordinator receives coordinator `roster` and `attendance_sessions` paths.
Unauthorized role projections are always `null`; clients must not synthesize
paths for them.

1. Read `GET /api/v1/mobile/sync/snapshot?trip_id={group_id}`.
2. Verify the returned trip, role, access generation, expiry, and role-specific resource map against the active account/session context.
3. Fetch every applicable non-null metadata resource into a new local staging generation. Follow `next_cursor` until null on paged endpoints; use the existing server-bounded singleton/itinerary endpoints once. The final unique item count must equal the exact role-scoped `resource_counts` value and must not exceed its advertised capacity. A zero authoritative version or an existing optional-resource 404 means "stage no value/rows," never "copy the old generation." Do not fetch document content as part of this phase.
4. Re-read the snapshot descriptor. If its trip/role, access generation, versions, or exact resource counts differ, discard the staging generation and retry with jittered backoff.
5. Atomically promote the staging generation with the **second** descriptor's `baseline_cursor`, access generation, expiry, and versions. Do not substitute the nested manifest's `sync_cursor`.
6. Acknowledge that exact committed baseline through the supplied `acknowledge` path, then resume normal deltas from the committed `baseline_cursor`.
7. Hydrate encrypted document content from a separate durable, bounded queue after the metadata projection is visible.

The server captures the snapshot journal cursor before it derives resource versions. A concurrent dashboard commit can therefore make the cursor lag the versions, which causes a harmless repeat delta; the descriptor cannot advance the cursor past a resource mutation that was not represented in the returned versions.

The server read order is: authorize the trip and role, capture the scoped journal
high-water, derive authoritative versions, then serialize the descriptor. Within
one access generation, a client must reject an inconsistent descriptor (wrong
trip/role, mismatched duplicate access-generation fields, or a baseline behind
the checkpoint event) and retry; it must never silently regress a committed
cursor. An access-generation change is an authorization boundary and requires
purging the old trip projection before rebuilding it.

There is no special snapshot error envelope. Missing/expired credentials use the
existing 401 error contract; a disabled, revoked, expired, cross-tenant, wrong
role, or otherwise unavailable trip returns the existing 403
`AUTHORIZATION_ERROR` contract. Invalid UUID/query values return FastAPI's
existing 422 validation response. A transient 5xx/network failure leaves the old
projection and cursor untouched and is retried with bounded exponential backoff
and jitter. A checkpoint itself is not an error and must not be retried as an
ordinary delta page.

`POST /sync/ack` retains its existing contract. It returns 409 with `Sync state
changed; refresh and retry` when the access generation is stale, the cursor is
ahead of the current scoped journal, or the committed versions are no longer
current. A version-only race leaves a valid older local generation in place and
should trigger an immediate delta pass; an authorization/access-generation
change must follow the existing purge-and-reauthorize path.

## Creation-time capacity behavior

The per-group passenger quota is an operational contract, not a client memory guard:

- public uploads take a short tenant/group row lock after object storage writes, re-check the idempotency key, and validate capacity before inserting;
- losing idempotent retries clean up only their own attempted objects and do not consume another slot;
- Excel imports already serialize their merge/write section on the same group row and validate only the number of genuinely new passengers, so update-only imports remain available at the limit;
- enabling an existing dashboard group in GC App validates its current passenger count before identity reconciliation and notification fan-out;
- the snapshot descriptor publishes the active `max_group_passengers` and `max_incremental_changes` values so mobile can provide clear diagnostics instead of failing at an unrelated page cap.
- attendance activity creation takes the tenant-owned group row lock, preserves idempotent retries of an existing active activity at capacity, and rejects a genuinely new activity beyond `MOBILE_MAX_ATTENDANCE_SESSIONS_PER_GROUP` before insertion;
- the snapshot publishes that attendance capacity plus exact role-scoped counts for announcements, common documents, personal documents, roster rows, and attendance sessions. The mobile staging pass rejects both over-capacity and silently short pagination.

Capacity rejection uses the existing HTTP 422 domain-error envelope with code
`VALIDATION_ERROR`; no record is inserted. In the public-upload path, objects
written by the rejected attempt are compensating-deleted. The Excel import is
transactional and does not partially add rows past the limit.

Changing either environment value is a capacity decision. It requires matching mobile/database/load evidence and a coordinated deployment; raising a number alone is not proof that the environment can sustain it.

## Mobile follow-up contract

The mobile implementation must recognize `snapshot_rebase`, stage and atomically promote a replacement projection, publish metadata before document hydration, and remove the fixed 20-page collection ceilings in favor of bounded page-at-a-time database writes. The server contract does not by itself prove 10,000-device concurrency; that remains a production-like database, cache, worker, object-storage, push, and connection-capacity load gate.
