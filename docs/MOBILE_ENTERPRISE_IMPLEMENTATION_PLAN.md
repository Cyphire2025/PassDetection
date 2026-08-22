# Group Companion enterprise implementation plan

Status: development implementation complete; manual and external release evidence intentionally deferred
Baseline: `main` at `1bdb0b2` on 2026-08-19
Primary scope: Expo/React Native Group Companion, plus the backend and dashboard contracts required for correctness, freshness, and load safety

## Objective

Bring the Android and iOS app to a measurable enterprise release standard without changing existing business workflows, permissions, terminology, authorization boundaries, offline guarantees, API compatibility, or stored user data.

This is not a rewrite. Changes are delivered as small, test-protected contracts. The durable encrypted database remains the mobile source of truth, and server authorization remains the security boundary.

## Non-negotiable implementation rules

1. Preserve current passenger, coordinator, and manager workflows and all existing authorization checks.
2. Keep historical Alembic migrations immutable. New schema work is additive and reversible.
3. Never use private PDFs, production PII, credentials, tokens, or generated release artifacts as tests or fixtures.
4. Fail closed on ambiguous identity, authorization, document matching, account context, and cursor state.
5. Keep metadata freshness independent from large encrypted-file hydration.
6. Make every durable mutation idempotent and every retry bounded, cancellable, and jittered.
7. Treat background execution and push delivery as hints; cursor reconciliation owns correctness.
8. Keep automated evidence separate from Android-device, iOS-device, security, load, production, and legal acceptance.
9. No finding is marked complete merely because code compiles. Completion requires the evidence listed below.

## Definition of done

Each item must have all applicable evidence:

- implementation merged in the intended source/configuration;
- focused regression tests for success, failure, retry, cancellation, and account isolation;
- complete mobile/backend/frontend automated suites remain green;
- release configuration and dependency policy checks pass;
- Android release-runtime validation for platform-sensitive behavior;
- iOS release-runtime handoff and result for platform-sensitive behavior;
- operational or load evidence where the finding is about concurrency, latency, memory, storage, power, or infrastructure;
- documentation of any external DNS, signing, store, legal, or production gate that cannot be completed from this Windows workspace.

## Target architecture

1. Encrypted SQLite is the mobile app's durable local source of truth.
2. React Query projects local state and screen state; it does not independently refetch resources already owned by synchronization.
3. One persisted sync coordinator accepts startup, foreground, realtime, push, background, manual, and mutation triggers.
4. Every sync run captures an immutable account/session context, supports cancellation, coalesces equivalent work, and uses global concurrency limits.
5. Metadata, versions, and cursors commit atomically and publish immediately.
6. Encrypted document downloads run in a separate durable, prioritized, bounded queue.
7. Foreground realtime messages carry version/invalidation hints; push and periodic reconciliation repair missed messages.
8. Expired or compacted cursors rebase through a stable server snapshot that is staged and atomically promoted on-device.
9. Storage, queue, dataset, API, and creation-time limits are explicit shared contracts across dashboard, API, and mobile.
10. Privacy-safe telemetry proves service-level objectives without recording tokens, names, document identifiers, phone numbers, file paths, or document content.

## Service-level objectives and release gates

These are targets, not current measurements.

| Area | Acceptance target |
|---|---|
| Cached authenticated shell | p95 at or below 1.5 s on reference mid-tier device; at or below 2.5 s on supported low-tier device |
| Foreground dashboard commit to visible app metadata | p95 at or below 2 s; p99 at or below 5 s |
| Reconnect to metadata consistency | p95 at or below 5 s under normal backlog |
| Missed-event correctness | 100% recovered through cursor reconciliation; push/realtime loss cannot lose data |
| Cursor safety | Monotonic, idempotent, crash-safe; duplicate, missing, reordered, compacted, and expired cases tested |
| Cross-account isolation | Zero stale-response commits after account/session-generation change |
| Attendance local enqueue | Immediate durable acknowledgement |
| Attendance server confirmation | p95 at or below 2 s on healthy network; explicit pending state offline |
| Crash-free sessions | At least 99.95% |
| Android ANR rate | Below 0.1% |
| Document open | Separate measured targets for cached and first-download paths |
| Storage | Hard account/app quotas; required offline documents are never silently evicted |
| Background sync | Best effort only; never the sole correctness/freshness path |
| 10,000 concurrent clients | Error rate below 1% during steady state and defined reconnect/publish bursts |
| API performance | Endpoint-specific p95/p99 budgets, not one generic latency number |
| Release quality | Expo Doctor green, dependency policy satisfied, signed device E2E green, verified links green |
| Accessibility | VoiceOver/TalkBack, maximum text, reduced motion, focus, orientation, and tablet matrix green |
| Data privacy | No tokens, PII, document identifiers, or sensitive paths in push, telemetry, logs, crash reports, or task snapshots |

