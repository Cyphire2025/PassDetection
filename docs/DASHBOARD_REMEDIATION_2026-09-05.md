# Dashboard remediation and release review — 5 September 2026

This change set responds to `outputs/dashboard-audit-2026-09-05.md` and the requested dashboard redesign. It starts from source commit `4a90d422a85a92d0a8a7ae9d672ea46de9f688c7`, described by the user as the production version, and is verified and published on `codex/dashboard-enterprise-20260905`. No production deployment, customer-data access, or live provider message is part of this work.

## What changed

The dashboard now uses a consistent workspace shell, restrained page headings, responsive navigation, accessible loading/error states, and practical settings. Appearance controls change real table spacing, content width, text size, motion, and sidebar width; they persist only presentation preferences. Platform policies, account/security and data administration retain their authorization, revision and destructive-action protections.

Search/filter changes preserve authoritative selection until the operator clears or deselects it. Matching/visible selection adds to the existing set. This includes passport records, tour assignments, rooming and WhatsApp recipient selection. Phone search understands formatted numbers. Global search supports cancellation, keyboard access, retry, and distinct empty/error states.

Notifications and the operational inbox keep a live first page separate from historical browsing. Historical pages no longer multiply repair polling, and loading history cannot evict all new messages. Malformed feed responses become query errors instead of crashing the shared header. Rooming lists render a bounded page of passengers.

The oversized route/page modules now have explicit ownership boundaries and ordinary static composition. There is no runtime source execution, mutable module proxy, or circular compatibility shim.

| Requested module | Before | Composition entry after |
| --- | ---: | ---: |
| Backend passport routes | 6,417 | 457 |
| Backend document distribution routes | 3,850 | 374 |
| Backend WhatsApp routes | 3,504 | 525 |
| Frontend passport-group detail | 2,200 | 22 |
| Frontend message activity | 2,073 | 315 |

The passport route modules are at most 638 lines. Explicit size/complexity ratchets cover 65 backend modules and 24 frontend modules. These ratchets prevent growth beyond reviewed limits; line counts alone do not establish software quality.

See [passport boundaries](architecture/passport-dashboard-boundaries.md), [messaging/document boundaries](architecture/dashboard-messaging-document-boundaries.md), and [dashboard state ownership](../frontend/docs/dashboard-state-ownership.md).

## Audit disposition

| Finding | Local remediation and evidence |
| --- | --- |
| S01 — vulnerable native decoder/framework | Next 16.3.3, sharp 0.35.4 and pillow-heif 1.6.0; actual Linux images report libheif 1.23.2. Public upload capability is checked before decoding. |
| S02 — stored refresh digest accepted | Hash-only lookup/atomic consumption; digest-shaped credentials rejected. Additive 0089 migration revokes legacy plaintext rows without reviving them on downgrade. |
| S03 — OAuth browser binding | Separate short-lived HttpOnly provider nonce is bound to initiating user and session generation. The callback rechecks account/agency/generation under a short lock after provider exchange and before persistence. |
| S04 — closed public capability | Public upload, status, image, document, retry, reconciliation and discard access consistently reject unavailable group lifecycles. |
| S05 — logout-all access tokens | Session generation is advanced and refresh rows revoked together. Locked security reads refresh ORM state so a concurrent fence cannot increment a stale generation. |
| S06 — private Docker context | Explicit runtime COPY allowlist and defensive context exclusions. Release-image checks found no debug, test, output or project virtual-environment directories. |
| S07 — storage administrator credentials | Production Compose requires separate administrator and application credentials. The bucket-scoped policy passed a disposable local allow/deny rehearsal, including denied cross-bucket and administrator operations. Provisioning/rollback instructions are included; actual production IAM provisioning remains an operator step. |
| R01 — broadcast retry transaction | Immutable identifiers survive rollback; rows are explicitly reloaded. Interrupted-batch regressions preserve completed recipients and continue remaining work without duplicate synthetic sends. |
| R02 — uncertain import commit | Commit attempts are distinguished from pre-commit failures. Fresh reference checks and durable cleanup retain objects when the commit outcome is uncertain. |
| R03 — inconsistent operational roster | A shared tenant/group SQL predicate applies rejection/replacement decisions to current exports, document delivery, attendance, rooming and QR eligibility. Historical evidence remains. |
| R04 — stranded extraction intent | Intent commits with imported records, followed by publication and bounded autonomous recovery using leases and retry limits. |
| P01 — blocking/quadratic exports | Workbook work is off the request loop, total exported rows are bounded, and repeated max-row scans are replaced by counters. |
| P02 — full-record roster hydration | Narrow identity projections preserve duplicate semantics; full DTOs hydrate only for the selected page/cluster, with repeated visibility/version checks. Projection work still scales with group size; this is not constant-cost SQL pagination. |
| P03 — synchronous broker publication | Blocking publication runs outside the async request thread while preserving durable intent and queued-only compensation. |
| P04 — notification history polling | Live-head polling is independent of bounded on-demand history. |
| P05 — inbox live head eviction | The latest messages remain available independently of historical pages. |
| P06 — session restoration | Explicit restoring/authenticated/rejected/unavailable states and a safe restoration entry preserve valid refresh sessions. Initial null-user rejection and activation-token StrictMode replay defects are also fixed. |
| P07 — misleading search failures | Errors have explicit retry UI. Real SQL regressions also fix the JSON accessor that caused global and passport-list search to return HTTP 500. |
| P08 — expanded rooming rendering | Passenger tables render 50-row pages with selection independent of the current page/filter. |
| O01 — request-protection readiness | Required security Redis is a readiness capability. A local outage rehearsal checks liveness, failed readiness and recovery; bounded probe verification is included in the final evidence. |
| O02 — resource isolation | Explicit CPU/memory ceilings, Redis memory limits and reduced default extraction concurrency. A preflight checker rejects unsafe/malformed budgets and is covered by 14 offline tests. |
| O03 — recovery evidence | A populated local PostgreSQL backup/restore and forward-upgrade rehearsal passed. Off-host backups, real alert delivery, production failover and recovery objectives remain unverified. |

