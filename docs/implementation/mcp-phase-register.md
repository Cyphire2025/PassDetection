# MCP implementation and product-fix evidence register

This register tracks the full user-approved objective. A partial implementation,
a passing unit test, or a classified inventory does not prove that a phase is
complete. Keep the overall goal active until every acceptance gate has current
evidence, including real Codex and production qualification where specified.

## Working agreement and baseline

- Implementation checkout: managed worktree `mcp-application-workflows`.
- User objective: complete the eight-phase, superadmin-only MCP integration on
  the existing VPS, plus the WhatsApp delivery/selection defects and compact
  responsive group overview. Work incrementally and report each completed phase.
- Team: root implements/integrates MCP; coordinator tracks coverage and checks
  evidence; delegated owners implement WhatsApp and group-layout work separately.
- MCP boundaries: no record/file/member removal, archive, purge, destructive
  replacement, arbitrary HTTP/SQL/shell/filesystem tool, server restart, deploy,
  reboot, or infrastructure-control capability. Inspect effects as well as names.
- Preserve existing authorization, MFA, consent/template/provider, data-retention,
  and real physical-event evidence requirements.
- No production send, destructive action, deployment, or container cleanup is
  evidence of completion merely because local code exists.
- Source baseline inspected 2026-09-29: committed OpenAPI snapshot contains
  **401 operations across 31 tags**. Source route tree contains 188 Python files,
  including support modules; this is not an operation count. Frontend workflows
  are under `frontend/app`, `frontend/features`, and `frontend/components`.
- Latest migration at baseline: `0113_document_follow_up`. The current qualified
  code-update path explicitly refuses schema/configuration/persistence changes.
  Durable MCP entities therefore require a separately qualified upgrade path;
  do not run the same-schema update helper against a new schema blindly.
- An authenticated read-only VPS snapshot at 2026-09-29 18:23 UTC observed source
  revision `a18d236f15bd96ea326fe436cdcc28af60ec17b0`, schema0113, no MCP tables,
  host/container/database resources. Runtime-role readiness and default grants have read-only evidence; live diagnostic
  collection and combined-load qualification remain open. Existing production files,
  services and data remain unchanged. A later pure Linux admission test created one
  new retained isolated helper lock, documented below.

## Progress summary

| Workstream | Status | Evidence / remaining gate |
| --- | --- | --- |
| Phase 1: inventory and baseline | Static inventory and initial live baseline recorded; gate open | Reviewed machine-readable source/API/UI matrix, drift checker and 12 behavioral tests; adapter effect reviews remain explicit implementation obligations. Read-only live snapshot records schema0113, source revision and resources; runtime privilege/readiness follow-up passes; logs, complete configuration and measured MCP capacity evidence remain open. |
| Phase 2: auth, connections, administration | Real OAuth, Codex and one durable management denial demonstrated; full gate open | User completed MFA/control enablement and named-connection authorization. Production1d77 retains one independently verified anonymous401 denial audit, and the authenticated workflow/setup UI and actual saved Codex readback passed. Durable assurance correction passes nine PostgreSQL races and focused HTTP tests. Complete controls and remaining expired/revoked/demoted/MFA live cases stay open; see the management release and live Codex checkpoints. |
| Phase 3: reads and diagnostics | Initial reads locally tested; one live dashboard example qualified; broad gate open | Initial group/passport/WhatsApp/document/job/office/GC/email/diagnostic evidence remains scoped below. Dashboard adds71 distinct focused cases including5 PostgreSQL tests; actual Codex on27afeb4c passed the fixed current-user schema and its four counts/five-row size matched the authenticated website. Optional sealed diagnostics remain disabled by default. Remaining domains, live log collection and broad production equality remain open. |
| Phase 4: transfers and exports | First production Codex Excel recovery/delivery and two option-discovery modes verified; broad gate open | Actual Codex resumed the saved operation on cd0e538f, checksum-verified14,863-byte local XLSX, and received server delivery acknowledgment; independent ZIP/openpyxl parsing passed. On27afeb4c, exact group and selected-group option reads passed three actual Codex calls with expected catalogs/defaults and unchanged100-row/1MiB limits. Earlier artifact/Excel/PDF/image ZIP evidence remains scoped. Other file families, scanner/TTL/revocation/recovery variants, complete source parity and combined-load capacity remain open. |
| Phase 5: safe business changes | Operation foundation and initial group creation locally tested; broad gate open | Agent reports72 SQLite tests (34 operations,24 group/SDK,14 existing website policy) and9 real PostgreSQL races including six concurrent create requests producing one group. Other business adapters and recovery/production evidence remain open. |
| Phase 6: conversational communications | Exact reminder lifecycle locally tested; broad gate open |170 affected integration/web/worker/receipt tests and6 PostgreSQL lifecycle races pass. New contact-workbook import has126 tests and3 PostgreSQL races passing; it creates a new broadcast without sending. Real provider, complete Excel-to-send scenario and other communication families remain outstanding. |
| Phase 7: remaining domains | Office/tour/GC and additive group-access/link operations locally tested; broad gate open | Office65 regressions plus6 PostgreSQL races; tour/GC31 final focused tests,128 earlier combined regressions and6 PostgreSQL races pass. Broader tour/GC lifecycle, retained room allocation, versioned plan regeneration and all other permitted workflows remain open. |
| Phase 8: qualification and rollout | Management/frontend and options/dashboard backend releases verified; full gate open | Backend27afeb4c/frontend1d77c9dd/schema0122 are live; workers remain efea4e4a. Independent23:57UTC probe verifies all20 services, public200, zero application OOM/restarts, continuous frontend and retained prior/intermediate resources. The96-case backend-only operator passed all four actual phases. Combined options/dashboard regression5921pass retains three skips/318 separate service exclusions. Saved Codex option and dashboard reads passed against27afeb4c, with current-user dashboard count equality. Earlier management recovery/denial audit and first actual-client Excel delivery remain separately recorded. Broad workflow/security/recovery and combined Linux-load/capacity gates remain open. |
| WhatsApp delivery state | Locally tested; release gate open | Exact receipt states, bounded reconciliation and revision cache refresh; delegated React/contract/lint/type checks recorded below. Provider/production evidence outstanding. |
| Passport-link recipient selection | Shared preview has targeted live evidence; broader gate open | Async/reopen/audience-identity regressions pass. Live passport-link preview safely showed an empty audience with send disabled. After1d77 deployment, the shared Welcome preview loaded one eligible recipient asynchronously and selected it automatically, with selectedIndex0 and send-to-one enabled; the preview was cancelled without sending. A populated passport-link audience, multiple-recipient switching and provider outcomes remain outside this live observation. |
| Compact group overview | Targeted live responsive verification passed |16 focused React, 24 existing contracts and 5 responsive local browser tests passed, with joined TypeScript/lint/budgets. Production readback on the EF frontend verified three cards in one desktop row, tablet wrapping, mobile stacking, no horizontal overflow at1440/768/390px, and working trip-detail expansion/collapse. Scope is one active group with the signed-in superadmin; no provider/send qualification is implied. |

## Phase acceptance register

