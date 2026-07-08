# Tour Operations Phase 3 Coordinator Module

## Scope

Phase 3 adds coordinator account management and group/passenger assignment foundations.

The desktop dashboard is the office control surface. The scanner remains a separate PWA/mobile route and is not embedded into the dashboard.

## Dashboard Responsibilities

The Tour Operations dashboard now supports:

- Creating coordinator accounts with the `agency_coordinator` role.
- Viewing coordinator workload.
- Viewing tour groups and submitted passenger coverage.
- Assigning multiple coordinators to one group.
- Evenly dividing submitted passengers among selected coordinators.

## Coordinator Access

Backend coordinator endpoints expose:

- Current coordinator assigned groups.
- Current coordinator passengers within an assigned group.

These endpoints are role-gated to `agency_coordinator`.

## Assignment Behavior

When office staff save coordinators for a group:

1. Active assignments for the group are closed.
2. Submitted passengers for the group are loaded.
3. Passengers are distributed round-robin across selected coordinators.
4. Assignment counts are returned for dashboard coverage.

This is an MVP allocation strategy. Manual drag/drop or custom passenger-level edits can be added later.

## Out Of Scope

Phase 3 does not implement:

- Passenger QR generation.
- Attendance session creation.
- Attendance recording.
- Offline scan sync.
- Session history or reporting.