## Phased delivery

### Phase 0 — Release and privacy blockers

- Fix the Hermes document-viewer failure and add engine-compatible regression coverage.
- Replace or correctly configure the broken verified-link origin and remove credential-bearing custom-scheme activation fallback.
- Put manager previews under the secure temporary-view lifecycle and disable renderer disk caching.
- Apply selective native screenshot/screen-recording protection and app-switcher masking to passport, visa, ticket, and other sensitive previews while retaining privacy-safe telemetry, notification redaction, and managed plaintext cleanup.
- Align the Expo SDK 57 patch set, eliminate native drift, and make Android/iOS generation deterministic.
- Establish an explicit signed-OTA policy or formally disable production OTA until signing is available.
- Add privacy-safe minimum crash/ANR visibility before broad rollout.

### Phase 1 — Instant startup and freshness

- Render verified cached identity/trips immediately while online validation proceeds.
- Separate metadata/cursor commits from document download and validation.
- Introduce one persisted sync coordinator and remove competing refresh ownership.
- Capture immutable account/session context and propagate cancellation through network and database commits.
- Add foreground realtime version hints plus durable cursor reconciliation.
- Focus-gate and jitter attendance fallback polling; coalesce scan/upload work.
- Correct push token registration, rotation, logout, account-switch, and revocation ownership.

### Phase 2 — Large-group and long-offline reliability

- Implement cursor expiry/compaction and snapshot rebase across API and app.
- Replace hard roster, attendance, trip, and content ceilings with stable snapshot/keyset/infinite loading.
- Batch SQLite writes, shorten write locks, and prioritize user mutations over bulk refresh.
- Replace wildcard/OFFSET search with debounced, cancellable FTS5/keyset search.
- Add aggregate document quotas, required-file pinning, LRU for evictable data, queue limits, retention/dead letters, and database maintenance.
- Add locally verifiable bounded QR behavior and accurate pending-versus-confirmed attendance states.
- Introduce signed, bounded offline authorization leases with clock-rollback protection.
- Make background work deadline-aware and checkpointed.

### Phase 3 — Enterprise operations and maintainability

- Complete rooming/meals against complete local projections or explicit server-filtered snapshots.
- Add privacy-safe SLO dashboards, traces, crash/ANR reporting, and alerts.
- Add release-device E2E, low-disk, kill/restart, slow/lost-network, battery, memory, and chaos suites.
- Run realistic 1,000/5,000/10,000 mobile-client and event-fanout load profiles.
- Add server-side upload validation/sanitization and platform attestation for risk-tiered operations.
- Add localization, canonical trip timezone handling, accessibility, large-text, and tablet acceptance.
- Split large stateful modules one tested contract at a time and publish shared API schemas.

## Finding ledger

Development completion snapshot (2026-08-19):

- All 32 findings now have their selected source, configuration, contract, and automated-regression remediation implemented. There are no remaining coding items in this ledger.
- Mobile validation is green: strict TypeScript, zero-warning lint, 136 Jest suites / 744 tests, aggregate coverage floors, Expo dependency/configuration checks, runtime audit, maintainability budgets, and device-E2E workspace contracts.
- Dashboard validation is green: lint, type generation, 613 Node contract/regression tests, zero production dependency audit findings, and a 39-page optimized production build.
- Backend implementation streams completed 1,971 passing tests, 4 intentional skips, and 126 generated subtests; the final changed-surface OpenAPI/runtime/capacity/realtime follow-up passed 21 focused tests. Supply-chain, Compose-separation, and load-harness contracts are also green.
- Per the development-scope decision, physical Android/iOS behavior, real notification delivery, real attestation providers, store signing/builds, production deployment, live dashboards/alerts, and an actual staging load run remain a manual or external release checklist. They are not represented as executed evidence.

Status values used below:

- `development complete` means the chosen source remediation and applicable automated proof are green.
- `development complete - manual gate` means source and automated proof are green, while physical-device or human acceptance is deliberately deferred.
- `development complete - external gate` means source and automated proof are green, while infrastructure, provider, staging, DNS, signing, store, or production evidence is deliberately deferred.