### Phase 1 — coverage and production baseline

- P1.1: Inventory source routes and browser workflows, including routes missing
  from the committed OpenAPI snapshot. Each maps to a business MCP workflow, an
  internal/provider dependency, or an explicit agreed exclusion with rationale.
- P1.2: Classify allowed reads, exports, uploads, changes, communications and logs;
  identify destructive side effects hidden in imports/replacements/list updates.
- P1.3: Record authorization, export-history and job/queue contracts per workflow.
- P1.4: Verify deployment revision/capabilities, configuration and measured VPS
  capacity without exposing secrets. Record unavailable evidence as unavailable.
- P1.5: CI detects new unclassified workflows; the matrix measures coverage and
  never substitutes classifications or tool counts for implemented behavior.

### Phase 2 — secure connection and Administration / MCP

- P2.1: Pin a tested official Python MCP SDK release compatible with Python 3.11;
  mount standards-compatible Streamable HTTP at `/mcp`, with correct lifespan,
  multiprocess behavior, explicit transport host/origin policy and resource URI.
- P2.2: OAuth authorization-code plus S256 PKCE reuses actual superadmin login,
  MFA and CSRF checks. OAuth authorization and token verification remain separate
  components. No password grant, implicit grant or shared administrator key.
- P2.3: Durable individually revocable grants, protected token hashes, 15-minute
  access tokens, rotating refresh credentials and a seven-day absolute grant
  lifetime. Single-use codes and atomic refresh reuse detection are exercised.
- P2.4: Approved clients/redirects, resource binding, rate limits and nonce/state
  verification. Do not trust a client-supplied identity or approval boolean.
- P2.5: Recheck actual active superadmin, security version, grant/connection state,
  emergency switch and capability on every request/download. Current revocation,
  deactivation or role loss rejects new calls and undispatched queued operations.
- P2.6: Superadmin-only Administration / MCP UI and APIs: named connections,
  creation/last-use/expiry/status, setup instructions, capability controls,
  revocation, emergency disable, activity history, workflows/jobs/files/outcomes
  and deployed-capability inventory. MCP cannot increase its own authority.
- P2.7: Audits record successful/failed/denied operations and entity identifiers,
  excluding credentials/raw documents. Sensitive account actions retain MFA rules.
- P2.8: A real Codex client connects successfully; non-superadmin/direct-endpoint,
  expired, wrong-resource and revoked clients fail at the real HTTP boundary.

### Phase 3 — comprehensive live reads and diagnostics

- P3.1: Query all business domains below through shared application services and
  policies. Extract reusable services when business logic lives in route handlers.
- P3.2: Resolve names explicitly, distinguish submissions, operational passengers
  and WhatsApp recipients, include empty groups, and preserve complete pagination.
- P3.3: Results identify environment, observation time, record identifiers and
  completeness. Distinguish deployed, enabled, passing functional check and unknown.
- P3.4: Bounded allowlisted API/worker/frontend/integration/proxy logs support
  request/job correlation, redaction and useful diagnostic evidence. Distinguish
  no matching error from inaccessible/unavailable logs.
- P3.5: Read outputs match synthetic API/UI fixtures and controlled live evidence;
  known failing workflows can be traced without arbitrary log/command access.

### Phase 4 — uploads, downloads and exports

- P4.1: Versioned local stdio-to-HTTPS MCP connector with browser OAuth, bounded
  loopback callback, state/PKCE and OS credential vault. No plaintext credential
  fallback and no access to Codex's private credential storage.
- P4.2: Connector proxies remote tools, accepts explicitly provided/identified
  files and streams uploads using existing size/format/malware controls.
- P4.3: Authenticated artifact IDs/protected links for direct clients; local
  downloads do not silently overwrite. Size/checksum verification precedes success.
- P4.4: Preserve export-history distinction between generation and verified
  delivery, including interrupted/resumed transfers and revoked permissions.
- P4.5: Cover group, selected, incremental and extra-column Excel exports;
  document/image ZIPs; tracking, rooming, menu and every other permitted export.
- P4.6: Temporary transfer copies expire independently of retained business/source
  files. Never embed large files or credentials in MCP tool results or logs.

### Phase 5 — safe groups, documents and application changes

- P5.1: Group creation/configuration, contact/passport Excel imports, document
  uploads, safe detail edits, approvals and supported processing operations.
- P5.2: Durable operation/workflow IDs, progress, outcomes and created-entity links;
  state survives API processes, restarts and Codex reconnection.
- P5.3: Idempotency at the business transaction boundary prevents duplicate groups,
  imports/jobs and other mutations across concurrency, lost responses and retries.
- P5.4: Additive or version-preserving adapters for replacement-prone APIs; deny
  unsafe variants. Test absence of hidden deletes in nested/bulk operations.

### Phase 6 — conversational communications

- P6.1: Excel inspection, sheet/column selection, normalization, valid/duplicate/
  rejected rows, agency/name/support contacts and recoverable parsing errors.
- P6.2: Resolve existing groups or collect required group details, recipient sets,
  message/template, links and attachments; ask only for missing/ambiguous input.
- P6.3: Immutable expiring preparation binds final content, exact recipients,
  attachments and revisions. Dispatch accepts ID plus idempotency key without
  content override or model-supplied confirmation as authorization.
- P6.4: Codex instructions require explicit user direction to send; complete
  already-authorized instructions do not require repeated dashboard approval.
- P6.5: Revalidate authority/consent/template/recipient limits/revisions at dispatch;
  report queued, sent, delivered, failed and uncertain separately. Reconcile
  uncertain provider outcomes before retries; no duplicated provider sends.
- P6.6: WhatsApp, email and push workflows, relevant follow-up/reminder audiences,
  attachments and delivery reconciliation match application policies.
- P6.7: Real Codex Excel-to-broadcast acceptance covers missing information,
  rejected rows, disconnects, concurrent changes, retries and partial delivery.

### Phase 7 — remaining application workflows

- P7.1: Complete permitted tour operations, attendance administration, coordinator
  assignments, QR/document distribution, rooming and menus without fabricating
  physical events, removing existing records or overriding retention.
- P7.2: Complete GC App groups/content/itineraries/notifications, administration,
  account operations/settings and analytics/audit queries with existing authority.
- P7.3: Complete document rename, ECR, email integrations/AI inbox, processing,
  notifications/search and every other discovered allowed workflow. Provider
  callbacks, public uploads and device protocols remain dependencies, not exposed
  administrator tools that bypass their protections.
- P7.4: Every allowed matrix row has concrete executable coverage; only agreed
  boundaries and internal/provider mechanisms remain excluded.

### Phase 8 — production qualification and rollout

- P8.1: Complete security, integration, browser, real-Codex, concurrency and
  failure-recovery verification. Test adversarial spreadsheet/document/log text
  cannot grant authority, exfiltrate credentials, redirect uploads or call tools.
- P8.2: Test real PostgreSQL concurrency and populated schema upgrade/rollback
  compatibility. Adapt release qualification for new durable tables deliberately;
  the baseline same-schema release helper cannot deploy this change unmodified.
