# Enterprise app audit remediation register

- Date: 2026-08-25
- Scope: local PassDetection application source, build configuration, tests, and runbooks
- Source audit: `PassDetection_Enterprise_App_Audit_2026-08-25.docx`

This register is the implementation handoff for the audit. It deliberately
separates a source-level remediation from evidence that can exist only in a
production-like deployment. A green unit test, mock, local build, configured
limit, or checked-in load harness is not production certification.

The requested workflow freeze remains in force. Existing routes, roles,
navigation, page hierarchy, labels, and product journeys were preserved.
Items whose correct remediation requires dual approval, delayed execution,
different navigation, fewer-click flows, or other product decisions remain
explicit rather than being silently redesigned.

## Status definitions

- **Implemented - source:** the unsafe or inefficient source path was replaced
  and has automated contract coverage.
- **Implemented - external proof required:** the source/configuration gate is
  present, but deployment, provider, browser, device, restore, or load evidence
  is still mandatory.
- **Partially implemented:** the highest-risk source behavior is contained, but
  a larger architectural or product boundary remains.
- **Deferred by workflow freeze:** changing the item now would violate the
  explicit instruction not to alter workflows.
- **Open operational gate:** source can enforce the release condition, but no
  current passing artifact or external rehearsal exists.

## P0 findings

| Finding | Status | Remediation and evidence boundary |
|---|---|---|
| P0-01 Archive import can exhaust API memory | Implemented - external proof required | Archive inputs are bounded and spooled/streamed instead of being retained as one unbounded in-memory body. Parser limits and failure cleanup are covered. A production-like concurrent import RSS/latency run is still required. |
| P0-02 Attendance page rebuilds a large roster every 1.5 seconds | Implemented - external proof required | The canonical attendance path now uses compact server summaries, ETag/revision-aware reads, PII-free realtime invalidation hints, and adaptive focus-aware repair polling. A realistic 700-800-passenger/two-browser staging trace remains required. |
| P0-03 Permanent passport deletion bypasses lifecycle controls | Implemented - source | Destructive mutations share one locked authorization policy, enforce tenant scope and legal holds, require recent MFA for privileged deletion, preserve append-only audit evidence, and reconcile storage cleanup failures durably. |
| P0-04 PWA offline access outlives server authority | Implemented - external proof required | Offline use is bound to a signed, short-lived authorization lease, authenticated account/session scope, encrypted local storage, expiry checks, and server reconciliation. Offline reload now restores only a locally valid lease and camera capture remains gated while authority is unresolved. Browser/device expiry and revocation rehearsals remain required. |
| P0-05 Settings exposes immediate Delete All Data | Partially implemented | The current workflow is retained, but the endpoint is fail-closed behind role scope, cookie CSRF, recent MFA, locked destructive policy, legal-hold checks, bounded cleanup recovery, and append-only audit. Two-person approval, delay/cancel, and moving the action out of Settings are product/workflow changes and remain deferred. |

## P1 findings

