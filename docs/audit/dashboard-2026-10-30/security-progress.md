# Manual dashboard security review â€” 2026-10-30

This is a direct source review and remediation record. No Codex Security scan or cloud security tool was used. It covers the dashboard authentication, private-file, observability, edge-log and rate-limit boundaries inspected so far. It does not establish that every dashboard/backend file has been reviewed or that the project has a particular security certification.

The per-file record is [security-reviewed-files.json](security-reviewed-files.json). `reviewed` means the listed file was read for the stated boundary without an evidenced issue. `needs-followup` records partial reads and unresolved scope. `fixed` records a concrete patch; a partial review is explicitly noted when the rest of that file remains outstanding. The latest continuation contains 128 physical-file records: 49 fixed and 79 reviewed, all fully read within this lane. Earlier partial records were completed in the final continuation below. This is the manual security lane inventory, not the whole dashboard inventory.

## Fixed findings

| ID | Evidence and impact | Remediation | Verification |
| --- | --- | --- | --- |
| SEC-01 | Unknown paths and arbitrary HTTP methods reached `MetricsRegistry` as permanent counter and histogram keys. An unauthenticated sequence of unique 404 paths produced a growing dictionary and retained raw path contents; requests rejected before routing had the same problem. | Unmatched requests use one static route label and methods outside the standard allowlist use `OTHER`. Matched endpoints retain their declared templates. | Reproduced before patch: 100 requests created 100 counter keys. Regression now requires one series for the same requests, verifies early 429 responses, and preserves known-route aggregation. |
| SEC-02 | Nginx `safe_log_path` omitted newer `/api/v1/public-drafts/{group_token}/...` routes. Application logging already redacted these group capabilities, while the edge access log used the full URI. | Added the missing public-draft prefix to the existing log map. Proxy targets, headers and runtime identities are unchanged. | Source-to-sink trace confirmed. Actual Nginx execution remains unverified because the local Docker daemon is unavailable. |
| SEC-03 | CSRF origin normalization allowed `urlsplit`/`.port` `ValueError` to escape for malformed IPv6 authorities and nonnumeric/out-of-range ports, yielding a 500 before origin rejection. | Parser errors now return an invalid-origin result and follow the existing 403 rejection path. | Both cookie-authentication and preauthentication guards reject malformed origins in regression cases. Existing valid-origin behavior passes. |
| SEC-04 | Byte-range parsing directly converted arbitrary-length digit strings with `int`. A 5,000-digit start/end/suffix or leading-zero sequence exceeded CPython's conversion limit and raised a 500 on private streaming routes. | Clamp ASCII decimals to the known object bound before conversion. Starts outside the object get 416; oversized ends/suffixes retain normal clamping behavior; leading zeros remain supported. | Four large-decimal regressions reproduce failures before the change and pass afterward. Existing full/single-range and invalid-range tests pass. |
| SEC-05 | Permitted Redis fallback stored per-window local counter keys and inactive token-bucket keys indefinitely. Historical buckets accumulated throughout an outage even after their quotas expired. | Extracted local quota mechanics into `local_rate_limit.py`; periodic cleanup discards expired entries. Each burst entry retains its own expiry so a shorter policy cannot reset another active guard. Distributed-required behavior remains fail-closed. | A 500-minute simulated outage leaves one active window. A mixed-policy test expires 100 short-lived buckets while preserving the longer policy's exact refill balance. Existing quota, proxy identity, header and fixture-isolation tests pass. |

## Validation

Using the existing CPython 3.11.15 environment at `backend/.venv311`:

```text
python -m pytest -q -o addopts='' 
  tests/unit/presentation/test_rate_limit_middleware.py
  tests/unit/presentation/test_local_rate_limit_expiry.py
  tests/unit/presentation/test_http_rate_limit_fixture_isolation.py
  tests/unit/presentation/test_request_metric_cardinality.py
  tests/unit/presentation/test_csrf.py
  tests/unit/presentation/test_object_streaming.py
  tests/unit/presentation/test_dashboard_cookie_csrf.py
  tests/unit/presentation/test_auth_route_csrf.py
  tests/unit/infrastructure/test_operational_event_metrics.py
  tests/unit/infrastructure/test_statsd_metrics_export.py

Result: 62 passed, 23 subtests passed.
```

Ruff passed for all changed source/test modules in this lane. Mypy passed for the six changed Python source modules. These checks are local behavior/type evidence; they do not qualify PostgreSQL/Redis/private-storage integration, production Nginx execution, or VPS deployment.