- P8.3: Joined website and MCP workloads demonstrate no OOM/connection-pool
  exhaustion and acceptable measured latency/queue backlog. Update capacity,
  drain/readiness and resource-envelope checks with measured overhead.
- P8.4: Installation, support, credential revocation, incident recovery and upgrade
  runbooks are tested; retain current release and rollback evidence.
- P8.5: Qualified images and controlled production activation: reads/exports first,
  then tested create/upload/send capabilities, emergency disable available.
- P8.6: User can connect Codex, inspect a live group, upload a document, download
  the correct Excel, complete the broadcast scenario and diagnose a known error.
  Local fixtures alone do not satisfy this final gate.

## Additional product-fix acceptance

### W1 — accurate live WhatsApp delivery progress

- Initial accepted/queued work must never appear delivered before provider evidence.
- Counts and row statuses update without a manual refresh for the same open batch;
  preserve queued/sent/delivered/read/failed/uncertain semantics.
- Reconcile out-of-order provider events, delayed failures and reconnect/refocus;
  stale list/detail caches must not overwrite newer batch status.
- Poll only as needed, with bounded cadence/backoff and correct teardown; reconcile
  through existing realtime infrastructure where supported.
- Reproduce a ten-recipient mixed-result scenario with three failures and verify
  the open UI reaches seven successful / three failed without toggles or reloads.
- Test component/query behavior and backend projection where the root cause spans
  both. No actual production sends are required for regression testing.

### W2 — passport-link preview selection state

- Opening via the three-dot Send passport link action with eligible recipients
  preselected immediately shows the correct individual send count and enables the
  valid action. Deselect/reselect must not be required to synchronize state.
- Cover reopen, async preview resolution, audience/group change, no eligible
  contacts, all/partial selection, concurrent updates and rejected/ineligible rows.
- Submit exactly the visible eligible selection; avoid stale derived state and
  additional render/effect cycles where direct derivation is sufficient.

### U1 — compact, responsive group overview

- Replace large vertically stacked destination/trip, WhatsApp tracking and document
  tracking sections with a coherent compact responsive overview so submissions
  become visible much sooner on desktop and remain usable on mobile.
- Show passport-expiry alerts below the overview only when there are alerts;
  preserve access to detailed information/actions with clear disclosure controls.
- Preserve distinct loading, empty, error, permission and unavailable states, field
  edits and existing workflow actions. Avoid ornamental or placeholder controls.
- Test keyboard/focus/semantics, narrow/wide viewports, long content, large counts,
  loading/empty/error states and screenshots against the user's examples.
- Browser evidence must demonstrate reduced vertical height and no horizontal
  overflow, lost controls or regression in the submissions workflow.

## Domain inventory baseline

These are OpenAPI tags and operation counts, not proof of MCP tool implementation.
Read source and browser interactions before deciding how operations are grouped.

| Domain tags | Baseline operations |
| --- | ---: |
| Passports | 60 |
| Tour Operations | 37 |
| WhatsApp | 32 |
| GC Mobile Operations | 24 |
| GC App Administration | 23 |
| GC App Content Publishing | 21 |
| Upload Links | 20 |
| GC Mobile Resources | 16 |
| Document Distribution | 16 |
| Email Integrations | 16 |
| Admin | 14 |
| Rooming Lists | 13 |
| Menu & Meal Planner | 13 |
| Authentication | 13 |
| GC Mobile My Photos | 13 |
| GC Mobile Authentication | 11 |
| GC App Notifications | 10 |
| AI Travel Operations Inbox | 8 |
| Account Administration | 8 |
| ECR Checker | 7 |
| Document Rename | 6 |
| Health | 4 |
| Notifications | 4 |
| Audit Logs | 3 |
| GC Mobile Integrity | 2 |
| AI Travel Operations Rollout | 2 |
| GC Mobile Journey; Dashboard; Observability; Analytics; Search | 1 each |

## Evidence ledger

Append only meaningful evidence with command/scope/result and remaining limitation.
Passing narrow checks must retain their actual scope.

