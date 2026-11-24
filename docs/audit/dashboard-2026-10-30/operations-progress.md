# Dashboard menu, rooming and tour-operations review

Direct manual review of the browser/dashboard runtime in frontend/features/menu, operations and tour-operations. The native mobile application remains excluded; browser coordinator/PWA workflows remain in scope. No Codex Security tool is used.

The initial inventory contains 57 runtime files. The source ledger records only actual reads with exact hashes; pending files remain explicit in operations-review-pending.json. Work starts with the 1,079-line meal planner, then the 1,013-line passenger/hotel allocation and 855-line rooming workspace. No file-size claim alone justifies changing workflow behavior.

Current work: complete meal-planner read, current revision-fenced mutation hooks reviewed, then separate generation state/actions, modal UI, saved plan detail/meal slots and formatting owners. Existing calls, pending/error states and selection semantics will be preserved, with focused behavioral tests before proceeding. Root owns the final full frontend checks after all source owners freeze.


## Meal planner extraction verified

The 1,079-line component now delegates workflow state/actions to a 292-line hook, rendering to a 164-line screen, 260-line generator dialog, 239-line saved-plan detail and 91-line meal slot, and reusable formatting to a 42-line helper. The generator and all three formatting function bodies are AST-identical. Revision-fenced API hooks were fully read and remain unchanged. Per-entry category lookup uses one memoized category Map instead of scanning the category list for each meal entry; current paused dishes and unused active replacement rules are retained.

Validation: full tsc passed, scoped ESLint passed, five new React behavior tests and five existing Node contracts passed. The new tests cover generation payload/closure, shortage admission, replacement choices, detail editing, cancelled export, failed deletion retry and removed-plan fallback. Initial test queries needed accessible-role matching for required fields, and Playwright-only exact options were removed from RTL queries before the final pass. No application workaround was introduced for those test errors. Root owns combined suite/build after all frontend edits freeze.

Meal-planner checkpoint ledger: 12 full physical paths including tests/new owners; 53 original runtime paths remain pending. Next work is rooming allocation/workspace and the remaining menu/operations/tour-operations runtime reads.


## Rooming allocation and workspace extraction verified

The original 1,013-line passenger/hotel allocation is now a 140-line screen, 281-line selection owner, 141/164-line filter/action views, 140-line group view and 188-line paginated table. All original state/mutation statements and the group/table/row/gender helper bodies are AST-identical. Selection remains parent-owned across table pages and excludes passenger IDs removed by authoritative refresh.

The original 855-line workspace is now a 260-line page, 53-line state/export owner, 102-line hotel summary, 73-line state views and 162-line shared hotel dialog. Create/edit forms previously duplicated their fields and payload/error logic. The previous custom focus handler did not inert the background or contain programmatic focus. The shared modal boundary now supplies those protections while preserving pending Escape/close/backdrop guards, field constraints and the current revision-fenced mutations.

Validation: 25 focused React tests passed across meal planning, allocation, hotel dialogs and the shared modal; full tsc and scoped ESLint passed. The 11 existing rooming/grouping Node tests and five existing menu contracts passed. Seventeen measured line/complexity ratchets were added with small ceilings; all 160 current high-risk module checks pass. AST checks also preserve workspace state/export and six summary/loading helper bodies. No full frontend rerun is performed during other owners' active source changes; root owns combined final gates.

The new manager-administration subtree is root-owned and excluded from this lane's pending inventory. Remaining 57-file initial-scope work is explicit in operations-review-pending.json; it includes untouched menu library, operations transport/hooks, remaining tour UI and signed browser offline storage/authorization.

Current coverage: 29 full physical-file records and 1 partial record; 49 original runtime paths remain pending.


## Operations transport and cache-owner review

Complete reads of operations.api.ts and use-operations.ts traced the current revision-fenced rooming mutations, scoped audit/attendance query keys, conditional summary revisions, private QR lifecycle/delivery, cancellation-aware exports and mutation invalidations. The rooming delta helper and compatibility flag were also read completely. No new evidenced authorization or private-data leak was found in these physical files. The mixed operations transport/type and hook facades remain architectural hotspots; no broad API ownership migration was stacked onto this review.