`docker info --format '{{.OSType}}'` could not connect to `dockerDesktopLinuxEngine`; no containers or production services were changed.

## Reviewed controls retained

- Dashboard access remains backed by live durable-session/account checks. Bearer clients and ambient-cookie callers retain their established authentication paths.
- Staff image reads authorize tenant/group/retained-asset ownership before object lookup and before the thumbnail cache. API responses remain private/no-store.
- Browser redirect destinations are constrained to declared same-origin application routes. Auth state remains in memory and server cookies stay HttpOnly.
- Mailbox authorization retains browser/account-generation binding and live actor revalidation before saving provider credentials. Provider transport failures remain sanitized and redirects disabled.
- CSV/XLSX exports inspected so far already contain formula-safety controls. No speculative security rewrite was applied to those existing controls.

## Further review

The JSON records physical files actually read and their exact reviewed hashes. Partial files from earlier batches have now been completed; transitive modules outside this ledger and service-dependent qualification remain separate work. Rooming and email synchronization have since been decomposed and their owning flows reviewed in the batches below. Existing compatibility facades and explicit transaction/authorization boundaries should be retained during that work.


## Rooming architecture and download header batch

The original rooming route module mixed approximately 1,900 lines of access policy, hotel selection, automatic allocation, check-in, workbook exports, retired compatibility handlers and response projections. It is now a small compatibility facade over ten focused modules. All existing route handler argument/decorator AST fingerprints are unchanged. Endpoint order, CSRF dependencies, compatibility helper imports, revision fencing, locking, audit events and export authority rechecks are retained. MCP source classifications were migrated only for the unchanged existing handler contracts; runtime capabilities were not expanded.

International hotel filenames exposed a separate HTTP serialization defect: direct interpolation into `Content-Disposition` cannot serialize non-Latin-1 names. A shared `download_headers.py` serializer preserves simple ASCII headers and uses RFC 5987 for Unicode or delimiter-bearing names. Rooming exports and both MCP artifact/native download responses use it. Protocol-level tests verify exact filename round-trip and prevent raw control characters from forming headers.

Validation used the reviewed `backend/.venv` CPython 3.11.15 environment after root identified that `.venv311` has a stale PDF runtime dependency. The second batch passed **147 tests** across rooming, authorization, MCP rooming exports/edit preservation/artifact/native transfers and HTTP filename serialization. Mypy passed for **12** changed rooming/header source modules. Initial source-classification check had no rooming errors; other active agents subsequently reconciled their own surfaces.

These tests cover local SQLite/protocol behavior. Real PostgreSQL locking and production Nginx execution remain separate qualification requirements.


## Email synchronization and PDF resource batch

The original 2,426-line email synchronization module is now a 307-line coordinator/compatibility facade with focused contract, connection/token, mailbox paging, review, activity, duplicate-assignment, attachment, canonical-ingestion and staff-review owners. The largest owning module is 378 lines. Extraction preserves every function/class AST, all provider/generation/lease filters, per-attachment commits, commit-acknowledgement recovery and native logger source. Existing public/private imports remain available; four unit-test mock targets now follow their actual implementation owners.

Manual review traced direct links to blocked review records rather than arbitrary HTTP retrieval; Graph continuation URLs are constrained to HTTPS, the exact Graph host/port and expected inbox resource paths, and provider redirects remain disabled. OAuth provider/token exchange endpoints remain fixed; credentials are encrypted and owner/generation-bound. The complete provider message-normalization implementations were subsequently read with the supporting branding_visuals agent in the final continuation below.

Two resource defects were fixed while reviewing this path:

- The async email validation boundary previously executed `EmailPdfValidator.validate` synchronously after scanning. Staff-confirmed email review reaches this path in the API. It now uses a thread through the existing cancellation-draining bounded helper, so parsing does not occupy the event-loop thread and cancellation cannot abandon claimed native work.
- Shared upload structural PDF validation previously left `PdfReader`/`BytesIO` reference cycles alive until garbage collection. Both resources now close deterministically for successful, encrypted and malformed PDFs.

Validation in reviewed `backend/.venv`: **156 tests passed** across email synchronization, task routing, Gmail/Outlook providers, Retry-After, PDF/encryption, connection lifecycle, OAuth persistence/races and MCP email overview. Mypy passed for **11** extracted source modules. After the PDF changes, **36 focused tests passed** for async/cancellation behavior, resource lifetime, upload security, sync helpers and PDF validation; mypy passed for both affected source modules and Ruff passed for all source/test edits in this batch.

An initial focused-test command named a nonexistent historical storage-transfer test file and collected no tests; the corrected five-file command produced the 36-pass result above. This failed command is not counted as verification evidence.