| Date | Scope | Evidence | Result / limitation |
| --- | --- | --- | --- |
| 2026-09-29 | Baseline | Parsed `backend/contracts/api.openapi.json`; inspected route registrations and frontend pages. | 401 operations / 31 tags; not a deployed-state or MCP coverage check. |
| 2026-09-29 | Release compatibility | Read `docs/QUALIFIED_CODE_UPDATES.md` and `docs/CONTRIBUTOR_GUIDE.md`; inspected migration head. | Schema 0113 baseline; normal release path rejects schema changes. |
| 2026-09-29 | Source/UI inventory | `scripts/mcp_inventory.py --check`; reviewed `mcp-workflow-coverage.json`; guide in `mcp-coverage-guide.md`. | Original source 419 versus committed contract 401; frontend 351 callable surfaces / 62 pages. New MCP surfaces are added as implemented. Classifications are not runtime authority or implementation evidence. |
| 2026-09-29 | Coverage drift behavior | CPython3.11.15 `-m unittest discover -s scripts -p test_mcp_inventory.py -v`. | 12 tests passed: hidden/new routes, frontend additions/non-async facade changes, auth signatures, router prefixes/registrations, duplicate/stale entries and false verification/exclusion claims. |
| 2026-09-29 | Local execution / production evidence | `docker info --format '{{.ServerVersion}}'`; Python version; SSH/default configuration inspection; retained resource/profile/release evidence. | Docker Linux engine pipe unavailable. Python3.11.15 works in primary `.venv311`. Current production state remains unobserved; exact limitations and historical evidence in `mcp-production-baseline.json`. No containers mutated. |
| 2026-09-29 | WhatsApp regression (delegated owner) | Broad React suite195/196, then stale archive-navigation expectation corrected and targeted9/9;104 WhatsApp `.mjs` tests; TypeScript and scoped ESLint. | All executed final targeted checks passed. Full broad suite after final expectation correction and final joined/browser/provider qualification are separate outstanding evidence. |
| 2026-09-29 | Group overview (delegated owner) |16 focused Vitest;24 existing group contracts; scoped ESLint; `tsc --noEmit`;40 module budgets;5 isolated Playwright cases at1440/768/390, keyboard/import-only/error cases. | Reported passing; webpack used after Turbopack rejected the worktree dependency junction. Final module-extraction browser rerun and retained screenshot paths pending. |
| 2026-09-29 | Final group-overview rerun (delegated owner) | `frontend/e2e/passport-group-overview.spec.ts`:5/5 Playwright cases passed after final extraction in22s; scoped lint clean. Screenshots retained in `evidence/group-overview/overview-{1440,768,390}.png`. | Temporary webpack configuration removed and test server stopped. Latest whole-project TypeScript run encounters concurrently incomplete MCP scaffold modules/route typing; overview has no reported diagnostic. Re-run full type check after integration. |
| 2026-09-29 | MCP HTTP authentication foundation (root owner) | `backend/tests/integration/test_mcp_authorization.py`: 24 passed against SQLite and the actual ASGI HTTP `/mcp` boundary. | Covers role/active/deleted/MFA/security-version changes, revoked/expired grants, emergency disable, PKCE/resource/redirect binding, code single use, durable refresh-replay revocation, narrowing, CSRF and lifespan. Does not establish PostgreSQL races, real Codex or production compatibility. |
| 2026-09-29 | Broadened inventory check | Final local matrix check passes for 1,384 surfaces, including the new MCP UI/OAuth and one registered tool. Ruff and CI supply-chain policy pass. | Callable detection was corrected to distinguish actual `fetch()` from query `refetch()`; 36 false callable entries removed while their page/API workflows remain represented. All business coverage remains planned or unverified. |
| 2026-09-29 | MCP UI integration (delegated owner) |39/39 administration/consent/role/redirect tests; full `npm run type-check`; targeted ESLint. | Passing after the MCP scaffold settled, resolving the earlier concurrent type-check failure. Real browser sign-in/consent-to-connector acceptance remains separate. |
| 2026-09-29 | Identity/MCP integration (root owner) |59 combined local identity/MCP tests, including the 24 MCP HTTP tests. | Passing before follow-up limiter/denied-audit changes; those changes need their own rerun. |
| 2026-09-29 | Updated HTTP contract / inventory | Root regenerated backend OpenAPI with seven MCP management operations plus existing document-follow-up and recipient-detail source operations. Coordinator `mcp_inventory.py --check` passes at 1,393 surfaces / 410 OpenAPI operations. | Corresponding source classifications retained; schema format changes from the Pydantic upgrade do not themselves prove behavior. |
| 2026-09-29 | Migration-aware release recommendation | Inspected current/code-update/dispatcher helpers, exact schema readiness, migration and role provisioning. Wrote `mcp-additive-release-contract.md`. | The current release helper also invokes persistent/storage changes. Recommended a distinct qualified additive mode with exact chain, writer fence, retained backup and tested recovery; no existing release guard relaxed or production action performed. |
| 2026-09-29 | Final frontend integration (delegated owner) |23 files /252 React tests pass: WhatsApp196, MCP/auth40, overview16. Five MCP Playwright fixture cases at1440/768/390 include denied non-superadmin direct URL and consent-to-callback with opaque state. Global TypeScript and focused ESLint pass. | Browser evidence is isolated HTTP fixtures, not live backend/provider/Codex. Screenshots and frontend evidence retained under `evidence/`. |
| 2026-09-29 | Connector foundation (delegated owner) | `mcp-connector/`:27 tests, wheel build, isolated wheel installation with the hash-locked runtime, CLI version/help and Ruff checks pass. Tests cover OAuth/metadata injection, loopback callback/Host/state/replay, mocked Windows vault, refresh concurrency/uncertainty, SDK handshake/wire, transfer primitives and actual local TCP backend OAuth/PKCE/MCP/rotation/revocation with SQLite. Windows mutex exclusion/release is tested without secret writes. | Actual Windows-vault sign-in, real Codex/production OAuth and remote artifact transfer integration remain unverified. Transfer primitives are not exposed as tools yet. |
| 2026-09-29 | Latest root authentication/release checks | MCP HTTP29/29; full application mypy734 modules and Ruff; core/domain194 passed with2 platform skips and27 subtests; rate limits26 with18 subtests;87 backend budgets; manifest4 and same-schema guard14; topology0114. | Root-reported local evidence includes per-grant429, limiter outage503, unknown-tool audit without raw input and dedicated management permission. Nginx routes added but container syntax/live TLS tests unavailable while Docker is down. |
| 2026-09-29 | Initial group discovery (coordinator) | `backend/tests/integration/test_mcp_group_reads.py`:12 passed in SQLite. Scoped mypy2 and Ruff pass. Page instrumentation verifies2 SQL queries for25 groups;107-group tie-order pagination tested. | Empty/import-only groups, duplicate names across agencies, separate raw/passenger/recipient-entry counts, literal searches, actor/filter-bound signed cursors, expiry/tamper, page limits and live rename behavior covered. No snapshot guarantee; PostgreSQL plan/capacity and tool HTTP registration remain separate. |
| 2026-09-29 | Cancellation and credential-disconnect effect review | Read passport cancellation route, retained job repository and worker cancellation; read email disconnect and separate data-removal route; followed upload-link close into retention policy. | Corrected processing cancellation and credential-only email disconnect from removal exclusions to planned safe adapters. Existing upload-link revoke can schedule passport purge and retains its explicit boundary. No adapters were enabled by this classification correction. |
| 2026-09-29 | Dependency qualification (root owner) | Runtime advisory audit passes after pydantic-settings2.14.2 resolved CVE-2026-58203; current ECDSA exception revalidated against unchanged installed versions/source/import closure. Local SBOM in `outputs/mcp-runtime-sbom.json`. | Existing ECDSA exception remains scoped and unpatched; full image/release security qualification remains open. Detailed evidence in `mcp-dependency-review.md`. |
| 2026-09-29 | Disposable PostgreSQL qualification (root / operation owner) | PostgreSQL16.15 on isolated loopback: full migration0001 through0114 passed;3 OAuth concurrency tests and latest9 operation concurrency tests passed. | Includes single-use code, refresh/revocation, duplicate/rollback/payload/control/grant/role/security barriers and six concurrent group creates yielding one group/audit. Not production, populated upgrade, recovery-build or load qualification. Docker startup remains unavailable; no destructive repair performed. |
| 2026-09-29 | Diagnostic foundation (coordinator) |21 SQLite/file tests, scoped mypy3, Ruff and87 backend budgets pass. Typed diagnostic SDK registration supplied by root. | Actual audit/job evidence, correlation, static source/time/size limits, secret/PII/raw-document omission, malformed log handling, permission/DB outages and role checks covered. All five runtime log collectors default unavailable; no production log retention/mount evidence exists. |
| 2026-09-29 | WhatsApp live reads (coordinator) |44 tests pass:8 relational read tests,2 actual authenticated SDK/ASGI cases and34 existing batch/receipt regressions; scoped mypy5 and Ruff pass. SDK cases re-pass after capability metadata was added. | Separate recipient/source/rejected rows, duplicate names/agencies/import-only,113-row pagination, signed cursor scope, exact provider states and ten-recipient seven-delivered/three-failed scenario covered. Persisted audience reads do not claim prepared send eligibility or every communication engine. |
| 2026-09-29 | Initial safe group creation (delegated owner) |72 SQLite tests and9 PostgreSQL operation tests passed, including group creation through SDK/invocation and existing website rules. | Durable foundation and one creation adapter only; no comprehensive Phase5 completion or exactly-once external delivery claim. |