| Finding | Status | Remediation and evidence boundary |
|---|---|---|
| P1-01 Multiple attendance families can diverge | Implemented - source | Dashboard, coordinator PWA, mobile, replay, closeout, and summary paths now converge on the canonical attendance session/record contract with idempotent event identities and shared status semantics. |
| P1-02 Attendance closeout is installation-scoped | Implemented - external proof required | Count-only account-scoped checkpoints, runtime/retry/discard evidence, stale/missing participant detection, late idempotent reconciliation, and audited manager closeout exceptions replace a single-install assumption. A multi-device field rehearsal remains required. |
| P1-03 My Photos lifecycle is not governed | Implemented - external proof required | Consent, enrollment, asset/match/provider deletion, retention, revocation, recovery, and private delivery lifecycles are explicit and bounded. Provider deletion and privacy/legal acceptance still require live evidence. |
| P1-04 Uploaded files are not malware scanned | Implemented - external proof required | The production upload boundary requires a pinned, isolated ClamAV service, bounded scanner timeouts, fail-closed readiness, quarantine retention, and tests. A live signature-update, EICAR, outage, and quarantine drill remains required. |
| P1-05 Password recovery has no reliable delivery path | Implemented - external proof required | Recovery delivery uses a durable outbox/worker path with retry and non-enumerating responses. Provider credentials, delivery receipts, bounce handling, and a live worker drill remain deployment evidence. |
| P1-06 Object files are buffered into memory | Implemented - external proof required | Object responses use bounded streaming and exact HTTP range semantics with storage timeouts/pooling. Concurrent large-object RSS and proxy buffering must still be measured in staging. |
| P1-07 Readiness reports healthy without critical dependencies | Implemented - external proof required | Readiness now evaluates database, separated Redis domains, worker/broker, object storage, malware scanning, realtime, and configured critical capabilities while liveness remains process-only. The deployed probe chain still needs validation. |
| P1-08 A post-commit broker failure can return a false write failure | Implemented - external proof required | Successful relational commits are no longer converted into false HTTP failures by best-effort dispatch. Durable recovery/scheduler paths own post-commit delivery. A live broker outage/recovery drill remains required. |
| P1-09 Biometric production behavior is unproven | Implemented - external proof required | Production fails closed when real liveness/face providers are unavailable; deterministic fixtures are restricted to explicit development/test environments. Provider calibration, liveness, bias/accessibility, privacy, legal, deletion, and pilot evidence remain release blockers. |
| P1-10 One Redis failure domain serves unrelated workloads | Implemented - external proof required | Broker, security/rate-limit, realtime, and cache domains have distinct validated URLs, credentials/databases, health checks, Compose wiring, and collision tests. The live Redis topology and failover behavior remain operational evidence. |
| P1-11 Database statements and locks have no effective deadlines | Implemented - external proof required | API and worker statement timeouts, lock timeouts, idle-in-transaction limits, bounded pool acquisition, recycling, and connection-capacity checks are configured. Production query telemetry and lock-contention rehearsal remain required. |
| P1-12 HA, backup, restore, and failover are not proven | Implemented - external proof required | CI now rehearses a populated PostgreSQL 0085 dump, checksum, restore, branch upgrade, merge-head upgrade, backfill/constraint verification, and append-only audit enforcement. PITR, replica/failover, object-store restore, RPO/RTO, and regional recovery remain operational exercises. |
| P1-13 Polling islands delay cross-session changes | Partially implemented | The existing cookie-only same-origin WebSocket carries bounded PII-free cursor hints. Attendance and related document, itinerary, roster, Rooming, GC App, and dashboard caches now invalidate immediately; focus-aware jittered polling repairs lost hints. Independent email/menu/provider jobs still use bounded adaptive repair polling until domain outbox events are introduced. |
| P1-14 Browser queue drains one scan per request | Implemented - source | Browser attendance reconciliation uses bounded batches of up to 50, idempotent receipts, backoff, wake signals, and closeout-aware retry/discard accounting. |
| P1-15 Browser storage retains plaintext PII | Implemented - external proof required | Offline storage is account/session fenced, encrypted, TTL-governed, and cleanup/compaction aware; auth transitions clear sensitive caches. Browser storage-denial, crash, expiry, and forensic device tests remain required. |
| P1-16 Settings can overwrite defaults or concurrent edits | Implemented - source | Editing is disabled until authoritative settings load, updates include the expected server revision, conflicts preserve unsaved input and require explicit reload, and failures are never reported as saved. |
| P1-17 Rooming mutations race and rebuild the full workspace | Implemented - external proof required | Every allocation-changing command is revision-fenced across the target and all discovered source hotels under deterministic row locks. Responses are bounded deltas, revisions advance exactly once, and the frontend applies functional stale-safe cache merges. A live two-operator PostgreSQL/browser rehearsal remains required. |
| P1-18 WhatsApp status is polled twice and sends lack safe replay | Implemented - external proof required | One durable cross-route activity tracker owns adaptive batch polling, terminal state, navigation persistence, and refresh invalidation. Server-side delivery ledgers/idempotency rules prevent unsafe duplicate sends. Controlled Meta provider replay/timeout evidence remains required. |
| P1-19 Browser exports build unbounded response Blobs | Implemented - external proof required | Authenticated downloads use a Fetch-adapter `ReadableStream` with backpressure to the File System Access API, hard/idle deadlines, session-reset abort, request/history identity, and an explicitly capped 32 MiB compatibility Blob. Large-export behavior on each supported browser and the asynchronous export path still require browser proof. |
| P1-20 Upload components retain raw `File` objects | Implemented - source | Raw files leave React state as soon as durable staging receipts exist. Resume state contains receipt/chunk identity only, acknowledged chunks are cleared, sign-out/unmount aborts without retry, and expired staging never fabricates a raw-file retransmit. |
| P1-21 Audit logs are mutable and capped | Implemented - external proof required | Audit events have an append-only database trigger, per-tenant hash chain, integrity verification, uncapped paged retrieval, and an external integrity-sink contract. Existing legacy rows retain their legacy chain version; WORM/SIEM delivery and retention proof remain external. |
| P1-22 Giant modules and an open mypy baseline undermine maintainability | Partially implemented | Strict mypy now closes over all application modules, CI enforces size/complexity/coverage ratchets, and newly added GC, Rooming, attendance, upload, download, and DR logic is being extracted into cohesive modules. Several inherited multi-thousand-line modules remain reviewed debt rather than being claimed as fully decomposed. |
| P1-23 Metrics are process-local and operationally weak | Implemented - external proof required | A bounded StatsD export sink, pinned Prometheus StatsD exporter, service health/configuration, and metrics tests make counters/histograms/gauges externally collectable without affecting workflows. Prometheus scraping, dashboards, alerts, trace correlation, retention, and on-call validation remain operational. |
| P1-24 Migrations are tested only on empty databases | Implemented - external proof required | The preserved `0085 -> {0086,0087} -> 0088` graph is enforced, and CI performs populated PostgreSQL dump/restore/upgrade/backfill/constraint checks with retained evidence. The first CI run and production-clone/mixed-version rehearsal remain required. |
| P1-25 There is no 100-200-user capacity proof | Implemented - external proof required | Staging-only k6 harnesses cover 100 concurrent passport extraction users, attendance idempotency/convergence, mobile API/realtime, My Photos, and a guarded 100/200-user dashboard profile. Checked-in harnesses are not passing results; a production-like run with server telemetry and headroom is still mandatory. |
| P1-26 Mobile attendance polls too aggressively | Implemented - source | Foreground/focus-aware full-jitter repair polling uses active/settled windows, honours `Retry-After`, pauses in background, and is woken by mutation/realtime invalidation. |
| P1-27 My Photos starts overlapping refresh loops | Implemented - source | One adaptive, focus-aware refresh policy owns indexing/gallery status and backs off for settled/hidden/error states. |
| P1-28 Device-clock changes can delete attendance evidence | Implemented - external proof required | Attendance retention uses trusted server-time anchors and excludes attendance evidence from idle cleanup when trusted time is unavailable. Manual clock-shift/device-kill proof remains required. |
| P1-29 Closeout override authorization is too weak | Partially implemented | Only the existing manager/admin closure roles can override, recent MFA is mandatory, a specific bounded reason is required, and blocked/successful attempts are audited. A distinct delegated capability or dual approval would change role/workflow policy and remains deferred. |
| P1-30 Download All enumerates before work begins | Implemented - source | A bounded producer/consumer plan starts transfers while small cursor pages are enumerated; it does not retain every result before beginning work. |
| P1-31 Download retries can stall indefinitely | Implemented - source | Runtime wakeups, bounded attempts/backoff, lease recovery, terminal states, and resumable range identity prevent silent permanent stalls. |
| P1-32 Download batches are not visible or manageable | Implemented - source | Durable batches expose queued/running/failed/completed state and allow safe retry/cancel/resume without losing encrypted files. |
| P1-33 Sensitive screens allow capture | Implemented - external proof required | Native sensitive routes and the Android coordinator WebView set screen-capture protection and restore it on exit. Physical screenshot/recents/recording tests remain required. |
| P1-34 Critical mobile media paths lack coverage gates | Partially implemented | Critical coverage floors and direct tests now cover streaming/range, vault policy, auth, realtime, queue, and My Photos planning/record helpers. Some inherited My Photos runtime/repository branches remain below the desired enterprise floor and are visible in the ratchet. |
| P1-35 Expo/native dependencies have drifted | Implemented - external proof required | Expo packages are aligned and `expo install --check`/Expo Doctor gates are green. A clean native prebuild and signed physical-device build remain required. |