## Final private-storage range correction and review snapshot

A source-to-sink trace found that bounded HTTP ranges passed only `start` and `expected_bytes` to storage. For `bytes=2-5` on a ten-byte object, S3 received `bytes=2-`, returned eight bytes, and the repository correctly rejected that response against the four-byte authorization. Presentation tests using a sliced fake stream had missed this integration defect.

The repository now accepts an optional exact `end` bound. The private HTTP response supplies it only when the requested end precedes the object end. Existing full-object/resume calls retain open-ended requests and their original size-change/trailing-byte guards. Five protocol-to-real-repository cases and one invalid-bound case were added using a synthetic S3 client. **29 storage/range tests passed**, both changed source modules passed mypy, and Ruff passed. No live object store was contacted.

Further full-file review covered retained snapshot ownership/availability, original company source attachments, company-private asset delivery, thumbnail caching, sensitive-read evidence and the remaining storage lifecycle methods. No additional evidenced cross-tenant read was found in these inspected paths. Document delivery queue/preview coverage was subsequently completed in the final continuation below; this is not a project-wide security assurance.

The JSON now includes an exact SHA-256 for every available reviewed path and an independent `review_scope` field. A patched file can still have partial review scope. Source edits in this lane are frozen for the final integrated verification. Latest static integration checks before this final narrow range correction passed backend quality budgets (130 modules), architecture boundaries, and all owned-source/test Ruff checks; final repository-wide verification belongs to the root task.


## Completed authorization/delivery continuation and narrow corrections

All 35 formerly partial records were completed by reading the remaining physical source, including dashboard authentication/registration, audit/error/search routes, public draft and returning flows, image mutations, upload controls, client downloads, Nginx locations, rooming/meal workbooks, MCP transfer boundaries and existing regression files. Added supporting delivery selection/policy/publication/worker files were read in full. Full file scope means the complete named physical file was inspected; it does not imply every transitive dependency, live service, race or deployed environment has been qualified.

The document queue source-to-sink trace now covers live actor/tenant/group locks, saved batch and selected-document ownership, current deterministic preview fingerprints, explicit resend and unknown-outcome suppression, durable persistence before publication, conservative queued-only broker compensation and agency/group-scoped tracking. The worker independently binds the private document to agency/group/passenger/type/saved batch, rechecks and locks the current destination/source/grant immediately before sending, and preserves ambiguous-outcome suppression and monotone provider receipts. No additional evidenced authorization leak was found in these paths. The 812-line worker remains an explicit maintainability hotspot; no broad refactor was attempted during final integration freeze.

The helper agent branding_visuals independently read all 747 lines of Gmail provider, 951 lines of Outlook provider and 450 lines of passport ZIP exporter and traced supporting export authorization. Fixed hosts, constrained continuation resources, redirect refusal, response/attachment limits, opaque ID quoting, repeated-page guards and sanitized errors remain intact. ZIP path normalization, case-insensitive collisions, regular file attributes, source-bound crops, size/spool limits and cancellation cleanup remain intact. No live OAuth, mailbox, provider send or object store was contacted. Actual tenant/revision checks remain at the owning route/service and are not replaced by exporter formatting helpers.

Three narrow corrections were implemented during these complete reads:

- Ordinary HTTP `filename=` values were incorrectly passed through URL decoding. A literal `100%.xlsx` could fall back to another name, and `Report%20Final.xlsx` changed its literal name. The browser now decodes only RFC 5987 `filename*=UTF-8''` values, preserving ordinary quoted/unquoted names. The focused Vitest file passed **15 tests**, including percent literals and malformed extended encoding. Existing download permission, session-reset cancellation, streaming and caller-selected names remain unchanged.
- `/mcp/native-transfers/{id}` and its content route existed in backend/frontend but had no Nginx proxy location, so production edge requests fell through to the Next.js application. Added the same private MCP proxy lane used by adjacent transfer routes: a 10 MiB bounded upload, streaming request forwarding, disabled access logging, fixed backend and shared no-store/edge quota policy. The existing isolated Docker qualifier now extracts the actual location and checks synthetic bearer GET/PUT routing, body allowance, no-store and access-log suppression. Python compilation and source extraction passed. **The new Nginx runtime assertions remain unexecuted locally because Docker is unavailable**; the CI runtime qualifier is the remaining execution gate.
- The meal-plan detail worksheet rescanned all entries for each distinct day. It now groups once, then sorts day keys, reducing grouping from O(days × entries) to O(entries + days log days) while preserving per-day input order. A real worksheet regression counts one input visit per entry and checks rendered dishes, dates, merged days and gap rows for interleaved 40-day data. **Three focused tests passed**, scoped Ruff passed, and the changed source passed mypy in the reviewed `backend/.venv` environment.