| 2026-09-29 | Retained documents and processing jobs (coordinator) |6 tests pass:5 relational and1 authenticated SDK/ASGI case exercising all three tools; scoped mypy3 and Ruff pass. | Empty/import-only groups, agency/deleted scope, operational membership versus assignment, identifier opt-in and audit, old/current job revisions and107-row bound pagination covered. Metadata does not imply delivered bytes, completed exports or all queue families. |
| 2026-09-29 | Artifact and connector foundation (delegated owner) |31 backend tests (18 artifact plus13 website history),2 PostgreSQL races and34 connector tests pass. Connector0.2.0 wheel installed in isolated environment; real TCP stages scanned PDF and saves/reopens XLSX before acknowledgement. | Detailed contract and limits in `mcp-artifact-foundation.md`. Staged PDF does not ingest business records. Native vault/browser sign-in, real Codex, production S3/ClamAV/Nginx/TTL, all file families and local MCP file-tool exposure remain open. |
| 2026-09-29 | Latest disposable PostgreSQL checkpoint (root owner) |15 tests pass:3 OAuth,9 business-operation races,2 artifacts and1 full migration chain. | Supersedes earlier smaller concurrency checkpoint only; no populated-production upgrade, load or recovery-build qualification. |


| 2026-09-29 | Bounded office read breadth (coordinator) |9 tests pass:8 relational and1 actual authenticated SDK/ASGI case covering four tools; mypy3 and Ruff pass. | Explicit tour assignments/activity/scan records; distinct rooming hotels, selections, rooms, allocations and check-ins; separate platform/agency menu and retained meal snapshots; privacy-minimal directory and separate roster counters. Includes107-row creation-cutoff pagination and inconsistent cross-agency links. Does not establish full attendance/closeout, allocation freshness, all analytics or PostgreSQL load behavior. |
| 2026-09-29 | Client-detail correction (delegated owner) |29 new client-detail SQLite/SDK plus36 operation tests pass;66 existing website/domain tests pass;2 new PostgreSQL races pass. Scoped mypy7/Ruff and12 connector setup UI tests pass. | Required revision, sparse nonempty corrections, retained changed-value history, no OCR/source replacement or queued-delivery cancellation. Other mutation families remain open. |
| 2026-09-29 | Evolving additive schema candidate (root owner) |Root reports0115 client edits/access,0116 reminder plans/outbox and0117 dispatch-origin migrations applied to disposable PostgreSQL with retained-data downgrade fences. | Historical0114 checkpoint above is not the final release chain. Candidate release/manifest, populated upgrade, recovery and production qualification must use the final chain. |


| 2026-09-29 | GC App, authored alerts and personal email (coordinator) |30 combined tests pass:6 new relational/SDK content tests,9 office regressions after shared context/page extraction,15 existing email website contracts. Scoped mypy9/Ruff and87 backend budgets pass. | GC publication/access state, all retained itinerary versions/days/items, common-document metadata, authored recipient/device receipt counts, and owner-only connection/message/artifact/review/event metadata.103-message pagination and cross-user superadmin denial covered. Content opt-in is audited and truncation reports partial. No provider fetch or full-email/GC-family completion claim. |
| 2026-09-29 | Passport XLSX export family (delegated owner, root registered) |49 artifact/export/website focused tests,148 shared exporter/route regressions,5 actual PostgreSQL artifact/export races and1 real TCP SDK-to-connector generation/retry/save/ack case pass. | Group full/incremental, selected groups and exact selected-passport XLSX now locally qualified; all other export/ingestion families remain open. Exact contracts and remaining gates in `mcp-excel-exports.md`. |
| 2026-09-29 | Diagnostic correlation checkpoint (root owner) |26 tests pass, including actual HTTP timeout injection followed by audit-ID lookup and static failure category projection; malicious categories discarded. | No raw exceptions exposed. Runtime log collector and production retention remain unavailable. |


| 2026-09-29 | Additive menu and hotel configuration (coordinator, root registered) |65 tests pass across new SQLite/SDK creation cases and existing menu/rooming regressions;6 actual PostgreSQL races pass; six production sources mypy and scoped Ruff pass. | Four creations only: categories, revision-bound dishes, new meal plans and empty hotel stays. Current receipt access, scope separation, audit rollback and immutable retry tested. Retained auto-allocation/versioned regeneration and broader Phase7 remain open; exact contract in `mcp-office-creations.md`. |
| 2026-09-29 | Reminder lifecycle qualification (delegated owner) |170 affected integration/web/worker/receipt tests;11-source mypy/Ruff;6 actual PostgreSQL tests pass. | Exact frozen preview/hash, explicit confirmation, outbox, live originating-grant dispatch fence, queued-only cancellation, retained source origin marker and no unknown resend. No Meta/provider or production qualification; other communication modes remain open. |
| 2026-09-29 | Connector local transfer authority (root owner) |48 connector tests and19 artifact tests pass; fresh capability preflight at `/mcp/artifacts/authority` audits `mcp.file_authority_checked`. Connector0.2.0 rebuilt wheel SHA256 `32d6fb13d87cbc62a5bde0323a91365f3bde9f0d129bcc6677b2170a51c22aa6`. | Startup-approved exact local paths/folders are enforced; this is not automatic Codex attachment access. Actual Codex/native-vault browser sign-in and production file-path qualification remain open. |
| 2026-09-29 | Continuing unpublished schema chain (root owner) |0118 PDF ingestion artifact binding and0119 contact import schema applied on disposable PostgreSQL. | Source release remains0113; current candidate chain passes through0114–0119. Final-head/recovery/release qualification must bind the eventual exact chain, not just the most recent local head. |
| 2026-09-29 | Retired rooming compatibility review (coordinator) |Read all five hidden manual room creation/edit/order/delete/allocation handlers; each unconditionally returns HTTP410. | Classified these retired shims as internal compatibility boundaries. Active passenger selection and auto-allocation remain permitted planned work requiring retained versions; this does not exclude rooming as a domain. |
| 2026-09-29 | Initial combined capacity harness (root owner) |18 harness and negative-contract tests pass. | Actual combined MCP read/export container benchmark remains unrun; no current capacity or production memory/latency claim. |


| 2026-09-29 | Additive tour and retained GC drafts (coordinator) |31 final focused tests pass,128 earlier combined new/office/website regressions pass,6 actual PostgreSQL races pass;9 production-source mypy, scoped Ruff and87 backend budgets pass. | Add-only coordinator membership, strict canonical attendance setup and retained itinerary draft creation. Existing scan evidence retained; current receipt access and inactive membership history tested. No physical-event fabrication, publication or notifications; broader Phase7 remains open. Contract in `mcp-tour-gc-creations.md`. |
| 2026-09-29 | Retained PDF business ingestion (delegated owner, root registered) |98 focused PDF/artifact/shared-web/ingester tests,4 actual PostgreSQL races and1 official-SDK-to-proxy-to-TCP test pass;7-source mypy/Ruff pass. | Contract in `mcp-pdf-ingestion.md`. No completed Phase4, real scanner/storage/Codex/attachment or production-capacity claim. |
| 2026-09-29 | Contact XLSX to new broadcast (delegated owner) |126 new HTTP/SQL/SDK and existing parser/import/create/ledger tests;3 actual PostgreSQL races;14-source mypy pass. | Agency-scoped retained XLSX, scanner evidence and bounded literal parsing, explicit mappings/preview hash/support contacts/opt-in, rejected-row retention and new broadcast only. No sends; real Codex/production and other communications remain open. |
| 2026-09-29 | PostgreSQL read parity and connector checkpoint (root owner) |24 actual PostgreSQL group/document/office/content read cases pass; latest connector suite55 passes. | Read parity is local synthetic-data evidence, not live production equality or load evidence. Earlier connector counts are historical scopes. |
| 2026-09-29 | Signed additive release metadata (root owner) |34 release artifact/code-update/manifest tests pass. Exact source hashes and ordered0113-to0119 chain bound to `mcp_additive_v1`; initially disabled and forward-repair contract required. | Same-schema updater rejects additive artifacts even at an already-current target head. This is metadata groundwork only; migration orchestration/protected dispatcher/production release remain unqualified. |