Additional review fixes include stale WhatsApp previews that could approve the previous draft; malformed notification responses; a GC group-control query with ambiguous joins; mobile tab visibility; narrow document tables and clipped action menus; audit-card overflow; and patched pypdf 6.16.1 for the three additional PDF denial-of-service advisories.

## Performance evidence and limits

Three-run synthetic exporter medians, using identical workbook values/styles/extents:

| Rows | Original | Updated |
| ---: | ---: | ---: |
| 800 | 0.462 s | 0.218 s |
| 1,500 | 1.015 s | 0.321 s |
| 3,000 | 3.347 s | 0.592 s |

The 3,000-row case directly stresses the exporter beyond the route's 1,500-row limit. A real in-memory SQLite projection/page experiment with 8 KiB of synthetic excluded metadata per record reduced peak Python allocation from 44.88 MiB to 4.49 MiB at 3,000 records, hydrating 50 ordinary unique-passenger DTOs. Whole duplicate clusters intentionally remain together and can exceed the requested page size. These measurements are not production PostgreSQL throughput or provider latency.

PDF work now closes native handles deterministically, bounds native text/render allocation, uses native text before sparse-page OCR fallback, shares exact-duplicate classification within a batch, and normalizes equivalent glyphs without guessing ambiguous passport characters. Existing matching and uncertainty behavior is preserved. No claim of universally better OCR accuracy is made without a labeled representative production corpus.

## Local verification record

The subsequent [PDF upload and dashboard copy follow-up](DASHBOARD_UPLOAD_FOLLOWUP_2026-09-05.md) repairs the local review stack's disabled ingestion, enables real ClamAV, fixes scanner startup and error classification, and records the requested sidebar/copy changes. Its focused API/browser checks and refreshed source/image fingerprint supplement the broader verification below.

The final ordinary backend suite passed on Python 3.11.15 with pypdf 6.16.1: **2,537 tests and 126 subtests passed** in 133.50 seconds. The 12 service tests skipped by that run were then explicitly enabled against separate disposable PostgreSQL, Redis, object-storage fixtures and a real Celery worker: **12 of 12 passed** in 21.51 seconds on the final backend image's Python 3.11.16. The full coverage run and a successful 123-test late-regression append produce **74.50% backend line coverage** across 538 modules (43,547 of 58,455 executable lines). All original coverage hits were retained, and all 65 reviewed module floors passed. Evidence is retained under `outputs/dashboard-qa` and in `outputs/dashboard-backend-final-tests.log`.

Evidence already completed:

- Passport API comparison: 46 paths/50 operations with unchanged schemas and route order. WhatsApp: 20 endpoints; document distribution: 13 endpoints, unchanged contracts.
- Latest changed passport/auth domain union on Python 3.11: 607 tests plus 46 subtests passed.
- Patched PDF/document/rename/ticket/visa corpus: 291 tests passed on both Python 3.11 and 3.13, including real nested/repeated PDF Form XObject fixtures.
- Real global search: 10 SQLite tests and 11 isolated PostgreSQL checks passed.
- GC group-control query: 11 tests passed, including a real database query.
- Frontend interaction suite after the responsive table/menu fixes: 41 files/155 tests passed. Browser journeys: 15 passed. Node contracts: 659 passed.
- Frontend type checks, zero-warning lint, 24 module budgets and configured interaction coverage floors passed. Coverage is 89.12% statements, 74.66% branches, 89.28% functions and 92.36% lines within the configured critical-component scope; those figures do not describe the entire frontend.
- Backend application types: mypy passed across 538 source files. Full backend application/test Ruff, compile checks, Alembic topology, Compose contracts, CI supply-chain policy, and the 14 resource-preflight tests passed.
- Populated PostgreSQL rehearsal: 522,037-byte backup, matching restored snapshots, 12 preserved table inventories, successful 0085 → {0086,0087} → 0088 → 0089 upgrade, clean Alembic model comparison, and integrity constraints verified. Both temporary databases were removed; the browser database was unchanged.
- The separate real-service lane also passed topology, fresh migrations, Alembic model comparison, and a real prefork Celery worker control ping before running its 12 tests. Its uniquely created containers, database, bucket and image aliases were removed without cleanup errors. Evidence: `outputs/dashboard-qa/service-integration/manifest.json` and `tests.log`.
- The rendered storage policy passed 21 local assertions with a disposable restricted application user: required bucket/object operations succeeded; six cross-bucket operations returned HTTP 403; server, policy and user administration returned explicit `AccessDenied`; other-bucket fixture contents remained unchanged. Cleanup reported no errors. The MinIO CLI returned exit 0 for one denied admin operation, so the structured response body was checked instead of trusting the exit code. Evidence: `outputs/dashboard-qa/service-integration/minio-policy-results.json`.
- Docker Desktop and the actual browser were inspected using Computer Use. All 42 dashboard route patterns were rendered at desktop and mobile widths with synthetic fixtures. Lower panels were also captured and reviewed; the mobile defects discovered there were corrected and recaptured.
- All 11 live controls passed with zero browser exceptions or API errors: computed styles and reload persistence, all four settings sections, global search and result navigation, passport selection, formatted WhatsApp number search, retained custom-recipient selection, mobile navigation, document-table/menu reachability, and audit-card bounds. No send, deletion or platform-policy mutation is part of this smoke test.
- In the rebuilt Docker backend, stopping the isolated security Redis changed readiness to HTTP 503 with `request_protection.available=false` in 3.156 seconds. Liveness remained HTTP 200; readiness recovered to HTTP 200 after restart. Delayed-probe tests also prove the bounded executor does not accumulate unfinished jobs during repeated timeouts.
- Dependency audit: the frontend reports no known vulnerabilities. The backend reports no known vulnerabilities after its one existing, explicitly documented `ecdsa` exception (`PYSEC-2026-1325`); this is not an exception-free audit.

Browser evidence uses a dedicated `passdetection-audit` project and synthetic accounts, groups, message metadata and document placeholders. No external provider keys are configured. Existing local containers were stopped gracefully and their volumes preserved. The QA stack uses development backend settings and background processing with the production frontend build; it does not reproduce every production worker/provider/security setting.

An initial full coverage run exposed three export tests still patching the old facade after decomposition. Their mock targets were moved to the owning module; 77 related tests passed and the complete final ordinary suite above was rerun successfully. The initial failing log is preserved for traceability and is superseded by the final run.

The final coverage append also verified the readiness batch timing regression with ordinary logging enabled. The test permits instrumentation overhead for 21 concurrent responses while still requiring bounded unfinished jobs and fail-closed results. The separate Docker outage measurement above records actual request latency. Files labeled `first-attempt` are retained diagnostic history and are superseded by final evidence.

The running local review UI is available at `http://127.0.0.1:3200/settings`; synthetic review credentials are stored only in the ignored `outputs/dashboard-qa/synthetic-seed.json`. The visible browser is already signed in to that synthetic workspace.

Selected visual evidence: [settings](../outputs/dashboard-qa/visual/32--settings.png), [successful global search](../outputs/dashboard-qa/controls/global-search-passenger.png), [open mobile document menu](../outputs/dashboard-qa/controls/document-lane-1-mobile-menu.png), and [mobile audit cards](../outputs/dashboard-qa/controls/mobile-audit-card-bounds.png). The complete route inventory and rendering evidence are in `outputs/dashboard-qa/visual/render-results.json`; live control assertions are in `outputs/dashboard-qa/controls/results.json`.

`scripts/qa/dashboard_release_evidence.py` records SHA-256 fingerprints for the final modified/new source files, the unchanged starting Git HEAD, and the actual running image IDs in `outputs/dashboard-qa/release-evidence.json`. Both runtime images run as UID 1001, contain patched libheif 1.23.2, and pass the checks for excluded local debug/test/output/environment artifacts.

## Review and rollout requirements

This is a feature-branch release candidate, not a production certification or a guaranteed AI rating. Review the patch and run the repository CI before merging to main.

A final read-only check found the GitHub feature branch absent before its first publication, so there was no feature-branch divergence to reconcile. The source fingerprint manifest identifies the reviewed candidate published on `codex/dashboard-enterprise-20260905`.

Before deployment, follow [the production release procedure](PRODUCTION_RELEASE_READINESS.md): provision/test the bucket-scoped application storage identity; supply separate MinIO administrator credentials; confirm host capacity and actual worker concurrency; take and test the release backup; then apply migrations and application images in the reviewed order. The rendered default service ceilings total 20.875 GiB; adding a 2 GiB host reserve passes at 24 GiB and fails at 16 GiB. This is an arithmetic envelope, not measured capacity. The local reduced QA stack fits the separate Docker Desktop allocation.

The pinned MinIO community image also needs an explicit maintained-distribution/provider and patch-owner decision. Off-host restore, real provider callbacks and delivery, physical devices, production load/latency, monitoring/alert reception, and failure recovery remain distinct release evidence. Neither passing local tests nor a favorable automated review establishes those facts.