| ID | Priority | Finding | Chosen enterprise direction | Acceptance evidence | Status |
|---|---:|---|---|---|---|
| F-01 | P0 | Verified Android/iOS activation links use an origin that does not serve valid association files | Use one owned HTTPS origin with valid AASA and asset-links files; accept activation credentials only from verified HTTPS links; keep any custom scheme non-credential-bearing | Live GET/HEAD checks, Android `pm get-app-links`, iOS associated-domain test, terminated-app activation E2E | development complete - external gate: live hosting and platform link proof deferred |
| F-02 | P0 | `toSorted` crashes the secure viewer on tested Hermes | Use an immutable `slice`/spread plus `sort`; add a test with `toSorted` absent and release-Hermes device smoke | Focused unit test, Android release viewer open, iOS release viewer open | development complete - manual gate: Hermes regression green; device viewer smoke deferred |
| F-03 | P0 | Manager preview can leave plaintext/cache remnants | Use the same managed temporary-view lifecycle as the vault, sweep on startup/background/logout/account change, disable renderer caching | Force-kill/relaunch storage inspection on both platforms; logout/account-switch/background tests | development complete - manual gate: lifecycle tests green; device storage inspection deferred |
| F-04 | P1 | Startup blocks on network and all-trip preparation | Cache-first authenticated shell; validate online in parallel; prepare selected/upcoming trips by priority | Instrumented cold/warm start p50/p95 on low/mid devices; offline and slow-network E2E | development complete - manual gate: cache-first/race tests green; device startup profiling deferred |
| F-05 | P1 | No foreground realtime path | Authenticated, version-only WebSocket/SSE hints plus coalesced cursor reconciliation; push is background hint only | Miss/reorder/reconnect tests, 10k connection/fanout load, p95/p99 dashboard-to-visible metric | development complete - external gate: protocol/auth/reconnect tests green; live Redis/fanout/load deferred |
| F-06 | P1 | Metadata waits behind encrypted blobs | Atomically commit metadata/cursor and durable blob jobs first; hydrate files in a separate bounded queue | Announcement/itinerary visible during slow/failed 25 MiB download; process-kill recovery | development complete - manual gate: metadata/blob split tests green; device kill proof deferred |
| F-07 | P1 | Startup/foreground/background/push/query refresh systems compete | One coordinator owns resource synchronization; triggers coalesce and React Query publishes local projections | Trigger-storm test proves one logical sync; request-count baseline and cancellation tests | development complete: coordinator, coalescing, cancellation, and publication tests green |
| F-08 | P1 | More than 10,000 pending changes can wedge a trip | Server `cursor_expired`/compaction signal plus stable snapshot/rebase; stage and atomically promote generation on-device | 100k backlog, duplicate/reordered events, kill-during-rebase, retry-from-checkpoint tests | development complete - external gate: snapshot/rebase contracts green; live backlog/kill proof deferred |
| F-09 | P1 | Hard 2k–4k dataset ceilings fail valid large groups | Explicit creation-time quotas plus cursor/keyset/infinite or complete local snapshots; never raise caps blindly | 4k/10k roster and attendance E2E, creation-side validation, memory/frame/response-size evidence | development complete - manual gate: capacity/pagination tests green; large-device evidence deferred |
| F-10 | P1 | Hidden/frozen screens continue eight-second polling | Realtime first; only focused route may run jittered adaptive fallback; stop elsewhere and honor `Retry-After` | Navigation/focus tests and 10k-client request-rate load evidence | development complete - external gate: focus/jitter/retry tests green; live request-rate load deferred |
| F-11 | P1 | Requests can commit into the wrong account after switch | Immutable account/session-generation context from request through DB transaction; cancel and verify before commit | Deterministic account-switch race tests at every query/mutation boundary | development complete: account-generation cancellation and isolation race tests green |
| F-12 | P1 | QR is format-only locally, replayable, prematurely shown as checked in, and queue is unbounded | Short-lived signed claims with key rotation where offline verification is required; bounded queue; explicit pending until server acceptance | Replay, screenshot sharing, invalid-junk flood, offline/online reconciliation, key-rotation tests | development complete - manual gate: evidence/queue/pending tests green; physical sharing flow deferred |
| F-13 | P1 | Offline auth trusts rollbackable wall-clock time | Server-signed scoped offline lease plus server-time floor and monotonic elapsed time within a boot | Clock rollback/forward, reboot, expiry, revocation-generation, long-offline tests | development complete - manual gate: lease/time/revocation tests green; device reboot proof deferred |
| F-14 | P1 | Push registration lifecycle is incomplete and noisy | Installation/account/session-generation registration, change fingerprint, token-change listener, idempotent upsert, atomic revoke/tombstone on logout/switch | Token rotation, reinstall, account switch, logout offline/online, stale-token cleanup tests | development complete - external gate: lifecycle tests green; real provider/device delivery deferred |
| F-15 | P1 | Logout/retention behavior does not match privacy language | Define one explicit product policy; default to purge sensitive local data and server registrations on logout unless documented reactivation retention is approved | Storage inspection after logout/reinstall/account switch; policy text and retention tests | development complete - manual gate: purge/retention tests green; device storage inspection deferred |
| F-16 | P1 | Response limits are enforced after full allocation | Native/streaming bounded transport for blobs; upstream and proxy size enforcement; bounded structured responses | False length, chunked oversize, concurrent downloads, low-memory device tests | development complete - manual gate: bounded transport/range tests green; low-memory device proof deferred |
| F-17 | P1 | Sensitive previews could appear in screenshots, recordings, or app-switcher snapshots | Acquire a ref-counted native capture-protection lease on passport, visa, ticket, and other document previews; add an opaque inactive/background cover while leaving ordinary screens capturable | Component lifecycle, native-rejection, app-state, document-viewer, and manager-preview regression tests plus physical-device review | development complete - manual gate: automated privacy lifecycle tests green; physical-device screenshot/recording proof deferred |
| F-18 | P2 | Local root/jailbreak detection is narrow and fail-open | Server-verified Play Integrity/App Attest for risk-tiered issuance/operations; local signal remains defense in depth | Root/jailbreak/hooking, replay, outage, unsupported-device, false-positive tests | development complete - external gate: provider/server contracts green; real attestation/device proof deferred |
| F-19 | P2 | Keys remain accessible after first unlock | Split key policy by sensitivity; iOS unlocked-only Keychain; Android native AES-GCM/Keystore store with API 35+ `UNLOCKED_DEVICE_REQUIRED` and API 26-34 native lock guard; short signed leases for high-risk material | Migration/failure/Kotlin compile evidence plus locked-device/background/reboot/biometric-change tests on both platforms | development complete - manual gate: source tests and Android release Kotlin compile green; API 35 cryptographic and API 26-34 guard physical-device/OEM proof deferred |
| F-20 | P2 | Repeated decrypt/hash work delays opening and synchronization | Cache verified integrity/version metadata securely, deduplicate in-flight opens, avoid redundant passes, profile before native optimization | Cached/open-first p95, concurrent-open, tamper, version-change, memory evidence | development complete - manual gate: integrity/dedup tests green; device latency/memory proof deferred |
| F-21 | P2 | SQLite bulk refresh uses row-by-row bridge calls and one long write lane | Bounded multi-row UPSERT/staging, prepared statements, mark-and-sweep, short transactions, user-write priority | 10k-row benchmark, lock p95, kill/rollback, idempotent replacement tests | development complete - manual gate: batching/replacement tests green; physical benchmark deferred |
| F-22 | P2 | Vault, queues, rejected records, and database files can grow without aggregate bounds | Required-file pinning, account/app quotas, LRU for evictable data, bounded queues, retention/dead letters, idle maintenance | Low-disk, quota, pinning, eviction, rejected-action retention, vacuum/checkpoint tests | development complete - manual gate: quota/race/retention/lifecycle tests green; low-disk device proof deferred |
| F-23 | P2 | Search is not actually debounced and local wildcard/OFFSET queries scale poorly | Fixed debounce, cancellation, normalized FTS5 search, keyset pagination, indexed server search | Keystroke request-count test; 10k-row latency and correctness benchmark | development complete - manual gate: debounce/FTS/keyset tests green; device-scale latency proof deferred |
| F-24 | P2 | Rooming/meals and some attendance views can be incomplete or all-before-first-render | Complete synchronized projection or server-filtered cursor endpoint; progressive first-page rendering; explicit completeness state | Matching records beyond first pages, offline completeness, 10k progressive-render tests | development complete - manual gate: completeness/progressive tests green; device-scale render proof deferred |
| F-25 | P2 | Background sync has no deadline/cancellation/checkpoint contract | OS expiration signal plus internal deadline; prioritize/version-probe/checkpoint and stop cooperatively | Expiration, process kill, resume checkpoint, battery/network tests | development complete - manual gate: deadline/cancellation/checkpoint tests green; OS/battery proof deferred |
| F-26 | P0/P2 | Expo patches, dependencies, native generation, OTA, and release governance are inconsistent | Align SDK patch set; reproducible lockfile/prebuild; explicit signed-OTA-or-disabled policy; store-signed device gates | Doctor/audit policy green, clean prebuild diff, Android/iOS release build and signed-device E2E | development complete - external gate: dependency/config/CI gates green; native/store signing/build deferred |
| F-27 | P2 | No fleet observability for startup, freshness, crashes, ANRs, queues, or sync | Privacy-safe native crash/ANR plus fixed-schema OpenTelemetry metrics/traces with redaction and sampling | Schema privacy tests, dashboard/alert drill, SLO evidence, outage correlation | development complete - external gate: schema/redaction tests green; live dashboards/alerts deferred |
| F-28 | P2 | Node tests miss release-engine, device, and chaos behavior | Layered unit/contract, release-Hermes emulator, iOS, physical-device, performance, and load suites | CI matrix plus recorded signed-device and load results | development complete - manual gate: automated layers/workspace contracts green; release-device/chaos proof deferred |
| F-29 | P3 | Wallpaper, blur, shadows, and list composition may be expensive | Measure frame time, overdraw, memory, and startup first; simplify only failing surfaces with capability/reduced-effects modes | Perfetto/Instruments evidence on supported low tier and large lists | development complete - manual gate: shared budgets/list policies green; native profiling deferred |
| F-30 | P3 | Localization, timezone, accessibility, and tablet behavior are incomplete | Typed localization catalog, canonical trip timezone, semantic/focus/large-text rules, responsive tablet layouts | Locale/timezone matrix, DST tests, VoiceOver/TalkBack, max text, tablet E2E | development complete - manual gate: locale/timezone/layout/a11y tests green; human/device proof deferred |
| F-31 | P3 | Large stateful modules and duplicated role orchestration drift | Characterization/race/chaos tests first; extract one state machine/service contract at a time; publish shared schemas | Complexity/duplication reduction with unchanged behavior and complete regression suite | development complete: vault split into bounded modules; maintainability and regression gates green |
| F-32 | Gate | Mobile-only checks cannot prove backend authorization or 10k capacity | Backend object/tenant authorization suite, endpoint/database/event/CDN load profiles, rate/queue/failure controls | Cross-user/trip/tenant denial tests; role downgrade/revocation tests; 1k/5k/10k steady and burst reports | development complete - external gate: authorization/capacity/harness tests green; actual 1k staging run deferred |