| 2026-09-29 | Passport image ZIP exports (delegated owner, root registered) |85 focused regressions,3 actual PostgreSQL races and1 official-SDK/proxy/TCP verified-delivery case pass;6-source mypy/Ruff and87 backend budgets pass. | All/incremental group and exact selected IDs, shared website byte parity and delivery-only history. Contract in `mcp-image-exports.md`; production storage/Codex/capacity and broader Phase4 remain open. |
| 2026-09-29 | WhatsApp header media (delegated owner) |19 HTTP/SQLite and3 actual PostgreSQL tests pass;4-source mypy/Ruff pass. Connector checkpoint81 tests passes followed by30 targeted header tests including8 added cases. | Grant/agency/broadcast-bound JPEG/PNG upload, exact selected local file, dual capability preflight, checksum bounds, unknown retention and explicit ready recovery. No message send or production provider claim. |
| 2026-09-29 | First-party normal-send recovery (coordinator) |240 WhatsApp React tests (42 new request/persistence tests and2 new composer controls),104 contract tests, TypeScript/ESLint and40 frontend budgets pass. | All four browser callers use stable request/body/media identity and same-tab session recovery. Changed uncertain draft requires explicit separate-send choice; no automatic expiry. No mobile broadcast-send caller found. Joined backend/provider qualification remains separate; contract in `whatsapp-normal-send-recovery.md`. |
| 2026-09-29 | Release/upgrade checkpoint (root owner) |0120 header-media schema applied; focused populated migration/guard/lock-timeout/history proof1 passes in23.15s. Release/manifest qualification reports41 passed and1 platform skip. | Windows connector gate and signed wheel/lock/readme inventory packaging added; no local CI run or signature created. Source release remains0113. Source now includes0121 normal-send intent migration; its newer populated upgrade proof is not implied by the0120 result. |
| 2026-09-29 | Native connector vault correction (root owner) |Actual synthetic native roundtrip found the pywin32 Unicode/UTF16LE boundary; correction passes19 auth/native tests including fresh-process credential recovery and cross-process named mutex. | The uniquely named synthetic test credential was cleaned. Actual Codex browser OAuth and production credentials remain unverified; no user credential/config mutation claimed. |

| 2026-09-29 | Joined Administration and normal-send browser checkpoint (coordinator) |8 Playwright cases pass in34.9s:5 MCP Administration cases plus desktop/mobile image invitations and actual lost-response/page-reload recovery. |Same send key/body and one image upload asserted. Six Files/Tools screenshots at1440/768/390 saved and visually inspected; no horizontal overflow or overlapping actions. All HTTP effects used isolated fixtures, no real provider/account/Codex. Temporary webpack config removed and harness server stopped. |

## Source-reviewed adapter hazards

These are confirmed implementation effects, not hypothetical risks. Future safe
adapters must test them before classifying their enclosing workflow as supported.

| Existing workflow | Confirmed effect | MCP adapter requirement |
| --- | --- | --- |
| Client-group broadcast configuration | `client_groups.py` deletes omitted `ClientGroupWhatsAppBroadcastLinkModel` rows and may cancel queued private delivery. | Add-only link changes with locked current state; never pass a partial replacement list as the whole configuration. |
| Rooming hotel passenger selection | Even add mode calls `clear_room_plans`; helper deletes room assignments and room rows. Moving a passenger changes existing membership. | Preserve existing plan versions/assignments or reject the variant; blocking only remove mode is insufficient. |
| Meal-plan regenerate | `menu.py` deletes all current `MealPlanEntryModel` rows before inserting the replacement arrangement. | Generate a separately retained version/plan; do not expose existing regenerate directly. |
| Same-filename document replacement | `document_distribution_replacements.py` deletes old document rows and schedules storage cleanup after retaining delivery history. | Add a retained document/version path or reject filename replacement; preserved delivery history alone does not satisfy source-document retention. |
| GC announcement update | `gc_app_content.py` deletes existing draft versions before creating the next draft. | Retain drafts/history or reject replacement of an existing draft; update is not intrinsically safe. |
| Manager/staff group assignment | `admin.py` deletes existing `ManagerGroupAccessModel` rows before applying the assignment list. | Add access under a lock and retain membership/history; omitted rows must not revoke access. |
| Broadcast support-contact edit | `whatsapp_groups_manage.py` deletes previous support-contact rows during update. | Add contacts or retain versions; do not expose the replacement update unchanged. |
| GC App feature/access and retention configuration | Disable/revoke modes can request purge; platform settings can schedule automatic archive/purge. | Enforce safe variants explicitly and test retained data; setting changes are not intrinsically safe. |

Lifecycle integration: `create_application` currently uses startup/shutdown
handlers for malware-scanner readiness, mobile realtime and recovery loops.
Introducing a custom ASGI lifespan must explicitly preserve these handlers.
Opaque MCP credentials require their own limiter identity/policy; existing
dashboard JWT-derived rate limits are not proof of per-connection enforcement.

| 2026-09-29 | Additive application access (coordinator) |34 SQLite/SDK/web tests,6 actual PostgreSQL races,4-source mypy, Ruff and87 budgets pass. |Exact scoped staff/manager additions, full retained-assignment revision, fresh MFA on mutation/replay, current entity bindings and website replacement locks; contract in `mcp-access-additions.md`. No phase completion. |
| 2026-09-29 | Tracking export qualification (delegated owner) |102 backend tests,3 PostgreSQL races,1 SDK/proxy/TCP delivery plus6 artifact regressions pass. |Group WhatsApp tracking with eight filters; contract in `mcp-tracking-exports.md`. Separate broadcast-only, rooming and menu exports remain open. |
| 2026-09-29 | Final normal WhatsApp lifecycle checkpoint (delegated owner) |159 affected tests,14 actual PostgreSQL cases,12-source mypy/Ruff and87 budgets pass. |Exact template/header-media/website-idempotency/reminder behavior with mocked provider I/O. Success is submitted, never inferred delivered. |
| 2026-09-29 | Connector and schema checkpoint (root owner) |91 connector tests including actual native Windows vault cross-process read and named mutex; migration/admin6 PostgreSQL cases through0121. |Native synthetic credential cleaned; real Codex/browser OAuth and production provider flows remain open. Final package evidence in `mcp-connector-qualification.md`. |
| 2026-09-29 | Authenticated VPS read-only baseline (root collector) |`outputs/mcp-vps-baseline-20260929T1823Z.json`: revisiona18d236f, schema0113, MCP absent; physical16,769,044,480B / available9,468,706,816B, no swap;25 connections,20 application, max100. |236 host containers:64 project including stopped history,172 unrelated. Backend2.16GiB/2.5GiB (86.42%) with4 web workers: host RAM does not establish cgroup capacity. SSH stdin collector created no remote files and changed no resources. No container cleanup or load qualification. |