A source/caller trace proved the legacy AuditLog interface, operationsApi.auditLogs transport and useAuditLogs polling hook had no consumer or dynamic dispatch. Only that closed dead chain was removed. Current paged audit/export behavior and backend routes remain intact. Focused attendance/tour transport and rooming delta tests passed 10 cases; full tsc, scoped lint and current dashboard structural contracts passed.

Latest lane coverage: 33 full physical-file records; 45 original runtime files pending.


## Account ownership, offline privacy and UI follow-up verified

The original 57-file menu/operations/tour-operations browser-runtime inventory has now been read completely. `operations-reviewed-files.json` records 88 actual full physical files including extracted owners, focused tests and support; `operations-review-pending.json` is empty for that original inventory. Root's new manager-administration subtree has its own owner/coverage. A full source read is not a guarantee of production security, physical-device responsiveness or completed architecture remediation.

Three reproduced source-to-sink problems were corrected. First, an original account's private mutation could replay after 401 refresh or MFA step-up under a replacement account; both ordinary mutation tests failed before default request binding. Protected dashboard requests now capture the known staff actor synchronously, preserve an explicit original queue owner, check after authentication/error awaits, guard the final adapter after asynchronous interceptors and abort/suppress stale in-flight output. Auth/bootstrap, public traveller proof/upload and health/OAuth requests keep their independent identity semantics. A stale refresh failure cannot clear a replacement actor/session. The API optionally checks `X-Expected-Actor-Id` against the already authenticated durable-session user before a handler can run. The header only rejects mismatches and never grants authorization. Native mobile clients are not required to supply it; no route schema, cookie format or deployment setup changed.

Second, legacy snapshot migration captured owner A, awaited IDB and then recaptured current owner B while writing A's minimized passenger roster. The regression proved an actual B/agency-B encrypted record was written before the fix. Persistence now carries the original snapshot identity through migration, and post-await/decrypt checks suppress stale results. Legacy data remains available after cancellation; successful same-owner copy/verify/removal remains intact. Third, a blocked IDB open could reject its caller and later succeed with an unowned live connection. Late success now closes the connection after prior failure while ordinary open/versionchange behavior remains unchanged.

Queue scans, batch/legacy replay, discard evidence and count-only closeout publication now carry their captured actor to the HTTP boundary. Owner changes during claims/decryption or after successful responses retain the original rows as retryable, release sending claims, preserve another owner's rows and suppress stale progress/private output. Server-detected cookie mismatch remains retryable even before the tab observes the account change. No queue purge, schema bump, idempotency weakening or row-retention change was introduced.

A separate passenger-detail effect wrote an offline snapshot, received its newly rehydrated array, and wrote again repeatedly. The regression observed two writes for the same persisted fields before the fix; comparing exactly the minimized id/name/city/status fields stops that cycle while preserving changed fields and other passengers. QR-delivery and missing-people previews now reuse the shared modal keyboard boundary instead of duplicate document listeners. Staff invite/reset copy errors use the existing clipboard helper and visible manual recovery; pending staff creation's close button respects the existing dismissal guard.

Current focused verification: 84 React/transport/storage tests across 13 files pass, all 81 Node contracts under the three reviewed feature scopes pass, full current TypeScript and scoped ESLint pass, and 194 measured frontend module budgets pass. The optional backend actor check has 12 passing ASGI/CSRF/role tests plus scoped Ruff and mypy in the fresh hash-checked audit environment. Expected-red reproduction artifacts are explicitly named `*-before-*.json`; they are evidence of the previous defect, not current failures. Exact check/source digests are in `attendance-owner-verification.json`. Root owns final integrated frontend coverage/build/browser and full-dashboard accounting.

Remaining architecture work is explicit despite complete source reads: menu library (716 lines), QR distribution (899), office attendance (about 625), rooming priorities/generated plan (539), browser scanner (718), hotel scanner/details (674), activity page (510) and queue (about 1780) retain multiple responsibilities. They were not broadly refactored during integrated freeze. Physical camera/torch behavior, multi-tab real IDB/Ed25519/AES service integration, VPS/Nginx and live service authorization qualification remain unexecuted locally. No Codex Security scan tool, production fixture or provider send was used.