The latest JSON stores exact SHA-256 values for all 128 existing file paths. It contains **49 fixed** and **79 reviewed** records, with no partial physical-file reads remaining in this lane. This does not state that the complete repository audit or live production qualification is complete. Root owns final integrated verification, release binding refresh and whole-dashboard coverage accounting. Owned runtime source is stable after the three narrow corrections above.


## Dashboard dependency follow-up

After the manual file pass, root requested remediation of the published dashboard npm findings. Next/eslint-config-next are now 16.4.3, Zod 4.6.6 and follow-redirects 1.16.1. Additional findings in the installed development tooling were patched to Vitest/coverage 4.1.12, Vite 8.2.4 and Undici 8.12.2. All unrelated dependency versions were preserved. Both final production/full npm audits report zero findings. Clean install, type/lint, 1,554-test full unit and unchanged-threshold coverage suites, optimized build, nine emitted-standalone browser checks and 124-module maintainability checks passed. This is an upgrade checkpoint before subsequent source review, not final whole-repository qualification. Exact primary metadata, deltas, package hashes, limitations and reproducible check outputs are in [frontend-dependency-remediation.md](frontend-dependency-remediation.md) and [frontend-dependency-verification.json](frontend-dependency-verification.json).


## Browser account and offline ownership follow-up

Protected request retries and offline migration owner-boundary fixes were implemented and reproduced directly from source, without scan tools. See `operations-progress.md` and `attendance-owner-verification.json` for exact latest scope/evidence. Security ledger now has132 full physical-file records, including support/tests; it does not claim132 runtime files or132 vulnerabilities. Shared client/auth source digests refreshed after the narrow follow-up. Root owns final integrated verification.


### Auth continuity checkpoint (2026-10-30)

Full auth runtime reads recorded with current source digests in `auth-reviewed-files.json` (reused identical-SHA prior reads explicitly attributed). Fixed post-await access switching, stale signout review, sensitive account/MFA output, late login/activation/recovery JavaScript state and operation-local same-tab HTTP cancellation. Stable protected subtree key clears old account/role/agency drafts while preserving same-authority renewal. Dead `useMe`/own-test chain retired after moving the stale role/AbortSignal assertion to actual AuthHydrator.

Verification: 21 focused files / 167 tests passed, full TypeScript passed, scoped ESLint passed. Actual Chromium loopback proof showed B JS state with A HttpOnly cookie under a guarded late response; abort before late headers preserved B cookie. This is browser semantics + actual authApi adapter tests, not deployed integration. `auth-continuity-verification.json` binds this checkpoint. Root Blob decoder max64KiB/single-parse diff independently read and source digest refreshed.

OPEN: all-cookie-writer/cross-tab ordering (refresh/logout/access-level and challenge deletion), clipboard rejection in AccountSecurityPanel, storage-denial query-reset reproduction and remaining mixed operations/UI decomposition. These remain work, not a final security certification or accepted blanket limitation. No native mobile, production fixtures, real provider sends, deployment or package/lock edits in this phase.


### Backend cookie-intent precondition checkpoint

Actual ASGI + durable SQLite baseline: seven mismatched-owner behaviors failed and two matching-header behaviors passed. Added optional expected actor rejection to logout and refresh before opaque refresh consumption/replay/family revocation or validated JWT logout mutation. Mixed credentials are checked before either family is revoked. Existing no-header calls, account/family lock order, weekly/MFA checks, and specific REFRESH_IN_PROGRESS retry classification remain intact. No new model/schema/configuration/native app requirement.

32 focused tests across five modules passed in fresh hash-checked environment; changed-source Ruff and mypy passed. Source receipt `auth-cookie-backend-verification.json`. Frontend remained frozen; raw refresh and direct logout do not yet send this precondition. All-writer locking/queued-intent frontend work remains OPEN.


### Auth cookie-writer frontend checkpoint (local date 2026-10-31)

Added shared native Web Lock around current staff-authentication/selected-access cookie HTTP writers, including raw refresh and direct logout. It releases before401/403 response recovery/step-up, rejects missing browser capability with actionable retry UX, and preserves nonbrowser/public requests. Known-actor refresh/direct logout send original actor precondition; no new grants or setup. Closed dead frontend authApi refreshToken/logout/logoutAll aliases retired after complete consumer search and full TypeScript.

