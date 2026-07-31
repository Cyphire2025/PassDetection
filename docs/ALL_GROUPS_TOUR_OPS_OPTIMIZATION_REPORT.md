# All Groups and Tour Ops Production Engineering Report

Date: 31 July 2026

Scope: the All Groups list, group detail, individual passport pages, and Tour Ops workflows. This report covers the current worktree only. Nothing in this change set has been staged, committed, deployed, or applied to production data.

## Executive summary

The two requested feature areas were optimized and hardened without replacing their workflows or removing existing capabilities.

The main results are:

- All Groups now has an additive, tenant-scoped server-pagination API and a 50-row UI page size instead of requiring every group summary in one response.
- Duplicate/submission clustering was changed from a quadratic pair scan to linear bucket construction. At 5,000 synthetic submissions the median processing time fell from 1,252.57 ms to 93.87 ms, a 13.34x speedup.
- Archived groups are explicitly readable but fail closed for operational mutations. Active and closed groups keep their existing write behavior.
- Group lifecycle checks now lock the exact agency-owned row in mutation paths, closing archive/write race windows and archived-to-closed bypasses.
- Non-super-admin exports now exclude deleted and soft-deleted groups even when a caller knows an object ID. Super-admin Old Data access remains intact.
- Cookie-authenticated mutations in the scoped group, passport, Tour Ops, QR-delivery, and hotel-scanning routes now require the existing CSRF control. Bearer-token API behavior remains supported.
- Tour QR generation is lazy-loaded, bounded to four concurrent render jobs per component, cancellable, failure-isolated, and cached only in component memory with passenger-and-payload keys.
- Offline Tour Ops storage was reduced to the minimum operational passenger projection. Rejected attendance events no longer retain QR bearer secrets or full passenger snapshots, and IndexedDB v4 rewrites legacy records.
- The verified Tour Ops family-size defect was fixed by counting the submitted family within its agency and group instead of always returning one.
- Fixed-cardinality timing/count metrics were added to the group-summary and group-submission-view hot paths without passport, email, tenant, or user identifiers.
- All backend unit/integration tests, all frontend tests, lint, frontend type checking, the production build, and scoped security checks pass.

