# Global Connects Dashboard — audit and implementation report

Local retained source review, implemented improvements and current production-browser qualification complete.

Updated November 1, 2026. Production release qualification has the separate open
requirements below. No commit, push, deployment, production access, real provider
send or Codex Security scan was performed. Security review used source inspection,
caller tracing and meaningful synthetic negative and healthy controls.

## Scope and file coverage

The review covers the Next.js dashboard, Python API and workers, shared database
and authorization infrastructure, desktop MCP connector, deployment/operator
tooling, tests and related documentation. Native/Expo feature code is excluded.
Operations Inbox remaining work is deferred by the user's subsequent instruction.
Shared authentication, outgoing activation/reset/OTP, notifications, WhatsApp
receipts, storage, startup, GC administration and release contracts remain retained.

The current inventory records **6,788 paths**, including
**5,382 active retained files**:
**4,989 full source reviews** and
**393 focused reviews**.
There are **zero active retained files at unreviewed depth**. Native/mobile 852
paths, including 63 exact native support paths, and dedicated Inbox 255 paths
remain excluded/deferred. Removed-source history preserves 295 paths, and four
native historical migrations are separately excluded under backend scope.
The partition is 5,382 active + 852 native/mobile + 255 Inbox + 295 retired +
four excluded native historical migrations = 6,788 paths.

Full and focused are distinct review bases. Generated maps, bundles, schemas,
dependency locks, binaries, images, private assets and mixed-scope files have
explicit provenance, metadata or retained-slice review; these counts do not claim
a physical line read of generated or private payloads. Source hashes invalidate
stale review records. The 134 preserved follow-up statuses include historical
review reminders, scope boundaries and external qualification limits; they are
not 134 validated vulnerabilities. Their individual interpretations remain in
[final-followup-disposition-summary.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-followup-disposition-summary.json), without automatic finding closure.

[Per-file inventory](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/file-inventory.csv) ·
[Progress tracker and cohort history](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/TRACKER.md) ·
[Current follow-up dispositions](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-followup-disposition-summary.json)

## Implemented changes

- **Banner and background editing.** Banners render without blur, color filters
  or image overlays. Image-enabled header/status/control surfaces are transparent,
  with visible keyboard focus. **Edit background** sets a fixed main-workspace
  background outside the sidebar and makes the intended workspace cards
  transparent. Editors provide bounded dragging, keyboard position sliders and
  zoom. Preview proportions follow the actual displayed target at the current
  viewport, including the first banner upload; cancel restores the plain layout.
  Failed or removed artwork restores the normal appearance. Private reads,
  content validation, metadata removal, version conflicts and object cleanup remain.
- **Image save ownership.** The initiating account and full authority are captured
  before asynchronous cropping. Editor-owned cancellation and request ownership
  checks reject stale work after account, role, agency or route changes, including
  an account leaving and returning. Healthy saves retain their original version,
  multipart fields, cache callbacks and API compatibility. The reproduced issue
  was stale client dispatch; no backend authorization bypass or live leak is claimed.
- **Saved relationship editing.** Resuming and editing a saved Other relationship
  restores its actual saved value. Requests are tied to the current group/member/
  proof and editor lifetime. Failed or disabled saved choices support an explicit
  reselection path without silently discarding proof, posting or overwriting a
  newer choice. The existing server validation remains enforced.
- **Architecture.** Large files were separated by responsibility with compatible
  facades, public imports and transaction/error boundaries. This includes passport
  bulk/submission and returning completion, repositories, document models and
  matching, WhatsApp preparation/claims/projection/directory logic, import/export,
  worker/server diagnostics and qualification helpers. The 2,540-line GC model
  module became a 110-line facade, 17 owners of 99–304 lines and a seven-line
  initializer. Explicit checks preserve all 23 classes, 174 tables/mappers, SQL
  metadata/defaults, 22 original star exports and import/pickle identities.
  Direct `inspect.getsource(moved_class)` has a documented compatibility-facade
  limitation; no maintained consumer uses it and no global patch was introduced.
  Immutable migration history and generated data retain their artifact structure.