Actual bundled app source in real Chromium found a further failure: full logout navigation released its document Web Lock while keepalive headers were pending, then erased newer B cookies. Expected-red artifact is auth-cookie-navigation-before-fix.json. Store now unmounts protected content immediately, waits for bounded logout cookie response before navigation, and rejects stale redirects. Four stale rendered Verify/login/activation/recovery intents reproduced before guards.

Current verification:28files/221focused tests,11actual-module Chromium scenarios,9existing Node contracts, fulltsc and scopedESLint pass.245root-merged module budgets pass, ceilings/floors retained. Full Next UI/build/whole coverage/real PostgreSQL qualification remains separate; this closes evidenced targeted tranche, not whole-audit certification. Source-bound receipt auth-cookie-frontend-verification.json. Next assigned implementation lane: prove and retire dead WhatsApp wrappers after porting strong safety tests to current normal composer path.


### Effective-authority cache/transport and live WhatsApp core checkpoint (2026-10-31)

Actual SessionLifecycle + QueryClient/store regressions reproduced stale private cache when shared browser storage already named B, when storage access/removal was denied, and on same-user effective role/agency changes. Preparation now compares prior in-memory authority and emits cache reset outside storage failure handling. Same-authority session/profile renewal preserves private form drafts and retained opaque recovery identities. Store-specific persistent cleanup still excludes unsynchronized attendance rows and discard evidence.

The common owner-bound request adapter and chained operation helper now capture the local effective tuple [user, role, agency]. They abort and reject stale dispatch/response/auth-retry outcomes after delivered authority changes, without throwing inside auth-store notifications. Only user ID is sent as the backend rejection precondition; local authority metadata is not an HTTP body field or grant. Actual TanStack global onMutate/onSuccess pauses demonstrated current WhatsApp and password intentions could inherit a newer actor or repopulate cleared private cache. Those live mutations now use the reviewed invocation-capturing private mutation helper.

Canonical TypeScript declaration references, computed access and escaped-facade/type-query analysis proved the old frontend WhatsApp send/resend/status/rejected-page chain unused by current UI. Before deleting it, all42original strong send-safety behaviors were ported through fixture-only adaptation onto the actual useNormalWhatsAppSend/composerApi path; reversible hash proof preserves every case/assertion. Five closed runtime files and three closed/ported test owners were retired. Backend/native contracts remain. The447-line hook became an11-line compatibility entry point plus focused query, group and recipient owners. Historical AST extraction proof explicitly distinguishes later invocation-security callee changes.

Verification receipt private-authority-whatsapp-verification.json binds31runtime paths. Combined focused checkpoint470/471 had one missing-auth test fixture; that exact file subsequently passed16/16 after adding a realistic synthetic authenticated User, with no assertion removal. Current81WhatsApp/auth Node contracts,11actual-module Chromium scenarios, whole TypeScript and owned ESLint passed. Parent268module budgets pass with existing live caps/floors retained. Parent integrated coverage/build/emitted-Next browser checkpoint is running separately under source/test freeze. This is not a combined all-suite pass or whole-project certification.27additional full physical core/test paths are recorded in whatsapp-core-reviewed-files.json; older receipts remain historical. Immediate convergence of undelivered cross-tab actor/access changes, clipboard rejection UX and remaining large operations/queue responsibilities remain open.


### Read-only backend support continuation during frontend freeze

Full physical reads of38dashboard backend support/runtime/test files are recorded with exact current SHA values in auth-security-support-reviewed-files.json. This includes cryptography/password work, cookie/CSRF/current identity and reduced access, realtime authorization/origin gating, Visa edit proof/crop persistence, accepted AI job claim/cleanup, bounded provider response handling and native image admission. One supporting settings excerpt remains partial. No runtime source was changed in this continuation. Existing support checks passed79tests+5subtests (Junit84/zero failure); nine further unchanged source files were read afterward, with no new test execution claimed for those extensions.

No additional security defect is asserted from these reads. Realtime agency suspension semantics need an actual supported suspension workflow/contract. Interactive image late-authority behavior needs policy-specific proof: analogous import/bulk workflows revalidate, while already accepted durable VisaAI work deliberately completes by source/claim ownership. A generic post-admission revocation alone does not establish an exploit. Provider errors remain fixed safe messages, response bodies are discarded for non2xx, redirects are disabled, and successful bytes are bounded before JSON/base64 parsing. Linux kernel/allocator behavior and real service concurrency remain separate qualification gates. Whole audit, remaining architecture and full frontend integration remain parent-owned ongoing work.