| 2026-09-29 | Read-only live readiness/runtime role follow-up (root collector) |`outputs/mcp-vps-runtime-20260929T1828Z.json`: HTTP200 ready, database and all five required capability probes available; seven runtime privilege guards pass. |Backend cgroup current2,329,972,736B/max2,684,354,560B; peak2,691,198,976B; max events53,533, OOM and OOM-kill0;99 PIDs. About338MiB current headroom and retained limit-pressure evidence; no combined-load/capacity claim. No remote mutations. |

| 2026-09-29 | Refined live container/cgroup baseline (root collector) |18:32 UTC snapshot:20 running project services,44 stopped project and172 stopped unrelated containers; all running limits finite, totaling13.5625GiB. Nginx baseline has151 OOM and3 OOM-kill events. |These are retained pre-existing events, without individual timestamps. Require zero NEW increments during qualification. About56MiB declared budget remains after2GiB host reserve; backend limit increases need whole-host qualification. No restart/delete/change performed. |
| 2026-09-29 | Current schema/capacity harness (root owner) |Local populated upgrade through0122_mcp_gc_push passed27.17s, including retained-origin downgrade refusal and SQL hash constraint;19 harness tests and actual canonical100/1500-row Excel content checks pass. |Source release remains0113. Large cohort reads5000 but export selects1500 under shared ceiling;100-row cohort exports whole group, complete identity multisets checked before acknowledgement. Combined container workload remains unrun. |
| 2026-09-29 | Hotel rooming/check-in exports (delegated owner, root registered) |19 focused/83 combined backend tests,3 PostgreSQL races,2 SDK/TCP plus6 artifact tests; scoped checks pass. |Canonical rooming-list/check-in workbook generation and verified artifact delivery. No allocation/check-in/history/message mutations. Contract in `mcp-rooming-exports.md`; other export families remain open. |

| 2026-09-29 | Additive group/broadcast links (coordinator) |61 combined tests (30 new relational/SDK,31 shared mobile/source regressions),4 PostgreSQL races,6-source mypy, Ruff and87 budgets pass. |One exact association; complete source/mobile preflight before insert-only writes, every existing destination/session/private delivery retained, canonical no-cancel lock and exact revision. Actual5001-row bound case. Contract in `mcp-broadcast-link-additions.md`; no provider sends or phase completion. |

| 2026-09-30 | Diagnostic collector/mount increment (coordinator) |64 backend tests plus2 existing diagnostic HTTP cases;18 operator tests pass with1 Linux-only subprocess case skipped;7-module mypy/Ruff pass. | Exact local Compose source binding, bounded sanitized streams, exclusive sealed runs, freshness/integrity and optional read-only mount. No live collection or activation; `mcp-diagnostic-collector.md` records limits. |
| 2026-09-29 | Migration identity/default-grant qualification (root owner) |Disposable PostgreSQL migration-role proof passed8.46s through0122 under migrator with no subsequent GRANT. Read-only production catalog checks at19:02:45UTC verify all six existing ownership/default-privilege guards. |Source remains0113. No blind role reprovisioning required by this evidence; actual candidate-head ownership/grants still must pass after migration. No production role/data/config changes. |
| 2026-09-29 | GC authored push checkpoint (delegated owner) |94 combined push/draft/native/web regressions and11 actual PostgreSQL races;11-source mypy/Ruff and87 budgets pass. |Four typed draft/plan/confirm/inspect tools, at most10 groups/100 people/300 devices,20-target native waves and original-grant dispatch fencing. All providers fake; real push/Codex/production remain open. |
| 2026-09-29 | Whole-project OOM capture and Linux export lease (root owner) |Capacity contracts26 pass; all isolated container identities/cgroup counters captured before/after. Pure Linux lease proof4 checks passes, source-hash bound, Python3.12.3; peak RSS parent23MiB/child17MiB under96MiB address-space caps. |Unchanged historic OOM counters allowed; new increments, replacement/restart or missing evidence fail. Pure kernel test created only new retained isolated helper lock; no app/data/container workload. Combined Docker capacity remains unrun. |
| 2026-09-29 | Strict-retention release metadata checkpoint (root owner) |348 release/static tests pass with1 platform skip. Signed additive contract retains existing containers, source/business files, backups and helper artifacts; cleanup prohibited. |Existing Compose activation can remove replaced containers, so it cannot supply the no-removal executor. Protected migration/activation/forward-repair execution remains unqualified. |

| 2026-09-30 | Streaming MCP HTTP contracts (coordinator) |102 combined transport/PDF/contact/header-media/frontend-error/OpenAPI tests pass41.81s;4-source mypy, scoped Ruff and87 budgets pass. Canonical backend contract and unchanged mobile projection checks pass; inventory1493 surfaces/68tools/423OpenAPI with12 drift tests. |Required bearer security,201 uploads, raw body/header schemas, typed receipts/errors and binary download headers match runtime. Duplicate/lowercase/empty/dashboard credentials reject before body read; streaming unchanged. Backend diagnostic route list now matches two MCP Administration pages. |
| 2026-09-30 | Release-first user steering (root relay) |User authorized a minimum stable direct VPS deployment before CI, followed by completion of the remaining eight-phase work. |Keep all existing production resources/files/data and fixed SSH-key expiry. Direct release execution still needs its concrete backup, writer fence, exact migration, resource/admission and recovery checks; no full-phase completion is inferred from minimum deployment. |
| 2026-09-30 | GC announcement additive drafts/revisions (delegated owner) |21 integration/SDK/website regressions,5 PostgreSQL append/concurrency/website-push races plus1 identity-refresh group-first regression;3-source mypy/Ruff/budgets pass. |Append-only draft/version creation with shared website policy; first-publication development deferred under release-first steering. No production/provider claim; evidence in mcp-gc-announcement-checkpoint.md. |
| 2026-09-30 | Direct-release database and retained cutover components (coordinator/root) |9 database unit tests and1 actual PostgreSQL16.15 archive/hash/lock-failure/upgrade/retry proof pass17.20s;27 direct container/build/activation/cgroup mocked tests pass. Scoped Ruff clean. |Fresh source-bound backup, exact0113-to0122 chain under existing migration owner, no automatic downgrade or deletion. Explicit source-only recovery, whole-host admission and cgroup comparisons added; live direct deployment and full eight-phase gates remain open. See `mcp-additive-release-contract.md`. |

## Live minimum-release checkpoint — 2026-09-30

This appended checkpoint updates the earlier pre-deployment observations; it does
not mark any of the eight phase acceptance gates complete. The root operator
reported successful retained receipt
`journal/0248-direct-release-live-verified.json` under
`/opt/GlobalConnectsDashboard/tmp/mcp-direct-efea4e4ac199b65fbf4f3b76a1ed59c4c963bd7e`.
Its exact observation time is `2026-09-29T20:52:25.162046+00:00`
(30 September 2026, 02:22:25 IST).

