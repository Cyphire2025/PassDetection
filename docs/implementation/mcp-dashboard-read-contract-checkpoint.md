# Dashboard summary read-contract checkpoint

Reviewed on 2026-09-30. This finite Phase 1 correction changes only
`adapter_requirements` for the following three representations of one existing
dashboard summary workflow in [the coverage ledger](mcp-workflow-coverage.json):

- `frontend:frontend/features/dashboard/api/dashboard.api.ts:getStats`
- `openapi:GET:/api/v1/dashboard/stats`
- `route:backend/app/presentation/api/v1/routes/dashboard.py:get_dashboard_stats:GET:/stats`

All three remain `disposition: implement`, `phase: 3` and
`implementation.status: planned`, with no adapter or executable evidence added.
The frontend row's generic mutation requirements are replaced by the specific
read contract below; the two previously empty HTTP/source requirement lists now
carry the same contract. Every other row and every surface fingerprint is
unchanged. This is contract repair, not implementation or phase qualification.

The website [dashboard route](../../backend/app/presentation/api/v1/routes/dashboard.py)
uses the current active account's agency. When that account has no agency, it
returns zero counts and an empty recent list; it does not aggregate all agencies.
The [shared use case](../../backend/app/application/use_cases/dashboard/get_dashboard_stats_use_case.py)
passes the current actor into the visibility policy on every repository call and
adds the staff ownership/assignment scope. A future MCP adapter must additionally
revalidate the current active superadmin, connection, resource, session and
emergency state with `mcp:read`; documentation does not enable this capability or
permit actor impersonation or a new cross-agency aggregate.

| Response part | Source-backed contract |
| --- | --- |
| `total_passports` | Count canonical office-visible passport submissions within the actor's agency and role/lifecycle visibility. Preserve the repository's total semantics; these are not operational passenger or WhatsApp recipient counts. |
| `pending_review`, `confirmed` | Use the canonical pending-review/confirmed status families and the additional archived/deleted-group filter. Do not replace these with equality checks against one status or assume every count has identical archive semantics. |
| `active_links` | Count active visible client groups. The current query does not independently prove that an upload credential is unexpired or usable. |
| `recent_submissions` | A fixed preview of at most five records, ordered by creation time descending and UUID descending. The `CLIENT_SUBMITTED` repository filter expands to the office-visible status family. Archived/deleted groups receive the existing additional filter. This is not a pageable history endpoint. |

These details come from
[passport repository count/list queries](../../backend/app/infrastructure/repositories/passport_submission_repository.py),
[active group counting](../../backend/app/infrastructure/repositories/client_group_repository.py),
the [central visibility policy](../../backend/app/application/security/authorization_policy.py)
and the [response schema](../../backend/app/presentation/api/v1/schemas/dashboard_schemas.py).
The fixed preview exposes only its existing authorized identity/name/email,
status, timestamp and confidence projection, not passport documents or complete
source records.

The use case performs separate live queries. It does not establish a repeatable
database snapshot, so a future MCP response must include `observed_at` and state
that counts and recent rows can change during the observation. The website's
[30-second polling hook](../../frontend/features/dashboard/hooks/use-dashboard-stats.ts)
is a client refresh policy, not a server freshness or snapshot guarantee.

The future adapter has no caller pagination. Aggregate counts should remain
database-side, without applying workbook export row ceilings to counts. Its
recent projection needs a memory bound before unrelated retained data is
materialized: the current `list_by_agency` loads full passport ORM records even
though this response needs only five small projections. A shared bounded
projection or admission of those exact records, together with bounded query
execution, still needs implementation and qualification. An over-limit response
must be explicit rather than silently omit recent rows or claim full data.

The permitted effect is an invocation audit. This read workflow needs no
business transaction idempotency key, saved operation, background job, artifact,
rendering or export-history checkpoint. It must not mutate or remove business
records. Existing [use-case tests](../../backend/tests/unit/application/test_dashboard_use_cases.py)
use mocked repositories and do not prove an MCP adapter or actual SQL parity.
The remaining adapter qualification should cover two agencies, the no-agency
zero case, staff owned/assigned/unassigned groups, role-specific retained and
archived records, canonical status families, draft exclusion, tied timestamps
with UUID ordering, and six recent rows yielding exactly five. Actual web/MCP
projection parity, revoked or reduced authority, bounded source reads and absence
of business writes remain open.

Validation for this documentation change: the inventory check passed with 1,493
surfaces and 68 tools; all 12 existing drift tests passed. An exact JSON comparison
confirmed that only the three named requirement lists changed, their planned
implementation records stayed identical, and every other row and top-level
ledger field stayed identical. No application, test or runtime file changed.