- **Manual security and correctness.** Review followed authorization, current
  actor/session revocation, tenant and ownership boundaries, disclosure, storage,
  temporary capabilities, file/image processing, diagnostics and resource lifetime.
  Corrections include current actor revalidation at document staging, safe
  diagnostic projection, temporary-object/process cleanup, bounded output and
  deadlines, stale-operation cancellation, calendar boundaries and safe test URLs.
  Tenant-scope and company-directory failure controls exercise real scoped queries
  and HTTP boundaries with synthetic data.
- **Measured performance.** The roster cohort reduced 5,000 reads to one query.
  Travel-tracker mutation removed 209 deep copies in its measured workload.
  Attendance queue visits fell from 505,000 to 257,500 for the same 5,000 items;
  its worst-case scanning remains quadratic. These are scoped work measurements,
  not production latency, throughput, memory or universal no-lag guarantees.
- **Retirement and organization.** The dormant passport OCR/MRZ engine path was
  retired in favor of active AI extraction, including 51 files and 18 dependency
  entries. AI-returned MRZ normalization/checksums and historical compatibility
  remain, as does unrelated visa/ticket OCR where used. Proven unrelated or
  obsolete material, including SmartCOPY, was preserved byte-exactly under
  **Not related to project/**. Active assets, operator tools and migration history
  remain available to their callers.
- **Names and deployment compatibility.** Display names use **Global Connects
  Dashboard** and **Group Companion**. Existing package/application IDs, operational
  service identities, volumes, origins and VPS directory remain compatible. The
  display rename introduces no new server setup. Normal release qualification
  and the reviewed additive 0142 migration still apply; nothing was deployed.
- **Reusable skills.** `review-and-improve-codebase` and
  `polish-existing-dashboard` now capture file coverage, manual boundary review,
  source-bound verification, responsibility extraction, unchanged quality floors,
  current-owner fixture repair, responsive editing and accessible browser checks.
  Both pass bundled structural validation, which does not certify future decisions.

## Verification and actual limits

Reviewed runtimes were CPython 3.11, Node.js 24.21.0 and npm 11.20.0. Exact
selections, source fences, raw logs and failed preliminary runs are retained.
Coverage floors and existing size/complexity ceilings were preserved.

| Lane | Actual result | Evidence |
| --- | --- | --- |
| Backend full retained selection | 9,109 passed, four failed, five platform skips, 87 deselections; 179 passed subtests separate | [final-retained-backend-20261101-001/receipt.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-backend-20261101-001/receipt.json) |
| Backend corrective whole-file checks | PASS: 101 cases + 18 subtests, including all four corrected failures; separate GC dashboard-scope supplement 7/7 | [final-retained-backend-test-repairs-20261101-001/verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-backend-test-repairs-20261101-001/verification.json) |
| Backend coverage union | PASS: all 808 retained normal and 163 retained critical floors; 84.12% global line / 66.94% branch vs unchanged 75% / 58% floors | [final-retained-backend-coverage-union-20261101-001/receipt.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-backend-coverage-union-20261101-001/receipt.json) |
| Backend static checks | PASS: current no-fix Ruff, architecture and static 900-module budget; mypy and migration topology pass at the behavior-identical checkpoint | [final-whitespace-preflight/backend-adoption/receipt.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-whitespace-preflight/backend-adoption/receipt.json) |
| Frontend full lint/types/unit checkpoint | PASS: full lint/types and 303 files / 2,086 unit cases with original coverage thresholds | [final-retained-frontend-20261101-002/results.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-frontend-20261101-002/results.json) |
| Final test-only corrections | PASS: 29 fixture cases + scoped lint/types with empty raw stderr; 1 current-owner Node contract + scoped lint; original assertions retained | [final-fixture-warning-repair/verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-fixture-warning-repair/verification.json), [final-qualifier-node-contract-owner-repair/verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-qualifier-node-contract-owner-repair/verification.json) |
| Current frontend Node contracts | PASS: 665/665 current cases | [final-retained-frontend-20261101-002/test-only-amendment/](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-frontend-20261101-002/test-only-amendment) |
| Frontend maintainability | PASS: 669 measured normal owners; all 661 pre-existing caps exact; 34 critical includes with original numerical floors | [final-frontend-gates-verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-frontend-gates-verification.json) |
| Current frontend production build | PASS: production build `SpoGDo7wxNT9DCsgfUntN` | [final-retained-frontend-20261101-002/test-only-amendment/](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-frontend-20261101-002/test-only-amendment) |
| Current production browser | PASS: 198 Chromium production journeys; zero retries, failures or skips | [final-retained-frontend-20261101-002/production-browser-command.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-frontend-20261101-002/production-browser-command.json) |
| Release bindings | PASS: 144 canonical AFTER and 288 actual Git BEFORE matches; strict loader 14 cases + 335 passing subtests | [final-frontend-gates-verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-frontend-gates-verification.json) |
| MCP surface classification | PASS: 2,036 surfaces; reviewed fingerprints only, historical policies/status/dates/evidence preserved | [final-mcp-branding-authority-integration/verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-mcp-branding-authority-integration/verification.json) |
| Operator / QA / connector | Operator 1,024 passing and six skipped outcomes reconciled across the broad run and separate native-locale case; QA 48/48, connector 181/181 + Ruff; isolated wheel integrity and six synthetic Compose renders pass | [final-operator-connector-verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-operator-connector-verification.json) |
| Retained whitespace | Zero retained warnings; raw Git exit 2 remains for five user-deferred Inbox EOF warnings, with CRLF notices classified separately | [final-git-whitespace-current-verification.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-git-whitespace-current-verification.json) |

All 12 fresh artwork screenshots were visually inspected across desktop and narrow
layouts. The separate root and peer visual receipts record exact image identities,
observations and synthetic-image limits: [final-root-branding-visual-review.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-root-branding-visual-review.json)
and [final-branding-six-screenshot-visual-review.json](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-branding-six-screenshot-visual-review.json). The isolated browser fixture
ports were closed after the run; no user service was stopped.

The original full backend run is not relabeled green. Its four failures were a
deadline-test clock, a stale source-owner contract, a misplaced mock and an
incomplete synthetic actor. Current whole-file tests qualify the repairs without
changing application guards. Coverage combines exactly the original full data
and two successful supplements while all 1,823 application source identities
were identical. Later blank-line/space cleanup has exact AST-location, token and
compiled-code/line-table continuity proof; no differing-source coverage was merged.

The unchanged whole-repository coverage verifier still exits 1 for two native-only
and 76 deferred Inbox coverage deficits. It reports zero retained, unknown or
global violations. Those excluded/deferred results remain visible.

The initial frontend browser run remains 179 passed / 17 failed. Current-flow
fixtures, menu-scroll synchronization and the actual saved-relationship defect
have separate corrective evidence. The latest whole unit run passed before four
test-only amendments: three complete mocks and one stale source-owner contract.
All 1,799 other frontend files, including application code and configuration,
remain byte-identical. Affected checks and the complete current Node/build/browser
results are separate supplements; no failed output was overwritten or renewed.

## Open production-release requirements

**This local source audit does not establish production release readiness.**

- Thirteen of the 15 existing image-advisory disposition windows expired on
  October 26, 2026. The actual validator rejects them. Dates and acceptances were
  not extended. Manual primary-advisory review is recorded, but the installed
  release image/component evidence still needs qualification.
- Docker is installed but its daemon was unavailable and was not started.
  Actual image builds, real PostgreSQL/Redis/private object storage, populated
  migrations, Linux Gunicorn/Nginx behavior, resource/capacity tests and VPS
  release verification were not established by SQLite, static Compose rendering,
  an offline wheel build or synthetic browser fixtures.
- Browser results use Chromium and isolated synthetic services/accounts. They
  do not establish actual provider sends, native-device behavior or universal
  accessibility and performance across browsers/devices.
- Published migration history is preserved: 141 committed migration files plus
  reviewed additive 0142 give 142 current files. This does not mean 0142 is
  already applied. Conditional historical populated rollback concerns remain
  recorded without rewriting published history or attempting unsupported rollback.

[Manual advisory and expiry evidence](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/image-advisory-expiry-manual-review.json) ·
[Final source-bound coverage evidence](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-retained-backend-coverage-union-20261101-001/receipt.json) ·
[Current image-save authority evidence](C:/Users/nipun/Desktop/PassDetection/docs/audit/dashboard-2026-10-30/final-branding-save-authority/verification.json)