## P2 findings

| Finding | Status | Remediation and evidence boundary |
|---|---|---|
| P2-01 Frontend API configuration can fall back to localhost | Implemented - source | Production configuration rejects unsafe localhost/demo origins and validates public runtime configuration before release. |
| P2-02 Blanket `no-store` prevents safe caching | Implemented - source | Cache policy is endpoint-specific: sensitive/user-specific responses remain private/no-store while immutable/static assets and safe validators use bounded caching/revalidation. |
| P2-03 Email pages poll fixed intervals and history is not consistently paged | Partially implemented | Operational inbox is cursor-paged with a bounded page budget; status/review/activity repair polling is visibility-aware, adaptive, jittered, and stops for terminal states. Legacy review/activity lists remain server-capped rather than fully navigable cursor history. |
| P2-04 GC administration performs N+1/unbounded history work | Implemented - source | Client-manager sessions/audit and group audit have deterministic server pagination, count plus bounded-page envelopes, lazy tab loading, previous-data retention, tenant filters, and a constant query count. Agency/company/group enumeration is bounded. |
| P2-05 Menu mutations race and return/reload broad aggregates | Partially implemented | Category, dish, plan, generation, and entry mutations are locked and optimistic-revision fenced; stale writes return a structured conflict and the frontend submits current revisions. Full domain pagination/realtime delta projection remains a later decomposition. |
| P2-06 Proxy checks cookies only as a UX guard | Implemented - source | The proxy is treated only as navigation UX; backend authorization and tenant checks remain authoritative for every API mutation/read. Cookie handling is secure and not presented as access control. |
| P2-07 PWA readiness is misleading offline | Implemented - external proof required | Readiness can restore a locally valid signed lease on offline reload, distinguishes transient refresh failure from invalid authority, rechecks lifecycle/expiry/scope, suppresses stale results, and gates camera capture while unresolved. Browser/device offline proof remains required. |
| P2-08 Browser coverage is mostly mocked | Implemented - external proof required | Isolated Chromium Playwright journeys cover rendered auth, authorization, recovery, and workspace behavior with deterministic HTTP/local-WS fixtures. A live-stack browser suite against PostgreSQL/Redis/MinIO/worker/provider services remains required. |
| P2-09 Aliases and defaults make navigation/workflows inconsistent | Deferred by workflow freeze | Route aliases/default destinations and fewer-click consolidation are product workflow changes and were intentionally not altered. |
| P2-10 Photo locator can remain stale | Implemented - source | Locator state is account/trip/version scoped and invalidated when canonical gallery/authorization state changes. |
| P2-11 My Photos offline page is unreliable | Implemented - source | A bounded encrypted offline page cache, stale-state disclosure, account isolation, and authoritative refresh/rebase behavior replace ad-hoc cached state. |
| P2-12 Feedback submission can race navigation/state changes | Implemented - source | Feedback uses a single intent lane with identity fencing, abort/supersession semantics, and stale-response suppression. |
| P2-13 Cleanup failures are discarded | Implemented - source | Cleanup failures remain durable/retryable with explicit terminal state and observability instead of being silently swallowed. |
| P2-14 Local metadata grows without compaction | Implemented - source | Account-aware retention/compaction policies bound queue, cache, tombstone, diagnostics, and My Photos metadata while protecting unsynchronized attendance. |
| P2-15 Mobile latency labels are ambiguous | Implemented - source | Metrics distinguish network, queue, provider, storage, sync, and end-to-end latency with bounded non-PII dimensions. |
| P2-16 Android artifact is 172.38 MiB | Open operational gate | Source release gates reject an APK over 120 MiB and AAB over 150 MiB. The latest local universal APK is still 180,750,134 bytes and fails. Release must produce a one-ABI ARM64 APK via a controlled architecture property and a separate all-ABI AAB, then pass signer/provenance, bundletool delivered-size, upgrade, and physical-device journeys. |
| P2-17 Mobile has no size/complexity budgets | Implemented - source | CI-enforced module line/complexity budgets and Android APK/AAB ceilings prevent silent regression. |
| P2-18 Mobile/API response bytes are not bounded | Implemented - source | JSON/media/download contracts enforce response-byte ceilings, cursor/page limits, exact ranges, and bounded parsing before allocation. |

