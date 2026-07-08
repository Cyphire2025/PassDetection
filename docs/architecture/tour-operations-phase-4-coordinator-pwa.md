# Tour Operations Phase 4 Coordinator PWA Shell

## Scope

Phase 4 introduces a coordinator-facing mobile shell backed by real coordinator assignment APIs.

The shell is the PWA start surface for coordinators. It does not yet persist attendance scans or create attendance sessions.

## Coordinator Surface

- `/coordinator` shows the signed-in coordinator's assigned groups.
- Selecting a group shows passengers assigned to that coordinator for the group.
- The mobile shell links to `/tour-scanner` for the existing continuous QR scanner proof.
- The PWA manifest starts at `/coordinator`.

## Backend Contract

The coordinator shell uses existing coordinator-only endpoints:

- `GET /api/v1/tour-operations/coordinator/groups`
- `GET /api/v1/tour-operations/coordinator/groups/{group_id}/passengers`

These endpoints remain role-gated to `agency_coordinator`.

## Out Of Scope

Phase 4 does not implement:

- Passenger QR token issuance UI.
- Attendance session management.
- Attendance record persistence from scans.
- Offline scan queue and sync.
- Attendance reporting.

Those belong to the attendance execution phase.
