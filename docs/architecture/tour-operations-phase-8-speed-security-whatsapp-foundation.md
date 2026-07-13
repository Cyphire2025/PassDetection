# Tour Operations Phase 8 - Speed, Security, and WhatsApp Foundation

## Active Scope

This phase optimizes the existing attendance flow without changing the main user journey.

- QR scan payloads are validated as `pdatt:{43-character URL-safe random token}` before backend processing.
- Successful scan writes use database conflict handling instead of a separate duplicate lookup.
- Duplicate scan races are handled by attendance record uniqueness constraints.
- The scanner ignores non-attendance QR codes before updating scan state.
- Offline queue entries are keyed by session and QR payload, preventing local duplicate overcounting.

## Future WhatsApp Scope

WhatsApp is prepared as a disconnected foundation only. It is not exposed in the dashboard, coordinator PWA, or API router yet.

Prepared modules:

- `backend/app/application/dtos/whatsapp_dtos.py`
- `backend/app/application/interfaces/whatsapp_provider.py`
- `backend/app/application/use_cases/whatsapp/plan_group_broadcast_use_case.py`
- `backend/app/infrastructure/whatsapp/noop_provider.py`
- `backend/app/infrastructure/whatsapp/pricing.py`

## Intended WhatsApp Flow Later

1. Import or use existing group passenger names and phone numbers.
2. Preview recipients and template category before sending.
3. Send approved welcome template.
4. Send approved passport upload-link template.
5. After QR generation, send each passenger their own QR payload or hosted QR image.
6. Store provider message IDs and delivery status in a dedicated message log table.

## Category Guidance

- Welcome or promotional broadcasts are usually `marketing`.
- Passport upload links can be `utility` when they are transactional and expected.
- Attendance QR messages can be `utility` when they are operational and expected.

The final category depends on Meta template approval and provider review. Pricing must be checked against the active Meta/BSP rate card when enabling sends.

## Not Yet Enabled

- No WhatsApp API route.
- No WhatsApp dashboard page.
- No message-log database table.
- No BSP credentials or outbound network calls.
- No automatic QR image hosting.