## P3 workflow and wording findings

| Finding | Status | Remediation and evidence boundary |
|---|---|---|
| P3-01 Image zoom/pan interaction should be redesigned | Deferred by workflow freeze | No gesture or navigation workflow was changed in this hardening pass. |
| P3-02 Product copy and multi-step workflows should be consolidated | Deferred by workflow freeze | Broadcast/link creation, naming, recipient, send, default-route, and fewer-click recommendations remain a separate product-management phase. |

## Local verification snapshot

The following gates passed against the final local source on 2026-08-25. These
results prove source consistency and local behavior; they do not replace the
production-like evidence listed in the next section.

- Backend: 2,387 tests passed and 16 real-service/OCR tests were intentionally
  skipped; aggregate measured coverage was 73%. Ruff passed over `app`, `tests`,
  and `scripts`; strict mypy passed all 473 application source files; all 13
  reviewed critical-module size, complexity, and coverage budgets passed; and
  bytecode compilation completed successfully.
- API compatibility: the mobile OpenAPI snapshot was regenerated and then
  independently revalidated with the canonical Python 3.11 runtime. The mobile
  contract/release scripts passed 22 tests.
- Frontend: ESLint and TypeScript passed; 31 Vitest files passed 123 tests; 15
  Chromium Playwright journeys passed; all five reviewed high-risk module
  budgets passed; and the optimized Next.js production build compiled and
  completed all 43 page-data generation units.