No database index or schema migration was added. Production-like PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` evidence was not available, so adding an unverified index would have introduced deployment and write-amplification risk.

## Preserved behavior and compatibility boundaries

- The legacy group-summary endpoint remains available; the paginated endpoint is additive.
- Existing tenant, manager-owner, staff-assignment, and super-admin visibility rules are retained.
- Closed groups retain their intended operational behavior.
- Archived groups remain accessible through explicit archived/history access, but cannot be reopened indirectly by a mutation.
- Permanent deletion and explicit restoration remain deliberate lifecycle exceptions.
- Super-admin Old Data access to retained deleted records remains available.
- Search, status, group, and destination filtering remain available. The UI now requests filtered pages from the server.
- The 30-second group metadata refresh is preserved.
- Public upload and retry flows retain their token-based workflow, with a locked lifecycle validation added before mutation.
- No user-facing layout redesign was made. Heavy dialogs/editors and the QR library now load on demand.

## Architecture and code-quality improvements

### All Groups and individual passport pages

- Added a focused page DTO, schema, repository contract, use-case method, and API endpoint rather than extending the legacy all-in-memory response shape.
- Centralized group lifecycle authorization in `AuthorizationPolicy` and the client-group route guard.
- Added row-lock support to the client-group repository so lifecycle validation and mutation share one transaction boundary.
- Centralized export lifecycle scoping instead of duplicating status predicates in individual export routes.
- Replaced nested duplicate scans with identity/passport hash buckets while preserving the special handling for incomplete identities.
- Kept sensitive image editors and export dialogs out of the initial route graph through dynamic imports.
- Added focused authorization, lifecycle, repository-query, pagination, and UI contract tests.

### Tour Ops

- Extracted QR rendering into a typed service with bounded workers, abort handling, partial-success reporting, payload-keyed caching, and lazy module loading.
- Extracted explicit offline passenger and rejected-scan projections instead of serializing broad API objects into IndexedDB.
- Added a versioned migration that sanitizes existing offline records.
- Reused the existing CSRF dependency on every audited state-changing Tour Ops route.
- Corrected family-size computation with agency, group, family, and submitted-status predicates.
- Added concurrency, failure, privacy, migration, CSRF, and route-contract coverage.

The React work follows component-scoped caching and lazy-loading guidance: no passport or tenant data is held in a process-global response cache, QR images are evicted when payloads change or passengers disappear, and optional UI code is excluded from initial route entry bundles.

## Performance improvements

### Submission clustering benchmark

Median of five runs using the same pathological synthetic input before and after:

| Submissions | Before | After | Improvement |
| ---: | ---: | ---: | ---: |
| 500 | 21.17 ms | 9.17 ms | 2.31x |
| 1,000 | 67.04 ms | 17.99 ms | 3.73x |
| 2,000 | 217.24 ms | 36.32 ms | 5.98x |
| 5,000 | 1,252.57 ms | 93.87 ms | 13.34x |

The prior algorithm performed pairwise comparisons and degraded quadratically. The replacement constructs lookup buckets in one pass and then resolves only relevant candidate identities, making observed growth approximately linear.

### Route entry JavaScript

Raw and gzip totals were computed from the production build's route client-reference manifests before and after:

| Route | Before raw / gzip | After raw / gzip | Raw delta | Gzip delta |
| --- | ---: | ---: | ---: | ---: |
| Passports list | 327,418 / 99,490 B | 322,942 / 98,370 B | -1.4% | -1.1% |
| Group detail | 481,029 / 141,475 B | 438,519 / 129,319 B | -8.8% | -8.6% |
| Passport detail | 382,934 / 118,105 B | 357,127 / 109,757 B | -6.7% | -7.1% |
| Tour Ops list | 317,479 / 95,271 B | 317,714 / 95,327 B | +0.1% | +0.1% |
| Tour QR page | 346,761 / 106,302 B | 325,278 / 98,144 B | -6.2% | -7.7% |

The 0.1% Tour Ops list change is operationally neutral. The heavier pages benefit from moving the crop editor, export dialogs, and QR encoder out of their initial entry graphs.

### Network, CPU, and memory

- All Groups requests a maximum of 50 summary rows per page and debounces destination filtering by 300 ms.
- Selection is maintained across pages, so pagination does not remove bulk export behavior.
- QR generation has a shared four-worker ceiling for overlapping requests within one mounted component.
- Unchanged QR payloads reuse component-local results; changed/revoked records are pruned.
- QR failures are returned per passenger instead of aborting the complete batch.
- UI updates from QR generation are batched through animation frames.
- Offline records no longer duplicate passport details, MRZ data, extraction confidence, and unrelated API fields.

## Security improvements

### AGTO-SEC-01 — High — missing CSRF enforcement on cookie-authenticated mutations

State-changing group, passport, Tour Ops, QR-delivery, and hotel-scanning routes had inconsistent CSRF dependencies.

Resolution:

- Applied the existing `require_cookie_csrf` dependency to the audited mutation routes.
- Confirmed cross-origin cookie requests fail with 403.
- Confirmed bearer-authenticated API requests retain their intended behavior.
- Left read-only preview/export POST routes unchanged where they do not mutate application state.

### AGTO-SEC-02 — High — archived/deleted lifecycle mutation bypass and race window

Authorization previously proved tenant ownership but did not consistently prove that the group still accepted mutations. In particular, revoking an archived group could transition it to closed, after which passport writes were allowed. Preflight status checks also raced with concurrent archival.

Resolution:

- Active and closed are the only mutable lifecycle states.
- Deleted and soft-deleted records fail closed.
- Mutation checks select the exact group-and-agency row with `FOR UPDATE`.
- Public submit/retry, bulk deletion, Excel import, document save, approval, extraction, image, QR, roster, WhatsApp-link, and related group writes use the lifecycle guard.
- Explicit restore and permanent-delete operations remain controlled exceptions.

### AGTO-SEC-03 — High — retained deleted data exportable by known ID

Selected-passport and selected-group exports were tenant-scoped but did not exclude retained deleted records. A manager or admin who knew a same-tenant ID could bypass the normal deleted-list restriction.

Resolution:

- Applied a shared deleted/soft-deleted group predicate to non-super-admin export queries.
- Preserved super-admin Old Data workflows.
- Added regression coverage for known-ID export attempts.

### AGTO-SEC-04 — High — excessive sensitive Tour Ops offline storage

Offline records and rejected scan events retained broad passenger snapshots and, for rejected events, a QR bearer token beyond the retry need.

Resolution:

- Offline passengers retain only operational ID, name, email, phone, and departure city fields.
- Rejected records retain a secret-free failure projection.
- IndexedDB v4 migrates and rewrites legacy records.
- The service-worker cache version was advanced so stale client assets do not keep the older storage behavior.
- Tests assert removal of passport, MRZ, confidence, and QR-secret fields.

Pending offline scans still require the QR token until synchronization succeeds. That residual is documented below.

### AGTO-SEC-05 — Medium — object lifecycle scoping gaps in read/write helpers

Some helper paths fetched a group without a locked exact-tenant lifecycle check.

Resolution:

- Added optional `for_update` repository reads.
- Used exact group and agency predicates in the authorization policy.
- Added repository SQL and route-level tenant/lifecycle tests.
- No confirmed cross-tenant object access remained in the audited paths.

### AGTO-SEC-06 — Medium — installed-runtime HTTP status constant mismatch

The local installed Starlette 0.37 runtime does not define newer aliases such as `HTTP_422_UNPROCESSABLE_CONTENT` and `HTTP_413_CONTENT_TOO_LARGE`, causing error-handling paths to fail with an attribute error instead of returning the intended status.

Resolution:

- Replaced the affected scoped aliases with the equivalent constants available in old and new Starlette versions.
- Fixed the same verified compatibility failure in the shared error handler, WhatsApp path, and menu path when full-suite validation exposed them.
- The source requirements already pin a current FastAPI/Starlette version; the compatibility names work across both environments.

### Security checks and boundaries

- `npm audit --omit=dev --audit-level=high`: zero findings.
- Direct source requirements audit: zero known vulnerabilities.
- The stale local virtual environment reports vulnerabilities in Starlette 0.37.2 and one no-fix `ecdsa` advisory. Source requirements pin Starlette 1.3.1, but deployment must rebuild from the lock/source requirements rather than reuse the stale environment.
- A full transitive source audit could not resolve on the workstation's Python 3.13 because the production-pinned NumPy 1.26.4 needs a compatible wheel/compiler. It should be repeated in the production Python 3.11 CI image.
- No SQL string concatenation, command execution, unsafe deserialization, path traversal, SSRF, or open redirect was introduced by these changes.
- No sensitive fields were added to logs or metric labels.

## Scalability improvements

- Server pagination bounds All Groups summary response size and frontend reconciliation work.
- Summary filtering/counting now executes in the repository instead of serializing every group before filtering.
- Linear submission clustering eliminates a CPU hot path that became impractical at several thousand submissions.
- Bounded QR generation prevents one large tour group from saturating the browser main thread with unbounded asynchronous encodes.
- Dynamic imports reduce initial parsing/evaluation on the three heaviest pages.
- Minimal offline projections reduce IndexedDB size, structured-clone overhead, and migration cost.
- Component-local QR caching prevents cross-user/cross-tenant leakage and avoids global cache invalidation problems.

## Reliability and observability improvements

- Row locks serialize lifecycle validation with mutations and prevent archive/write time-of-check/time-of-use races.
- QR cancellation prevents stale batches from updating an unmounted or superseded view.
- One QR failure no longer discards successful results from the same batch.
- The cached dynamic-import promise resets after failure, allowing a later retry.
- IndexedDB upgrades sanitize legacy values transactionally.
- Group-summary and submission-view hot paths emit fixed-cardinality latency and count measurements:

  - `passport.group_summaries.query_ms`
  - `passport.group_summaries.returned_count`
  - `passport.group_summaries.total_count`
  - `passport.group_submissions_view.load_ms`
  - `passport.group_submissions_view.loaded_count`
  - `passport.group_submissions_view.build_ms`
  - `passport.group_submissions_view.returned_count`

## Validation results

| Check | Result |
| --- | --- |
| Backend unit suite | 1,140 passed, 4 skipped, 124 subtests passed in 18.17 s |
| Backend integration suite | 6 passed in 3.47 s |
| Backend Ruff lint | Passed for `app`, unit tests, and integration tests |
| Focused backend strict typing | Passed for six changed application-core files with imports skipped |
| Frontend tests | 503/503 passed across 75 files |
| Frontend ESLint | Passed |
| Frontend TypeScript | Passed |
| Frontend production build | Passed; 34 pages built |
| JavaScript syntax checks | Offline scanner and service worker passed |
| Frontend dependency audit | Zero high-severity production findings |
| Git diff whitespace check | Passed |

The final production build wall time was 16.26 seconds versus 34 seconds for the first build, but this is not presented as a product-performance gain because the later run benefited from warm local caches. Route entry bundle measurements above are the comparable artifact metric.

Full backend strict `mypy` remains red with 167 errors across 28 files in the imported legacy graph. Errors directly introduced in the changed route helpers were corrected, and the focused application-core check passes. Repository-wide strict typing is existing technical debt and should be handled as a separate migration rather than hidden inside these features.

## Remaining risks and recommended next work

### Priority 1

1. Group detail still loads every submission for the group and returns complete navigation IDs/expiry-alert context before applying UI paging. Clustering is now linear, but memory and payload remain unbounded for very large groups. The next compatible step is a persisted/versioned identity projection plus server navigation windows.
2. Tour QR retrieval currently performs database mutation and, by code inspection, scales at roughly a fixed query cost plus multiple operations per passenger. Split it into an idempotent batch-generation mutation and a read-only retrieval endpoint, then measure query count in PostgreSQL.
3. Hotel/coordinator assignment paths still contain check-then-insert or replacement race windows. Enforce uniqueness with database constraints and use conflict-aware writes after validating existing production duplicates.

### Priority 2

1. Summary pagination uses offset plus a count query. This is appropriate for the current UI, but deep pages at very large scale should move to stable keyset cursors.
2. Case-insensitive contains filters require production query plans. Add `pg_trgm` or expression indexes only if `EXPLAIN (ANALYZE, BUFFERS)` shows scans at real cardinality.
3. Tour QR WhatsApp preview recomputes nested recipient matches on a two-second refresh. Normalize matches once per response or add a server-side projection.
4. A pending offline attendance scan must retain its bearer token until sync. Minimize retention time, encrypt local storage where the browser deployment model permits, expire stale events, and continue deleting the token immediately after success/rejection.
5. Individual get-by-ID paths should be reviewed for uniform 404 behavior before authorization to reduce object-existence disclosure, even though no IDOR was confirmed.
6. Rebuild and audit dependencies in the production Python 3.11 image. Do not deploy from the stale local virtual environment.
7. Pay down repository-wide backend strict typing and legacy formatting debt in a separate controlled change set.

### Verification not performed

- No production database query plan, load test, or production traffic replay was available.
- No migration was applied.
- No production deployment or smoke test was performed.
- No seeded local environment matching the supplied production screenshots was available for end-to-end visual capture. UI contracts, TypeScript, lint, and production rendering compilation passed, and no deliberate layout redesign was made.

## Files changed and why

### Backend application/domain

| Files | Why |
| --- | --- |
| `backend/app/application/dtos/passport_dtos.py`; `backend/app/presentation/api/v1/schemas/passport_schemas.py` | Add the bounded page result contract without changing the legacy response. |
| `backend/app/application/use_cases/passports/list_passport_group_summaries_use_case.py`; `backend/app/application/use_cases/passports/list_passport_submissions_by_group_use_case.py` | Orchestrate authorized paginated summaries and explicit archived reads. |
| `backend/app/application/use_cases/passports/submission_view.py` | Replace quadratic duplicate clustering while retaining incomplete-identity behavior. |
| `backend/app/application/security/authorization_policy.py` | Centralize exact-tenant, lifecycle-aware, locked passport mutation authorization. |
| `backend/app/application/use_cases/passports/submit_passport_use_case.py`; `client_submit_passport_use_case.py`; `retry_public_passport_extraction_use_case.py` | Lock and validate the public/client group before accepting a write or retry. |
| `backend/app/domain/repositories/interfaces.py` | Expose compatible paginated-summary and optional row-lock contracts. |

### Backend infrastructure and API

| Files | Why |
| --- | --- |
| `backend/app/infrastructure/repositories/client_group_repository.py` | Implement optional `FOR UPDATE` access on exact group/token reads. |
| `backend/app/infrastructure/repositories/passport_submission_repository.py` | Execute scoped summary filters/counting/pagination in SQL and correct failed counts. |
| `backend/app/presentation/api/v1/routes/passports.py` | Add additive page/summary APIs, lifecycle/export guards, row locks, CSRF, and hot-path metrics. |
| `backend/app/presentation/api/v1/routes/client_groups.py` | Centralize mutable-group enforcement and protect group/roster/link mutations with CSRF. |
| `backend/app/presentation/api/v1/routes/tour_operations.py` | Protect mutations with CSRF and correct family-size computation. |
| `backend/app/presentation/api/v1/routes/tour_operations_qr_delivery.py`; `backend/app/presentation/api/v1/routes/rooming.py` | Apply CSRF to QR delivery and hotel scanning/update mutations. |
| `backend/app/presentation/api/v1/routes/passport_image_library.py`; `backend/app/presentation/api/v1/routes/whatsapp.py`; `backend/app/presentation/api/v1/routes/menu.py`; `backend/app/presentation/middleware/error_handler.py` | Use status constants supported by both the installed and source-pinned Starlette versions after full-suite failures verified the defect. |

### Backend tests

| Files | Why |
| --- | --- |
| `backend/tests/unit/application/test_passport_group_summary_pagination.py`; `backend/tests/unit/infrastructure/test_passport_group_summary_query.py`; `backend/tests/unit/presentation/test_passport_group_summary_routes.py` | Prove page bounds, filters, tenant/role visibility, archived access, and SQL predicates. |
| `backend/tests/unit/application/test_submission_view.py` | Lock down duplicate, incomplete-identity, and conflicting-passport semantics. |
| `backend/tests/unit/application/test_authorization_policy.py`; `test_submit_passport_use_case.py`; `backend/tests/unit/infrastructure/test_client_group_repository_locking.py` | Prove lifecycle fail-closed behavior and row-lock usage. |
| `backend/tests/unit/presentation/test_archived_client_group_mutation_guards.py`; `test_archived_passport_mutation_guards.py` | Prevent archived/deleted mutation regressions across route families. |
| `backend/tests/unit/presentation/test_group_and_passport_csrf_contract.py`; `test_tour_operations_hardening.py` | Verify CSRF coverage, bearer compatibility, tenant predicates, and the Tour family-count fix. |
| `backend/tests/unit/presentation/test_selected_groups_export.py` | Prevent known-ID export of retained deleted data by non-super-admins. |
| `backend/tests/unit/presentation/test_client_group_storage_cleanup.py`; `test_group_whatsapp_links.py`; `test_passport_bulk_delete_route.py`; `test_passport_upload_status_route.py`; `test_whatsapp_role_access.py` | Update mocks/contracts and add lifecycle, role, lock, and redispatch regression assertions. |

### Frontend All Groups and individual pages

| Files | Why |
| --- | --- |
| `frontend/features/passports/api/passports.api.ts`; `hooks/use-passports.ts`; `frontend/lib/api/endpoints.ts`; `frontend/types/passport.types.ts`; `frontend/constants/index.ts` | Add typed paginated-summary access, page sizing, and stable query keys. |
| `frontend/features/passports/components/passport-list.tsx` | Use server filtering/pagination, preserve cross-page selection, and lazy-load export UI. |
| `frontend/features/passports/components/passport-group-detail.tsx` | Make archived rosters read-only, retain refresh/navigation, and lazy-load heavy dialogs/editors. |
| `frontend/features/passports/components/passport-detail.tsx` | Lazy-load the image editor from the individual page. |
| `frontend/features/passports/hooks/use-upload-links.ts`; `utils/passport-group-navigation.ts` | Carry lifecycle/archive context through group reads and prevent archived navigation writes. |
| `frontend/features/passports/components/passport-bulk-delete.contract.test.mjs`; `passport-groups-pagination.contract.test.mjs` | Prove request/selection compatibility and paginated UI contracts. |

### Frontend Tour Ops and offline scanner

| Files | Why |
| --- | --- |
| `frontend/features/operations/components/tour-group-qr-codes-page.tsx`; `services/qr-image-generation.ts`; `services/qr-image-generation.test.mjs` | Lazy-load QR encoding, bound concurrency, support cancellation/cache eviction/partial failure, and verify those invariants. |
| `frontend/features/tour-operations/services/passenger-offline-projection.ts`; `passenger-offline-projection.test.mjs` | Store only the passenger fields needed offline and prove sensitive-field removal. |
| `frontend/features/tour-operations/services/rejected-attendance-scan-projection.ts`; `rejected-attendance-scan-projection.test.mjs` | Remove QR secrets and broad snapshots from rejected events. |
| `frontend/features/tour-operations/services/attendance-scan-queue.ts`; `frontend/public/offline-scanner.js`; `frontend/public/sw.js` | Upgrade/migrate IndexedDB, sanitize legacy values, and invalidate the old scanner asset cache. |
| `frontend/features/tour-operations/components/coordinator-group-activity-page.tsx`; `coordinator-passenger-detail-page.tsx`; `coordinator-pwa.contract.test.mjs` | Use the minimal projection at both storage entry points and verify PWA behavior. |

### Documentation

| File | Why |
| --- | --- |
| `docs/ALL_GROUPS_TOUR_OPS_OPTIMIZATION_REPORT.md` | Record measurements, security findings, validation evidence, change rationale, and residual deployment risks. |

The untracked user files `GCT staff  Mobile Number detail.xlsx`, `Saigon Sheet.xlsx`, `globalconnect-logo.png`, and `globalconnectteam.png` were not read, modified, staged, or included in this work.