## Validation matrix

### Automated on every change

- Mobile: strict TypeScript, lint with zero warnings, full Jest, focused contract/race tests, Expo Doctor, dependency policy.
- Backend: focused and full pytest, Ruff, mypy, migration-head check, API schema/contract tests.
- Frontend/dashboard: Next type generation, strict TypeScript, lint, build, relevant interaction/contract tests.
- Repository: `git diff --check`, secret/artifact hygiene, generated-file policy, lockfile reproducibility.

### Android release-runtime

- Secure document open and manager preview cleanup after force-stop.
- Verified activation link from browser/email in foreground/background/terminated states.
- Account switch during in-flight requests and sync/database commits.
- Push/token rotation/logout lifecycle.
- Background expiration and resume.
- Privacy-safe telemetry, notification redaction, and plaintext cleanup across app lifecycle transitions.
- Low storage, network loss, clock changes, 4k/10k lists, 25 MiB files, and process kill during critical operations.
- Frame time, ANR, memory, startup, and battery on the supported low tier.

### iOS release-runtime handoff

- Equivalent viewer, links, account-race, push, background, privacy, storage, network, time, accessibility, and performance matrix.
- App Store signing, entitlements, privacy manifest/declarations, and encryption-export review.

### Backend and event infrastructure

- Authorization matrix for cross-user, cross-trip, cross-tenant, role downgrade, disabled account, and revoked document access.
- Endpoint-specific database/query-plan and p95/p99 evidence.
- 1,000, 5,000, and 10,000 virtual mobile clients in steady state.
- Reconnect storms, dashboard publish bursts, push fanout, attendance scans, large file/CDN downloads, cache loss, database failover, and broker degradation.
- Error rate below 1% for the agreed steady and burst profiles; zero correctness loss after recovery.

## External decisions and gates

The following cannot be truthfully completed by source edits alone:

- DNS/HTTPS ownership and hosting for the verified-link origin.
- Android and iOS production signing credentials and store-signed device builds.
- OTA signing certificate/private-key custody, or a formal decision to disable OTA.
- Apple encryption-export and App Store privacy/legal declarations.
- Physical iOS device validation from a macOS build environment.
- Production-like load environment, event broker, CDN/object storage, push provider, database capacity, monitoring, backup, failover, and disaster-recovery drills.

These remain release gates; they are not silently waived.