- Mobile: TypeScript and Expo lint passed; all 210 Jest suites passed 1,236
  tests; all 23 reviewed high-risk module budgets passed; dependency alignment
  was current; and Expo Doctor passed all 21 checks.
- Cross-runtime contracts: all 112 checked-in Node contract files passed 713
  tests, including the guarded dashboard, attendance, mobile, My Photos, build,
  artifact, and CI safety contracts.
- Infrastructure/configuration: Compose runtime separation, CI supply-chain
  policy, and the preserved Alembic merge topology all passed their static
  verifiers.

The current universal Android APK remains deliberately rejected by the release
size gate: it is 180,750,134 bytes (172.38 MiB), above the reviewed 120 MiB APK
ceiling. No local result above is a signed artifact, physical-device result,
live-provider result, PostgreSQL restore result, or 100/200-user staging result.

## Required release evidence that source tests cannot replace

1. Deploy the matching backend/frontend/mobile revisions and migrations
   together where protocol contracts changed.
2. Execute the populated PostgreSQL restore/upgrade rehearsal and retain its
   JSON evidence; separately perform PITR, object-store restore, and failover.
3. Run the guarded 100- and 200-user dashboard profiles plus upload,
   attendance, realtime, and My Photos load suites against an approved
   production-like staging topology. Correlate p95/p99 with database pool,
   Redis, worker queue, provider, CPU, memory, socket, and proxy telemetry.
4. Rehearse Redis-domain and broker outages, ClamAV outage/signature updates,
   storage partial failures, provider timeout/replay, and post-commit recovery.
5. Produce signed ARM64 APK and all-ABI AAB artifacts and complete physical
   Android/iOS/WebView/browser offline, upgrade, camera, QR, PDF, SQLCipher,
   notification, background, screen-capture, clock-shift, and revocation tests.
6. Complete biometric provider calibration, privacy/legal review, deletion
   evidence, accessibility/bias evaluation, and a controlled pilot.
7. Connect Prometheus/alerts/SIEM/WORM retention and prove alert, audit-integrity,
   on-call, rollback, and evidence-retention runbooks.

Until those gates pass, the accurate claim is **source-hardened and locally
verified**, not **production-certified enterprise capacity**.
