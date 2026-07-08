# Tour Operations Phase 1 Architecture

## Scope

Phase 1 establishes the foundation for a separate Tour Operations and Attendance module. It does not implement QR scanning, coordinator assignment screens, attendance session workflows, offline queues, or reporting.

## Product Boundary

Tour Operations is a separate operational module that uses confirmed passenger records from the existing passport workflow. Passport extraction, client upload, OCR, review, and export behavior remain owned by the passport module.

The module is coordinator-led rather than vehicle-led. Buses, flights, walking transfers, trains, boats, and hotels can all be represented by generic attendance sessions without transport-specific data models.

## Roles

The platform adds `agency_coordinator` as a dedicated role.

Coordinator accounts are intentionally excluded from existing passport, upload-link, analytics, settings, and admin navigation. Later workflow endpoints must also enforce this boundary server-side.

Coordinator access is limited to:

- Assigned groups
- Assigned passengers
- Attendance sessions
- QR scanner
- Attendance history

Admin and staff access covers:

- Coordinator management
- Passenger assignment
- Session monitoring
- Missing passenger views
- Attendance history

Super admin access additionally covers QR revocation/regeneration and system-level audit.

## QR Security Model

Passenger QR codes must contain only an opaque random token. They must not contain passport number, phone number, email, name, or other personal data.

The server stores a hash of the token in `passenger_qr_tokens`. A QR is stable by default, but can be revoked and regenerated. The database allows only one active QR token per passenger through a partial unique index.

## Data Model

Phase 1 adds four operational tables:

- `coordinator_assignments`: active/inactive assignment of passengers to coordinators for a group.
- `passenger_qr_tokens`: hashed revocable QR identity tokens for passengers.
- `attendance_sessions`: generic session lifecycle with `draft`, `active`, `completed`, and `cancelled` states.
- `attendance_records`: immutable check-in records for a session.

Attendance records enforce:

- `unique(session_id, passenger_id)` to prevent duplicate attendance.
- `unique(session_id, client_event_id)` to make offline sync idempotent.

## Offline Sync Strategy

Offline behavior is designed into the schema before scanner work starts.

The coordinator PWA will store pending scan events in IndexedDB. Each event will include a `client_event_id`, `device_id`, local scan timestamp, QR token payload, and session id.

When connectivity returns, the client will sync pending events. The server will use `client_event_id` for retry idempotency and `session_id/passenger_id` uniqueness for duplicate attendance protection.

The coordinator UI must show:

- Online/offline state
- Pending sync count
- Last successful sync time
- Sync failure state when retries are exhausted

## Navigation

Phase 1 adds a dashboard sidebar entry for Tour Operations and a read-only architecture/status page. Future phases should add the coordinator mobile shell separately from the existing desktop dashboard layout.

## Phase Gates

Phase 2 should not start until this foundation compiles and the migration is valid.

Phase 2 must validate continuous QR scanning on real Android and iPhone browsers before deeper workflow implementation.
