# WhatsApp delivery history

Each broadcast has two complementary reports on its existing `/history` page.
The default **Every send** view and its saved-message report are unchanged.
**By message type** adds unique-recipient coverage and separately numbered sends.
Selecting a version opens the original saved-message report, including number
editing and explicit resend controls.

## Overall coverage

`GET /api/v1/whatsapp/groups/{group_id}/message-types` returns all five built-in
types plus other types already present in that broadcast's log. The historic
`update` alias is reported as `document_update` (Trip update).

Totals use current, non-removed recipient entries, counted once by recipient ID.
They prefer any accepted attempt over later failed attempts, and delivered/read
evidence over acceptance alone. Without an accepted attempt, the latest attempt
determines the status. A recipient without any attempt is Not sent. Removed
recipients remain in their original per-send reports, but leave overall coverage.

Sent means provider acceptance (`submitted`, `sent`, `delivered`, `read`). Delivery
left is the subset accepted without a delivery/read receipt. Queued/processing
attempts become unconfirmed after the same existing timeout used by per-send
history. Unconfirmed, cancelled and unrecognized outcomes stay in the Failed
filter with their actual status; this read projection never rewrites evidence or
authorizes an automatic retry.

`GET /api/v1/whatsapp/groups/{group_id}/message-types/{message_type}/recipients`
provides paginated, searchable coverage with the five existing delivery filters.
Its counts describe the entire current cohort; search and filter narrow returned
rows only. Phone numbers are current editable numbers. A saved-send link retains
the original attempt's destination. Changing a number never rewrites earlier
history or proves a new number received the previous message.

## Version boundaries

`GET /api/v1/whatsapp/groups/{group_id}/message-types/{message_type}/versions`
groups by immutable batch ID, never by message wording. Sending the exact same
content again produces a separate version. Reminder, Group invite and Trip
update all use this mechanism, as do the other types. Explicit one-person resends
are separate batches and can have smaller audiences.

Version numbers follow the saved batch creation time with an ID tie-breaker.
Numbering happens before search and pagination, so filtering does not renumber
results. Each version reports its original audience and current recorded delivery
outcomes. Older logs without a batch ID remain visible as **Legacy record** with
no invented version number or guessed grouping by content/time.

These endpoints reuse existing authorization, agency isolation, SQL status
projections and message logs. They do not change the sender, eligibility rules,
idempotency, tasks, database schema or provider configuration. The type overview
uses a fixed set of aggregate queries rather than one query per type/recipient.

## Recipient comparison

The recipient page has a wider detail rail with separated, vertically stacked
cards. Two cards share the available height and each scrolls its own fields while
keeping its header visible. More than two cards allow the stack to scroll as well.
At narrower screen widths, cards move below the table and retain bounded internal
scrolling. Existing reduced-motion preferences apply to card entry animations.

## Verification

- `backend/tests/integration/test_whatsapp_type_history.py`: real SQL fixtures for
  unique coverage, success after repeated attempts, identical-content versions,
  aliases, filtering, stable numbering, legacy boundaries and agency isolation.
- `backend/tests/integration/test_whatsapp_workspace.py`: existing per-send report,
  immutable destination and historical resend contracts.
- `backend/tests/service_integration/test_whatsapp_type_history_postgresql.py`:
  parameterized grouping and numbered repeat sends on isolated PostgreSQL schemas.
- `frontend/e2e/whatsapp-delivery-types.spec.ts`: browser navigation, three repeatable
  type histories, overall filters/number correction, independent card scrolling at
  two desktop heights and mobile overflow. Synthetic API fixtures make no live
  provider calls.
