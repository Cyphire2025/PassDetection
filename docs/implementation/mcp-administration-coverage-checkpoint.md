# Administration coverage reconciliation

Reviewed on 2026-09-30 against source `ba905132799728f6fcc7fa4cad103d9256768263`.
This finite correction changes only the implementation records of 14 existing
entries in [the workflow matrix](mcp-workflow-coverage.json): seven Administration
handlers, each represented by its source route and published OpenAPI operation.
Every entry changes from `planned` to `implemented_unverified`. No entry becomes
`verified`, no surface is added or removed, and no runtime authority is enabled.

| Existing handler | HTTP operation | Implementation and retained evidence |
| --- | --- | --- |
| `overview` | `GET /api/v1/admin/mcp` | Deployment/emergency state and resource/capability metadata; actual HTTP role boundary and Administration component/browser coverage. |
| `connections` | `GET /api/v1/admin/mcp/connections` | Bounded named-connection metadata with server-derived active/expired/revoked status; actual HTTP expiration/revocation and retained UI-state tests. |
| `activity` | `GET /api/v1/admin/mcp/activity` | Bounded, action-filtered fixed audit metadata; actual HTTP role boundary, UI pagination/filter reset and browser rendering. |
| `authorize` | `POST /api/v1/admin/mcp/authorize` | Active-superadmin consent, recent MFA, CSRF, approved redirect/resource and S256 PKCE; HTTP denial/issuance and consent UI/browser tests. |
| `control` | `PUT /api/v1/admin/mcp/control` | Manual emergency switch with recent MFA/CSRF; current enabled-state access denial and UI/browser control behavior. |
| `revoke` | `POST /api/v1/admin/mcp/connections/{connection_id}/revoke` | Durable manual revocation; actual HTTP rejection of both credentials afterward and retained revoked-state UI. |
| `update_connection` | `PATCH /api/v1/admin/mcp/connections/{connection_id}` | Manual naming/capability narrowing; HTTP expansion rejection, immediate reduced authority, and UI/browser narrowing coverage. |

All adapters name the existing
`backend/app/presentation/api/v1/routes/mcp_admin.py`. Their evidence lists point
to relevant retained source, HTTP tests, component tests and browser tests. The
shared `presentation/dependencies/mcp.py` boundary rechecks the actual active
superadmin and MFA-enabled account. Mutating handlers additionally require
recent MFA and cookie CSRF; read-only handlers do not require a fresh factor on
every read.

These are manual Administration workflows, not remotely callable MCP tools.
The existing rationale and `never_proxy_management_as_tool` requirement remain
unchanged. In particular, emergency control, consent, revocation and capability
editing do not authorize a model to alter its own connection authority. All
surface signatures/fingerprints, dispositions, phase assignments, adapter
requirements and exclusion boundaries are preserved. Existing frontend facade
rows and the separate inventory/operations/artifact rows are outside this pass.

After this finite correction, root approved a separate refresh of exactly two
router-registration surface fingerprints: `mcp_admin.py` and
`mcp_admin_files.py`. The coordinator added `route_class=MCPManagementAuditRoute`
to their existing router constructors. The helper observes fixed management
denial outcomes after request dependency cleanup; it preserves the existing
authorization dependencies and uses a separate bounded audit transaction.
No route, scope, classification, requirement or implementation status changes
in these two registration entries. Qualification of that audit helper is owned
by the coordinator. The final ledger diff is therefore 14 implementation
records plus two explicitly reviewed registration fingerprints.

## Evidence scope

The new `test_mcp_phase2_http_boundaries.py` cases passed 15/15 against the actual
local ASGI application and isolated SQLite; `mcp-connection-state.test.tsx`
passed 6/6 with mocked API responses. The former proves refresh/access resource
and lifetime boundaries plus real Administration revocation. The latter proves
retained expired/revoked metadata, no false success after denial/cancelled MFA,
post-success state refresh and removal of rendered management data after role
loss. The durable MFA HTTP/PostgreSQL suites are supporting evidence for the
shared authentication foundation, not a claim that every management mutation
has full PostgreSQL or production-browser coverage.

The existing browser suite uses intercepted API fixtures at 1440, 768 and 390
pixels. Its interaction/layout evidence is separate from a browser connected to
the live backend. This bookkeeping pass does not rerun business suites, close
P2.6/P2.7/P2.8, or claim full Phase 2 qualification. Management-denial auditing
and live-client acceptance have separate evidence owned by their implementers.
The following presentation improvement is a bounded addition to P2.6.

## Workflow outcome presentation

The existing Workflows cards now show the server-provided stage for every
operation, including terminal and uncertain outcomes. They separately label
the operation ID, workflow ID and owning connection ID, along with the
observation revision and update time. A completion time appears only when the
server supplies one. The workflow ID is a correlation identifier; the UI does
not relabel it as a provider, job or batch ID. Existing created-entity links
remain constrained to the supported group route.

Communication cards explain that dispatch completion does not confirm
delivery. The existing operation status is preserved, with `unknown` rendered
as “Outcome uncertain”; neither operation success nor `dispatch_complete`
becomes a sent or delivered receipt. The page does not invent delivery counts
or receipt detail that the Administration response does not provide. Component
coverage includes queued, running, cancelled, cancelled-with-unknown,
failed-dispatch, provider-unknown and succeeded-dispatch observations, plus a
completed PDF workflow awaiting review.

Connector setup now says “Full workflow qualification remains in progress.”
This removes an obsolete blanket claim that production sign-in/access had
never been qualified. It does not promote the release qualification flag or
claim that every workflow or attachment handoff has been verified. Production
OAuth/read/export evidence remains in the separately maintained live-client
record; these frontend checks use local fixtures.

The browser scenarios cover 1,440, 768 and 390 pixel widths with no horizontal
overflow, and screenshots were visually inspected. Retained examples:
[desktop workflows](evidence/mcp-workflow-outcomes/mcp-workflows-1440.png) and
[mobile uncertain workflow](evidence/mcp-workflow-outcomes/mcp-workflow-card-390.png).
They use intercepted response fixtures, not production API data. The temporary
Webpack test configuration was removed after the browser run; dependencies and
the shared browser configuration are unchanged.

## Validation

- `python scripts/mcp_inventory.py --check`: passed with 1,493 surfaces,
  68 tools, 423 OpenAPI operations, 442 source routes and 361 frontend callables.
- `python -m unittest discover -s scripts -p test_mcp_inventory.py -v`:
  all 12 existing drift/truthfulness tests passed.
- Exact parsed-JSON and compact-line audit against the baseline: exactly the
  14 expected source/OpenAPI implementation objects changed, plus only the
  `surface` objects of the two separately reviewed router registrations.
  Every adapter/evidence file exists inside the repository, and every other
  ledger line is preserved. No new verification or exclusion claims.
- `node node_modules/vitest/vitest.mjs run features/mcp --maxWorkers=1`:
  all 48 tests passed, including 14 workflow/file/tool observations and the
  retained six connection-state cases.
- Focused `e2e/mcp-administration.spec.ts` Playwright run: all five scenarios
  passed (23.6 seconds), including three responsive management flows,
  non-superadmin direct-navigation exclusion and consent with opaque state.
- Strict TypeScript (`tsc --noEmit --incremental false`), scoped ESLint and
  existing frontend size/complexity budgets passed. No budget was relaxed.