- Live application source is
  `efea4e4ac199b65fbf4f3b76a1ed59c4c963bd7e`. All nine migrations from
  `0113_document_follow_up` through `0122_mcp_gc_push` were verified after the
  writer fence and a validated full PostgreSQL custom archive. Archive validation
  does not establish a production restore rehearsal.
- All 12 replacement application services are healthy, with zero restarts and
  zero new OOM events in the verified startup window. Public liveness, readiness
  and OAuth protected-resource metadata returned HTTP 200 from the VPS and
  Windows. The email heartbeat arrived on its normal 60-second schedule. This
  does not establish sustained or combined-load capacity.
- Active bindings are retained in `images-runtimefix.json` and
  `candidates-forward1.private.json`. The project label remains
  `mcp-direct-efea4e4ac199-runtimefix`; active names use its `-fwd1-<service>`
  suffix, while network aliases remain `-<service>`. Full secret-free mapping is
  recorded in `mcp-direct-release-checkpoint.md`.
- The original project's 12 application containers are stopped and retained;
  its eight infrastructure services remain in place. Original source revision
  `a18d236f15bd96ea326fe436cdcc28af60ec17b0`, images, files, business data, failed
  candidates, helpers and backups remain retained. The failed earlier runtimefix
  worker has restart disabled. New backend-based containers explicitly clear the
  image entrypoint to preserve the original intended service command.
- MAIN/operator revision `e92f086e03e73593b8dc05919fed064f13b02a31` contains the
  subsequent operator corrections; deployed application source remains the exact
  `efea4e4a` revision. Latest reported checks are 53 direct-helper tests and a
  focused 6-case container suite, each passing; these counts are not summed into
  a distinct combined total.
- Live Administration / MCP is visible to the signed-in superadmin. Runtime
  capability admission is only `mcp:read` and `mcp:export`, with only
  `passport_excel`, at most 100 source rows per family and 1 MiB cumulative
  database-measured source text. At this checkpoint the database control remains
  disabled pending human recent-MFA verification. Browser OAuth, connector
  authorization, real Codex calls and verified live export remain unqualified.

The retained original checkout and application containers expect schema 0113.
Do not use normal Compose activation from that checkout or restart those old
application clients against the now-upgraded schema 0122. It can introduce
incompatible or duplicate writers and recreate retained containers. Maintenance
must use the exact active bindings above; recovery after migration requires a
qualified forward repair. The earlier guarded source-schema recovery is no
longer applicable. All eight phases remain open, including remaining workflow
coverage, real Codex/file delivery and combined-load qualification.

### Post-cutover qualification follow-up — 2026-09-30

At `2026-09-29T21:12:50.298841+00:00`, all 12 replacement application containers
and eight original infrastructure services were running. All ten configured
application Docker health checks were healthy; frontend and Nginx have no Docker
health check and passed their public HTTP checks. API liveness, full readiness,
OAuth resource metadata and the MCP page returned HTTP 200. Replacement cgroup
OOM counters and restart counts remained zero after approximately 20 minutes.
This is an observation window, not representative combined-load qualification.

The final frozen broad Windows backend regression reports **5,805 passed,
3 skipped, 285 deselected, 162 subtests passed**, exit zero in 737.98 seconds.
All three skips require Linux fork/path behavior; the deselected tests belong to
the separately run service-integration lane. Backend source is unchanged from
the deployed `efea4e4a` revision. Retained log/JUnit artifacts are
`outputs/backend-regression-20260929T2107Z.log` and its `.xml` sibling. This
closes the earlier aggregate regression gap after the eleven targeted fixes.

Operator commit `82d503c5` additionally has 67 passing joined direct-helper tests.
Future builds commit explicit runtime image configuration and verify the result,
with a bounded 120-second commit timeout and no automatic uncertain retry. Those
Docker tests are mocked, and no new application build/deployment is implied.

Connector 0.2.0 is installed independently of the worktree under
`%LOCALAPPDATA%/GlobalConnects/mcp-connector/0.2.0` with hash-checked dependencies
and the recorded wheel checksum. Its native vault is accessible and has no
authorization yet. The signed-in website is displaying the real recent-MFA
dialog; human verification, OAuth, Codex configuration and the actual live
read/export proof remain pending. No phase is marked complete by this follow-up.


### Actual Codex recovery and forward backend — 2026-09-30

This supersedes the prior pending-authorization and EF backend state above.
The user completed recent MFA, enabled MCP and authorized the named desktop
connection; the installed connector stores its credential in Windows Credential
Manager. Actual Codex first demonstrated production reads, then retained a queued
Excel export after the deployed storage SDK rejected its conditional-write
parameter. The source correction is pushed to main through45dded23 and deployed
as exact backend revisioncd0e538f, retaining schema0122, frontend/workersEF,
read/export-only controls,100-row/1MiB limits and all prior resources.

At22:12:26UTC on29 September, all20 services and ten configured application health
checks passed, public routes returned200, and all prior containers/images were
verified retained. Actual Codex run4 resumed the original operation
13ffbc2f-34b1-434b-b432-3513e74cd8c7 without a new key. Download checksum and server
delivery acknowledgment passed; independent ZIP CRC and openpyxl parsing passed
for the14,863-byte workbook. Exact hash, immutable runtime bindings, private safe
evidence paths and limitations are in[mcp-live-codex-checkpoint.md](mcp-live-codex-checkpoint.md).
This proves the first saved Excel recovery/delivery case, not full export parity
or phase acceptance.

The storage SDK/MFA correction has81 focused SDK/storage/export tests, eight safe
diagnostic tests and nine real PostgreSQL authority races passing. The initial
full backend run had5,821 passes and one test-ordering failure; that test now uses
exact token identities and its six-test file passes. The clean full rerun then
passed5,822 tests,3 Linux-only skips,294 service-integration deselections and162
subtests in863.68 seconds. Fifteen additional local HTTP authority tests and six
mocked-API UI connection-state tests pass separately, outside that aggregate. The capacity harness now matches the current minimum export profile;
36 focused tests pass, with serialized export waiting included in unchanged
latency limits. No combined workload has run, and the existing disposable Docker
stack helper remains incompatible with production retention requirements.

All eight phase gates remain open. The overnight authorization preserves MFA,
existing credentials, the original SSH expiry and all retained resources, and
allows no additional customer messages. No fresh-factor live roundtrip is
claimed for the durable dashboard MFA fix while the user is asleep.

The existing authenticated production browser separately showed the exact saved
operation as `succeeded` and its 14,863-byte file as `delivered`, without another
MFA prompt. The active group overview passed responsive checks at1440,768 and390
pixels: overview heights210,431 and653 pixels, with three columns, two-plus-one,
and a single column respectively; no horizontal overflow was observed. Trip
details expanded and collapsed, the viewport was restored, and the temporary
group tab was closed. Safe receipt:
`outputs/mcp-live-browser-readback-20260929.json`. The archived export group is
outside the active website listing; layout verification used the active group
reached through All Groups. No source/passenger contents were retained in this
receipt, and no messages or business updates were submitted.
