# Additive tour administration and GC itinerary drafts

This locally tested Phase 7 increment exposes three typed operations through
`register_tour_change_tools`. Each uses the existing MCP transaction/idempotency
service, live superadmin authority, an explicit agency and group, a business
audit, and current entity authorization before replay or inspection.

| Operation | Effect and preservation contract |
| --- | --- |
| `add_group_coordinators` | Locks the group, applies existing coordinator-management policy and trip-date eligibility, validates 1–100 distinct current coordinator IDs in the same agency, and inserts only missing active memberships. Existing active and inactive rows and every passenger assignment remain unchanged. |
| `create_attendance_activity` | Uses existing canonical name admission, group serialization, capacity and schedule validation. Creates an activity or returns a compatible active canonical activity unchanged. Existing draft/state/schedule mismatch conflicts; no activation, schedule rewrite, scan, runtime registration or physical event is fabricated. |
| `create_gc_itinerary_draft` | Uses the shared GC access/group lock, active/closed group rule and current access revision. Creates a new draft/version with days/items, advances the access revision, and retains all prior versions and content. Does not publish, retire content or queue notifications. |

`application/mcp/change_context.py` supplies shared current identity/agency/group
checks. Tour membership additions have their own insert-only adapter because the
website assignment endpoint accepts a full replacement list. The canonical
activity helper keeps its default website behavior; MCP explicitly selects the
strict additive resolver. Schedule values are normalized to UTC before entering
that resolver, including on SQLite where timezone metadata is not retained.

GC itinerary version creation is extracted into the shared flush-only
`application/use_cases/gc_app/create_itinerary.py`; the website keeps its existing
validation, policy, audit and response behavior. Nested MCP itinerary schemas
reject undocumented fields and duplicate day numbers. Shared website limits
remain 365 days, 250 items per day and 1,500 total items. Receipt data contains
IDs/counts, not free-text itinerary content or device/client-event secrets.

New attendance setup writes the existing internal synchronization journal. Its
existing inert GC anchor behavior grants no mobile audience access. Existing
canonical resolution produces no new synchronization event. No provider sends
occur in any operation.

Local evidence on 2026-09-29:

- Combined SQLite/SDK and existing website regression run: **128 pass** before
  five final focused retained-scan/cross-agency/removed-GC-access cases were added.
  The final focused file passes **31/31**, including those five additional cases.
  This covers the new tour/GC operations, prior office additions and menu,
  attendance, tour-route/visibility and GC content/closed-group regressions.
- **6 PostgreSQL 16.15 tests pass** in the guarded disposable loopback database.
  Six concurrent cross-connection requests create one entity per operation;
  distinct coordinator intents retain inactive history and add one active row;
  distinct itinerary intents at one revision have one winner; compatible
  canonical activity intents resolve the same UUID without schedule changes.
- Nine changed production sources pass mypy; scoped Ruff and all87 existing
  backend quality budgets pass. The canonical resolver was extracted cohesively
  without raising a size or complexity ceiling.

The coordinator membership index already permits inactive history in PostgreSQL;
its SQLAlchemy SQLite metadata now expresses the same partial-index predicate.
This does not add a PostgreSQL migration.

Broader tour administration, attendance lifecycle changes, scheduled edits with
retained history, GC publishing/notifications and remaining domain workflows are
still required. Actual Codex and production qualification remain open. A created
administrative activity is not proof that any passenger attended it.
