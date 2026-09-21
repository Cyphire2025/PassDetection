# WhatsApp broadcast performance boundaries

The broadcast workspace keeps its existing screens, query keys, response shapes,
recipient ordering, and sending contracts. The September 2026 changes remove
repeated work from the existing paths rather than introducing another data cache.

## Browser reads and updates

`["whatsapp", "groups"]` is the shared prefix for lists, details, recipient
rosters, rejected-contact pages, and source contacts. A mutation invalidating
this prefix already refreshes every active descendant. Do not invalidate or
explicitly refetch the same descendants again after awaiting that refresh.

Read helpers consume React Query's abort signal. Closing a dialog or removing
an activity can cancel an obsolete request; mutations and queued deliveries are
not cancelled by this mechanism. Source-group refresh and one-way synchronization
keep their existing rules.

The live activity tracker keeps its existing foreground polling cadence. Interval
polling pauses when the browser tab is hidden, and focusing the tab refreshes it.
This affects browser status reads only: server-side sending continues. Combined
query results structurally share unchanged activity objects. Several completed
activities invalidate each affected group/query prefix once in the same update.

Delivery filter counts reuse the display predicate without sorting or building
display arrays. Only the visible filtered list needs ordering. Search indexes
normalize names, phone representations, and imported fields once per current
dataset while searching; they are component-scoped and rebuilt when that dataset
changes. Traveller pagination stores offsets while building pages and keeps each
shared-number group together.

## Database reads

Roster delivery state reads rank explicit attempts by recipient, message type,
and creation time in SQL, returning only the latest status and timestamp. They
do not hydrate historical message bodies or image parameters. The existing
failed-baseline timestamp comparison stays against the loaded state because
these database sessions do not automatically flush pending changes.

Group Invite destination protection aggregates the strongest blocking status
from logs and current delivery states in one SQL query. Tenant, broadcast, and
phone scope remain part of the destination key. Worker exclusions are applied
before aggregation. Result size is bounded by the requested destinations; the
database still evaluates retained history using the existing indexes.

Full batch status reads select the six response fields instead of hydrating
message-log and recipient models. Summary/activity endpoints retain their
existing database aggregates.

## Contracts to preserve

- Every source traveller remains visible, including people sharing a phone.
- Delivery deduplication, Group Invite retry protection, opt-in, and message
  prerequisites remain server-enforced.
- Group edits flow to linked broadcasts in the existing direction; broadcast
  edits do not rewrite source submissions.
- Import-only markers and tracking visibility remain unchanged.
- Template changes use the separate, durable configuration described in
  [WhatsApp template settings](whatsapp-template-settings.md). Queued payloads
  are frozen and delivery history is retained.

These changes reduce request duplication, result hydration, sorting, and repeated
normalization. No tests, builds, compilation, browser checks, benchmarks, or live
messages were run for this change at the user's request. Actual latency, capacity,
and behavior under production load remain unmeasured; full roster responses also
retain their existing size and are not server-paginated by this change.
