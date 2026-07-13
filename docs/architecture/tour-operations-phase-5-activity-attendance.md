# Tour Operations Phase 5 Activity Attendance

## Scope

Phase 5 makes the coordinator PWA scanner flow operational for named attendance activities.

Coordinators log in once through the PWA, see assigned groups, select a group, name the current activity, and scan QR codes for that activity.

Example activity names:

- After lunch count
- After Destination 1 visit
- Hotel lobby departure

## Coordinator Flow

1. Open `/coordinator`.
2. Select an assigned group.
3. Enter the current activity name.
4. Start the activity scanner.
5. Scan passenger QR codes.
6. Complete the activity.

Each scan is sent with a `client_event_id` so repeat attempts are idempotent. Duplicate passenger scans in the same activity are rejected by the backend.

## Office Flow

The Tour Ops group list now has two actions:

- Open Group: split passengers between assigned coordinators.
- Attendance: view live and completed attendance counts for the group.

The attendance page polls every 10 seconds so office users can watch progress while coordinators scan.

## QR Model

Passenger QR payloads are cryptographically random, URL-safe bearer tokens and are validated by server-side hash matching against active, unexpired passenger QR token rows. The raw QR payload is revealed only when generated or regenerated and is never stored in the database.

## Still Out Of Scope

- Offline scan queue and replay.
- Public QR print sheet/export UI.
- Push/live websocket updates.
- Attendance reports/export.
