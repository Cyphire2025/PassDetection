# Tour Operations Phase 7 - QR Distribution

## Scope

Phase 7 adds the office-side QR distribution workflow for attendance scanning.

- Super admins, agency admins, and managers can open QR codes from Tour Ops group assignments.
- The backend generates opaque per-passenger attendance payloads for submitted passengers only.
- The frontend renders printable QR cards with passenger identity, contact details, and coordinator assignment.
- Coordinator PWA scanners continue to accept only server-issued opaque payloads.

## Security Model

QR payloads do not expose passport or passenger details. Each payload is a deterministic opaque token with an active hash stored in `passenger_qr_tokens`.

Office users can generate cards only for groups they manage. Managers are restricted to groups they created or were explicitly assigned.

## Operational Flow

1. Office creates coordinators.
2. Office assigns coordinators to groups.
3. Office opens a group and assigns passengers to eligible coordinators.
4. Office opens QR Codes and prints or shares passenger cards.
5. Coordinator logs into the PWA, starts a named activity, and scans the cards.
6. Office monitors activity counts from the Attendance view.

## Implementation Notes

- Endpoint: `GET /api/v1/tour-operations/groups/{group_id}/qr-codes`
- Dashboard route: `/tour-operations/groups/{groupId}/qr-codes`
- QR rendering is done in the browser with the `qrcode` package.
- Normal passenger assignment endpoints remain lightweight and do not generate QR images.
