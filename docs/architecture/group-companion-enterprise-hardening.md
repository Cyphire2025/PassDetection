# Group Companion enterprise hardening evidence ledger

Status: implemented working tree; repository checks, a fresh Android
release-mode APK build and emulator installation are complete for the checks
recorded below. Store signing, physical-device and macOS/iOS validation remain
open and are not claimed by this ledger.

Snapshot date: 2026-08-03.

This ledger describes the implementation currently present in the repository.
It deliberately separates source evidence, automated verification, synthetic
measurement and external validation. A unit test, an existing APK, or a local
benchmark is not treated as proof of a production deployment or a real-device
end-to-end journey.

## Evidence vocabulary

- **Implemented** means the behavior and its enforcement path are present in
  the working tree.
- **Verified** means the named command or focused check passed against this
  combined working tree during this implementation session.
- **External validation required** means the result depends on Meta, the
  deployed VPS/object store, Android or iOS hardware, signing credentials, or
  production-scale data and was not proven by the recorded local checks.

## Authoritative architecture and invariants

- PassDetection remains the source of truth. Mobile contracts reuse the same
  groups, passengers, assignments, publications and authorization services;
  the device cache is not a second business-rule implementation.
- The mobile API is bounded and role-scoped. Tenant, principal, enabled-group,
  assignment, lifecycle and passenger ownership are checked server-side; IDs
  supplied by the client are not trusted as authorization.
- Mobile DTOs are explicit projections rather than serialized ORM models. Raw
  object-storage URLs, passport numbers, MRZ, AI confidence, internal notes and
  private document fields are absent from the Coordinator detail contract and
  rejected by the strict client schema.
- Local metadata is normalized in a per-account SQLCipher database. Database
  lifecycle operations and writes use a serialized, keyed transaction
  connection so account switching and concurrent startup/sync cannot share a
  transaction or cache namespace. A secure health marker avoids repeating
  `PRAGMA quick_check(1)` after a confirmed clean close, while a missing,
  malformed, dirty, stale, future-dated or schema-mismatched marker and every
  migration force the bounded check. Controlled recreation is allowed only
  when the durable action queue is provably empty; otherwise the database is
  preserved and the application fails closed.
- Passenger sessions persist the exact set of identities proven during OTP
  verification. A stable account identifier survives passenger trip switches,
  while every selected trip remains bound to that session allow-list. A shared
  phone number never grants multiple identities without the configured
  secondary factor proving each retained record.
- Screen queries complete their account/trip-scoped persistent-cache hydration
  before automatic network fetching is enabled. Cache failures release the
  bounded network path without deadlocking, and late hydration from a replaced
  account/session is discarded. In-memory query keys include the full
  tenant/account namespace, and changing either tenant or principal clears the
  query client and selected-trip stores before the new account can render.
- Personal and common files are stored in application-private storage as
  authenticated AES ciphertext. Keys are held through Android Keystore/iOS
  Keychain via SecureStore and are not written beside the files.
- SQLite schema v16 records durable trip-purge tombstones before revoked,
  expired or removed content is hidden. Failed ciphertext deletion is retried
  on startup/background sync, and database triggers prevent a pending purge
  from being repopulated. Per-trip, per-account and plaintext-preview fences
  order in-flight writes/decrypts ahead of cleanup so logout or revocation
  cannot acknowledge deletion and then recreate sensitive files.
- Offline mutations are durably queued before submission and carry unique
  idempotency keys. Attendance receipts, duplicate suppression and queue
  deletion are committed atomically.
- Already usable cached screens are never covered by background preparation.
  Only an explicit pull gesture owns the pull-to-refresh indicator.

## Implemented product and platform ledger

| Surface | Implementation present | Repository evidence / boundary |
| --- | --- | --- |
| GC App dashboard | Groups are added with Passenger, Client Manager and Coordinator access enabled by default. The group list remains summary-only; role controls are kept in Manage & Publish. Publishing presents one fixed Itinerary PDF area followed by categorized common documents. | GC App API adapter, App Controls, group workspace, common-document panel and dashboard contract tests. Access is still enforced by the backend, not only hidden in the UI. |
| Mobile authentication and preparation | Stable-session preparation, one-trip fast path, explicit searchable multi-trip passenger selection, remembered selection, and role-specific Passenger/Manager/Coordinator preload progress are implemented. OTP challenges are durably serialized before provider submission, use bounded neutral responses and timing equalization, and rotate into exact session identity allow-lists. Individual file failures are non-blocking, reported as retry-later, and must not claim that all files are ready. | Auth prepare route, OTP challenge/session migrations, required-preload policy, passenger trip selection, and role preload modules. Meta/WhatsApp delivery remains external. |
| Authentication race isolation | Login, logout, account replacement and token rotation advance a monotonic authentication epoch. Concurrent 401s share one refresh only inside the same epoch/token boundary; a delayed response cannot revive a logged-out account, overwrite a new account, or retry an old request with the new account's bearer token. | Session store/service and API client race tests cover account switching, logout, stale refresh rejection and normal same-session rotation. |
| Bounded API parsing | JSON success bodies are capped at 2 MiB and error bodies at 64 KiB. Declared, chunked and unknown-length responses are bounded before parsing; oversized streams are cancelled and malformed JSON becomes a stable non-sensitive error code. | API client payload-boundary tests explicitly cover valid and oversized unknown-length streams, declared-length rejection before body consumption, stream cancellation and malformed responses. |
| Passenger trip content | Cached trip metadata, fixed Itinerary/common-document presentation, QR, profile details, updates and role-scoped trip switching are implemented. Background invalidation is silent; explicit pull refresh is available. | Passenger routes, trip repository, content repositories, notification runtime and shared manual-refresh hook. |
| Passenger documents | Passport, visa and flight-ticket states are reconciled from the authoritative backend. Eligible new versions are prefetched after authentication/sync, encrypted, versioned, checksum-validated and opened from the local copy. A failed file remains retryable without blocking entry to cached trip data. | Content repository, passenger preload, retry policy, vault and document screen tests. Passenger upload remains outside the app. |
| Client Manager | Explicitly assigned groups, common documents/itinerary, readiness and updates use selected-trip, account-scoped caches. Background refetch does not display a pull spinner. | Manager routes, manager preload, selected-trip store and compact readiness contract. No personal document grant is introduced. |
| Coordinator selection and details | The selected assigned group is shared across passengers, scan, attendance, documents and updates. Coordinator passenger detail is a strict safe projection cached by account, trip and passenger and rendered in grouped sections. | Coordinator trip store/hooks, strict detail schema, SQLCipher schema v12 migration/legacy fallback, repository and detail screen. |
| Cache-first query lifecycle | Trips, content, notifications and Coordinator hooks share one persistent-hydration gate. Network requests wait for the scoped cache decision; errors release the network path, and stale account/session completions cannot populate the replacement account. React Query receives React Native focus/connectivity state while Sync Runtime remains the sole reconnect synchronization owner. | Shared persistent-query hydration hook, query runtime and ordering/account-switch tests. |
| Render failure recovery | A root error boundary catches provider/navigation/render failures, dismisses a stuck splash screen and exposes two bounded recovery attempts plus the existing safe sign-out path. Diagnostics retain at most 20 process-local fixed codes and bounded attempt values; thrown messages, stacks, routes, paths and account/document data are never stored or rendered. | Root layout, application error boundary, diagnostics module and seven focused tests. No external crash provider was introduced. |
| Coordinator attendance and scanning | Started/completed activities and missing-passenger detail are cached. Scans are stored locally first, deduplicated per activity, queued idempotently, drained serially without starving new scans, and reconciled with server counts. Active attendance retains an intentional foreground-only 8-second activity refresh. | Attendance session/queue repositories, scan policy, scanner and attendance screens. The 8-second active-session query is not the global sync loop. |
| Incremental synchronization | Manifests, resource versions, update cursors and changed entities drive scoped refresh. Startup, reconnect, foreground, selected-trip change and push are event triggers. Requests coalesce, a full request wins, unchanged results do not invalidate queries, and removed trips purge only their scoped caches. | Sync service/runtime/policy, access cache and notification runtime. A persisted cursor of zero is valid and no longer forces repeated baseline downloads. |
| Passenger mutation propagation | GC-enabled passenger, WhatsApp-link/recipient and roster mutations reconcile mobile identities inside the caller's existing transaction and append bounded role-targeted journal events without passenger fields. Imports above 100 passengers collapse to one roster refresh. | Passenger propagation service plus public upload, Excel import, bulk delete, broadcast link/recipient and roster-resolution integrations. Worker-only extraction/delivery transitions remain on authoritative manifest reconciliation. |
| Synchronization race isolation | Every background run captures an immutable account, agency, role, session, namespace and abort signal. The context is revalidated before database/vault writes, in-flight keys include namespace/session, and switching accounts aborts the old context. Durable purge tombstones block revoked-trip restoration; authorized access-generation refreshes preserve queued attendance, the finite access lease and the selected trip while invalidating only derived caches. | Sync-context, purge, vault-fence and session-race tests prove that delayed Account A work cannot commit into Account B, logout waits active writes/decrypts, and true revocation still removes unauthorized queued actions. |
| Refresh visibility | All app `RefreshControl` instances use gesture-owned manual state; none bind their visible spinner to React Query `isRefetching`. Overlapping manual pulls deduplicate and failures always settle the indicator. | Shared `useManualRefresh`, focused hook tests and the static audit recorded below. |
| Streamed mobile downloads | Object storage is read through bounded range/stream APIs rather than being materialized in the backend process. The client accepts missing HTTP `Content-Length`, bounds bytes by signed metadata, validates exact ranges and MIME, retries/resumes interrupted bodies, verifies SHA-256 and atomically replaces encrypted files. | MinIO repository, mobile resource route, vault/download-range tests and the 25 MiB mobile ceiling. |
| Durable encrypted transfer | New downloads are stored as authenticated AES-GCM frames with 256 KiB plaintext windows. Authenticated progress survives process restarts, resumes from the exact verified byte, remains account/trip/document/version/checksum bound, and never persists plaintext staging. A completed encrypted file awaiting SQLite registration is recoverable. | Chunk-container, vault, recovery-candidate and content-repository tests cover restart, cancellation, corruption, truncation, supersession, unknown length and checksum failure. Legacy v1 ciphertext remains readable until naturally replaced. |
| Stream connection lifecycle | Authorization, metadata and audit writes complete and release the backend database session before a request waits for the bounded stream semaphore or a slow client. Cancellation closes the object-store stream; range and grant checks remain unchanged. | Mobile-resource saturation tests hold 12 streams and verify released sessions, cancellation cleanup and invalid-grant rejection. |
| Bounded roster persistence | Coordinator roster replacement remains one atomic transaction, but up to 1,500 rows are persisted in 75-row multi-value UPSERT batches rather than one statement lifecycle per passenger. | Roster batching helper and 1,500-row focused test; 20 bounded batches use 750 bindings each, below SQLite's conservative variable ceiling. |
| Deduplicated role preload | Manager and Coordinator preparation consume the document-prefetch result already produced by `syncTrip`; only a failed sync runs one centralized fallback pass. Coordinator common-document prefetch uses the shared size-aware policy, is abortable on unmount/selection change and skips a current offline version. | Manager/Coordinator preload and Coordinator document-cache tests. |
| SQLite health and recovery | Database health stays dirty while either keyed SQLite connection is open. Only a confirmed native close records clean state; migrations and any uncertain previous shutdown revalidate. Transaction recovery replaces a connection whose rollback state became unknowable and never issues rollback before a successful begin. | Database lifecycle and SecureStore tests cover concurrent open/close, rollback failure, clean reopen, forced recheck, failed close and queued-action-preserving corruption handling. |
| Tenant consistency and throttling | Database constraints bind a passenger identity and document cache row to the same agency, group, access record and passport submission. Production login lockouts fail closed when the shared Redis limiter is unavailable. Client-IP rate-limit/audit identity accepts forwarding only from configured reverse-proxy peers. | Alembic 0071, ORM constraints, limiter tests, trusted-client-IP tests, Compose production setting and Nginx Cloudflare real-IP allowlist. |
| Private limiter identifiers | Dashboard-login and mobile-OTP limiter keys use purpose-separated HMAC-SHA256 identifiers keyed by the existing application secret. Redis and warning logs contain no raw normalized email, phone or IP; limits, TTLs and fail-closed behavior are unchanged. | Login and mobile-OTP limiter privacy/stability/isolation tests. No new production secret is required. |
| Reduced motion and bounded preparation | Navigation disables animation when the OS requests reduced motion. Manager and Coordinator multi-group preparation uses two bounded workers, aggregate monotonic progress and per-resource resilience instead of serially blocking every assigned group. | Accessibility policy test, root/auth/coordinator layouts and role preload modules. |
| Durable push delivery | Push tickets and receipts are persisted with bounded retry/backoff and age caps. Receipt processing records FCM/APNs handoff, revokes `DeviceNotRegistered` tokens, deduplicates events and keeps notification bodies free of document or passport detail. | Alembic 0076, notification service/provider/tasks and focused ticket/receipt tests. Production provider/device delivery remains external. |
| Batched attendance reconciliation | Up to 100 idempotent scans are reconciled with batched session, QR and replay lookups, ordered conflict-safe inserts and atomic local queue receipts. | Coordinator mobile API and attendance tests. Modeled query boundaries are recorded separately from live latency. |

## Deterministic performance deltas

### Synchronization cadence

The former foreground runtime scheduled a sync every 15 seconds and a full trip
refresh every fourth tick (once per 60 seconds):

This source baseline is `mobile/src/core/sync/sync-runtime.tsx` at Git commit
`090e6ae`; the current implementation is compared against that exact revision.

- selected/global foreground schedule: 240 ticks per active hour;
- full-trip schedule: 60 full refreshes per active hour.

The implemented runtime is event-driven for startup, reconnect, returning to
foreground, selected-trip changes and push. Its bounded safety schedules are:

- selected-trip fallback every 5 minutes: 12 scheduled fallbacks per active
  hour, a deterministic 20x / 95% reduction from the former 15-second schedule;
- full-trip reconciliation every 30 minutes: 2 scheduled full reconciliations
  per active hour, a deterministic 30x / 96.67% reduction from the former
  once-per-minute full schedule.

These ratios compare timers only. Event triggers can add work when real changes
occur, so they are not a claim of an identical reduction in production request
count. The new work is smaller in scope: selected-trip sync is preferred,
unchanged manifests do not invalidate screens, cursor pages are bounded, and
only affected query keys refresh. Active Coordinator attendance deliberately
keeps its separate 8-second foreground refresh while an activity is active.

### Synthetic payload benchmark

The following command was run on the development workstation:

```text
python scripts/benchmark_gc_mobile_payloads.py --passengers 1500 --iterations 101
```

Recorded results from that run:

- reference full roster: 356,543 JSON bytes;
- compact readiness: 275 JSON bytes, 99.923% smaller;
- incremental room change: 367 JSON bytes, 99.897% smaller;
- verified coordinator passenger change (journal plus one passenger detail):
  1,008 JSON bytes, 99.717% smaller than the synthetic 1,500-passenger roster;
- reference serialization p50/p95/p99: 1.6633/1.7062/1.7316 ms;
- readiness serialization p50/p95/p99: 0.0031/0.0032/0.0036 ms;
- incremental-room serialization p50/p95/p99:
  0.0036/0.0038/0.0061 ms.
- incremental-coordinator-passenger serialization p50/p95/p99:
  0.0077/0.0082/0.0121 ms.

The batched attendance implementation also reduces the modeled database-query
boundary for 100 new scans from 404 to 108 round trips (73.27%), and for 100
known idempotent replays from 400 to 3 (99.25%). This is a deterministic code-
path/query-count comparison, not a production database latency measurement.

This is a local synthetic serialization and payload comparison. It is not a
physical-device cold-start, render, SQLite, object-storage, production network,
or production API p50/p95/p99 measurement.

## Security controls present

- Production API configuration rejects cleartext transport; Android release
  configuration disables cleartext traffic and backup.
- A production deployment with the mobile API enabled refuses to start unless
  `MOBILE_JWT_SECRET_KEY` contains at least 32 UTF-8 bytes. The secret remains
  independent of public Expo configuration and is never embedded in the app.
- Mobile access tokens have a separate audience/type. Opaque refresh tokens are
  hashed server-side, stored in platform secure storage on-device and rotated;
  logout/account switching purges the account database, queued actions and
  offline vault namespace.
- JWT validation uses maintained PyJWT with explicit HS256, issuer, audience,
  token-type and required `exp`/`iat`/`sub` checks. The vulnerable transitive
  `python-jose`/`ecdsa` dependency path was removed.
- Logout invalidates the authentication epoch, cancels required preparation,
  clears the in-memory session and selected trip synchronously before any
  fallible SecureStore, network, database or filesystem operation. Server
  revocation uses the snapshotted bearer without authentication refresh, while
  local credential/key deletion and the purge fence still run after a token
  lookup or network failure.
- SQLCipher keys and document keys are device-bound SecureStore secrets using
  this-device-only accessibility. Personal caches are namespaced by account,
  tenant, trip and passenger as applicable.
- Document authorization is short-lived and identity-bound. Download handling
  enforces an exact MIME allowlist, safe filename rules, strict single-range
  resume behavior, streamed byte ceilings, checksum verification and atomic
  ciphertext replacement. Missing `Content-Length` is accepted only while the
  streamed ceiling and integrity checks remain enforced.
- Signed document paths are canonicalized and must match the exact authorized
  trip, document, content endpoint and single version query; trusted-looking
  suffixes under an unrelated host or path are rejected.
- Background sync persists only allowlisted, bounded failure reason codes; raw
  exception strings, filenames, phone numbers and document metadata are not
  written to the local diagnostic cursor.
- Passenger QR and document screens request screen-capture protection. QR and
  document contracts remain passenger/group scoped.
- Coordinator detail schemas fail closed on unexpected sensitive fields.
  Attendance duplicate receipts and server-side idempotency prevent repeated
  actions from becoming repeated attendance.
- Push tokens are encrypted server-side, notification refresh is trip-scoped,
  and notification navigation revalidates the current assignment before
  selecting a trip.
- Biometric/device-unlock re-entry is intentionally not requested by this
  product revision; biometric/fingerprint permissions are blocked in Android
  configuration. This removes the repeated OS lock prompt but leaves possession
  of an already-unlocked device as a residual risk.

## Verification recorded for this working tree

| Check | Result | What it proves |
| --- | --- | --- |
| Mobile TypeScript | `npm run typecheck` passed | Current mobile TypeScript contracts compile. |
| Mobile lint | `npm run lint` passed with zero warnings | Current mobile lint policy passes. |
| Full mobile Jest | 71 suites, 370 tests passed | Current unit/component policy suite, including keyed database lifecycle/recovery, v16 migration, durable purge and document jobs, encrypted restart resume, namespace/trip/temp-view fencing, unknown-length/ranged downloads, bounded API bodies, auth/account races, multi-group selection, strict cache-first hydration, root error recovery, batched roster persistence, deduplicated preload, renderer-cache lifecycle, Coordinator document cancellation, scan/detail, reduced motion and refresh behavior. |
| Manual security/regression review | Passed for the scoped mobile/backend/dashboard hardening; type-check, lint, full tests and dependency audits passed | Authentication, authorization, cache isolation, encrypted vault, logout, download, push and temporary-view boundaries were reviewed manually as requested. No Codex Security scanner was used. Residual operational limits are disclosed below. |
| Manual refresh focused test | 2 of 2 passed | Explicit pull owns the spinner, overlapping pulls deduplicate, and failures clear it. |
| Database/sync/scanner/detail focused selection | 5 suites, 29 tests passed | Serialized database lifecycle plus Coordinator detail, scanner and sync policies. This is included in the later full mobile result but retained as focused evidence. |
| Backend full pytest | 1,644 passed, 4 skipped and 124 subtests passed | The full backend automated suite passed against the combined working tree, including mobile OTP, exact passenger-session authorization, streaming session release, push tickets/receipts, attendance batching and document-propagation regressions. |
| Backend Ruff | Full `ruff check .` passed | The backend lint gate passed. |
| Alembic head and offline SQL render | `0076_mobile_push_receipts (head)`; offline `upgrade head --sql` exited 0 | Operational indexes, scope constraints, exact passenger-session identities, serialized OTP challenges, device sync acknowledgement, mobile session index and durable push receipts form one repository head. Revision identifiers are bounded to the production Alembic `VARCHAR(32)` contract. A live PostgreSQL rehearsal remains external because local Docker was unavailable. |
| Backend mypy | 446 errors across 66 files (362 checked) | Repository-wide legacy type debt remains red and is not misreported as a pass. Runtime regression tests, Ruff and compile paths are green; removing this debt safely remains separate from the mobile behavior release. |
| Dashboard/frontend contract tests | 78 test files, 538 tests passed | The full Node contract-test set passed. |
| Dashboard lint/type/build | All passed; production build compiled 37 static pages | Dashboard lint, TypeScript and production compilation passed. |
| Refresh source audit | No `RefreshControl` binding to `isRefetching` remained | Background React Query invalidation cannot directly display a pull-to-refresh spinner. |
| Scoped diff check | Passed; only Windows line-ending notices | No whitespace-error finding in the audited mobile scope. |
| Payload benchmark | Values recorded above | Deterministic local payload/serialization comparison only. |
| Android release-mode APK (debug-key signed) | Clean native `assembleRelease` passed in 8m 41s; final source delta rebuilt incrementally in 1m 55s | The current working tree bundled with production API URL, preview release guard and demo mode disabled. This is an emulator/compile verification artifact, not a Play-distribution artifact. |
| Android AAB | Deliberately not rebuilt in this pass | The requested delivery was APK-only. Any older local AAB predates the final source and must not be distributed or cited as current. |
| Android manifest/ABI audit | package `com.globalconnects.groupcompanion`, min SDK 26, target SDK 36, version 1.0.0/1, four ABIs | The built APK contains arm64-v8a, armeabi-v7a, x86 and x86_64 native libraries. |
| Android emulator install/launch | Streamed in-place install and launcher start passed | Exact fresh APK installed on `emulator-5554`, package process `15063`, version 1.0.0/1 and last update `2026-08-03 11:39:19 +05:30`; the app was the top resumed activity and the bounded post-launch fatal/ANR/transaction-error scan returned zero matches. Earlier timing measurements are retained only as a historical absolute baseline and are not attributed to this final APK. |
| iOS project generation | WSL2/Linux Expo prebuild passed; Expo Doctor 20/20 | The reproducible managed-workflow Xcode project was generated and its bundle ID, deployment target, privacy keys, push entitlement and associated domain were inspected. CocoaPods/Xcode compilation and Apple signing still require macOS. |
| Verification bundle configuration | Embedded `https://tech.gctravels.com/api/v1`, `preview` release guard and demo disabled; production application ID | The APK exercises the real API and production package boundary without pretending that missing EAS identity/store credentials are configured. Production profiles independently fail closed unless their complete public EAS configuration is supplied. |
| Dependency checks | Frontend npm audit: 0; mobile npm audit: 0; backend pip check and pip-audit: 0 known vulnerabilities | The mobile build-tool `uuid` path is pinned to the fixed release, and backend JWT handling migrated from `python-jose`/`ecdsa` to PyJWT. |

No migration upgrade against a production clone, iOS compile, physical-device
journey, real-provider OTP/push journey, or production-load result is claimed
by this ledger unless a later entry adds its exact command and result.

## Delivery documentation

- The complete tracked/untracked working-tree path inventory is recorded in
  [group-companion-changed-files.txt](./group-companion-changed-files.txt).
- Android APK/AAB commands and iOS/macOS preparation instructions are recorded
  in the [mobile build README](../../mobile/README.md).

## Android and iOS build readiness

### Android

- The native Android project is present. Gradle release APK/AAB tasks, Expo
  production profile, package identifier, deep link, notification/camera
  permissions, SQLCipher, minification, resource shrinking and cleartext
  blocking are configured.
- A fresh universal APK was built from this working tree. It is 173,065,095
  bytes with SHA-256
  `C0BE8A83FE1B720D9A0B92DBDD92784B90F5ADAA3CBBE5AFBB947C554E681A90`.
  No AAB was rebuilt; any older local bundle is stale relative to this source.
- The current artifact path is
  `mobile/android/app/build/outputs/apk/release/app-release.apk`.
- The minified APK retains the manifest-reflected
  `expo.modules.adapters.react.apploader.RNHeadlessAppLoader`; the corrected
  emulator run recorded no loader initialization error.
- This release-mode verification artifact is signed with the generated
  debug keystore (`release` currently uses `signingConfigs.debug`). For Play
  distribution, the AAB must be signed with the protected upload key/EAS
  credentials; Play App Signing signs delivered APKs. The local APK is not
  production-distribution signed.
- APK Signature Scheme v2 verification passed. The signer is `CN=Android
  Debug`, certificate SHA-256
  `FAC61745DC0903786FB9EDE62A962B399F7348F0BB6F899B8332667591033B9C`.
- The merged manifest has `allowBackup=false` and
  `usesCleartextTraffic=false`. Platform `WRITE_SETTINGS`, external-storage,
  `MANAGE_EXTERNAL_STORAGE`, `USE_BIOMETRIC` and `USE_FINGERPRINT` permissions
  are absent; vendor launcher badge permissions with similarly suffixed names
  are not the platform `android.permission.WRITE_SETTINGS` capability.
- OTP login, upgrade, offline document/QR/scanner and account-switch isolation
  on representative physical Android devices remain required.

### iOS

- Expo configuration contains the iOS bundle identifier, iOS 16.4 deployment
  target, associated domain, camera description, private file-sharing settings,
  static frameworks and shared React Native source.
- The managed/prebuild `mobile/ios` project was generated successfully through
  WSL2/Linux after native Windows correctly refused iOS generation. The generated
  Xcode project contains bundle ID `com.globalconnects.groupcompanion`, iOS 16.4,
  camera privacy text, disabled file sharing/open-in-place, push entitlement and
  `applinks:app.globalconnecttravels.com`; Expo Doctor remained 20/20. Native
  folders are intentionally reproducible and ignored by the managed-workflow
  Git policy. CocoaPods resolution, Xcode compile/archive, provisioning, signing,
  notification/deep-link behavior and App Store privacy declarations remain
  unverified and require macOS/Xcode.

## Production configuration boundary

Backend secrets and provider credentials belong only in the VPS/server
environment. A production GC App configuration includes these mobile-specific
settings in addition to the platform's existing database, Redis, object-store,
JWT, WhatsApp webhook and encryption settings:

```text
MOBILE_ENABLED=true
MOBILE_JWT_SECRET_KEY=<independent random production secret, at least 32 UTF-8 bytes>
MOBILE_JWT_ISSUER=passdetection
MOBILE_JWT_AUDIENCE=gc-mobile
MOBILE_ACCESS_TOKEN_EXPIRE_MINUTES=15
MOBILE_REFRESH_TOKEN_EXPIRE_DAYS=30
MOBILE_OTP_PROVIDER=whatsapp
MOBILE_OTP_DEVELOPMENT_CODE=
MOBILE_OTP_TTL_SECONDS=300
MOBILE_OTP_DELIVERY_TIMEOUT_SECONDS=10
MOBILE_OTP_RESEND_COOLDOWN_SECONDS=60
MOBILE_OTP_MAX_ATTEMPTS=5
MOBILE_OTP_PHONE_LIMIT_PER_HOUR=10
MOBILE_OTP_IP_LIMIT_PER_HOUR=30
MOBILE_OTP_REQUIRE_REDIS=true
MOBILE_SYNC_PAGE_SIZE=200
MOBILE_ADMIN_PAGE_SIZE=50
MOBILE_COMMON_DOCUMENT_MAX_BYTES=26214400
MOBILE_PERSONAL_DOCUMENT_MAX_BYTES=26214400
MOBILE_DOCUMENT_GRANT_TTL_SECONDS=60
MOBILE_PUSH_PROVIDER=disabled
MOBILE_PUSH_ACCESS_TOKEN=
MOBILE_PUSH_BATCH_SIZE=100
MOBILE_PUSH_TIMEOUT_SECONDS=10
MOBILE_PUSH_DISPATCH_INTERVAL_SECONDS=5
MOBILE_PUSH_MAX_SEND_ATTEMPTS=5
MOBILE_PUSH_RETRY_BASE_SECONDS=5
MOBILE_PUSH_RECEIPT_BATCH_SIZE=1000
MOBILE_PUSH_RECEIPT_INITIAL_DELAY_SECONDS=900
MOBILE_PUSH_RECEIPT_POLL_INTERVAL_SECONDS=60
MOBILE_PUSH_RECEIPT_MAX_ATTEMPTS=8
MOBILE_PUSH_RECEIPT_MAX_AGE_HOURS=23
LOGIN_LOCKOUT_REQUIRE_REDIS=true
WHATSAPP_ACCESS_TOKEN=<existing Meta system-user token>
WHATSAPP_PHONE_NUMBER_ID=<existing Meta phone-number id>
WHATSAPP_API_VERSION=v25.0
WHATSAPP_OTP_TEMPLATE_NAME=verify_code_1
WHATSAPP_OTP_TEMPLATE_LANGUAGE=en_US
WHATSAPP_WEBHOOK_VERIFY_TOKEN=<existing high-entropy webhook token>
WHATSAPP_APP_SECRET=<Meta app secret>
```

`MOBILE_OTP_DEVELOPMENT_CODE` must remain empty when the provider is
`whatsapp`. Push stays fail-closed with `MOBILE_PUSH_PROVIDER=disabled` until
the Expo project and physical-device delivery tests are ready. Configure
`MOBILE_PUSH_ACCESS_TOKEN` when Expo access-token security is enabled or
required for that project. Ticket IDs are retained in the database until the
bounded receipt worker confirms FCM/APNs handoff or reaches its retry/age cap;
keep the bounded dispatch and receipt settings from `.env.example`.

The following are public compile-time application configuration, not secrets:

```text
EXPO_PUBLIC_API_URL=https://tech.gctravels.com/api/v1
EXPO_PUBLIC_APP_ENV=production
EXPO_PUBLIC_DEMO_MODE=false
EXPO_PUBLIC_EAS_PROJECT_ID=<production Expo project UUID>
EXPO_PUBLIC_EXPO_OWNER=<production Expo owner>
EXPO_PUBLIC_UPDATES_URL=<signed production EAS Update URL, if enabled>
```

Never put Meta, database, Redis, object-storage, JWT, signing or encryption
secrets in an `EXPO_PUBLIC_*` value because those values are embedded in the
application bundle.

## Safe deployment order and rollback boundary

1. Record the current Git revision, Compose status and database backup; confirm
   there are no unreviewed VPS-local source changes.
2. Fetch and fast-forward to the reviewed commit. Build the backend and
   frontend images without deleting volumes or containers holding data.
3. Run `alembic upgrade head` with the newly built backend image. Migration
   0071 deliberately fails before adding constraints if historical tenant,
   group, identity or passenger ownership is inconsistent; 0072 persists the
   exact passenger identities authorized for each session; 0073 cancels older
   duplicate pending OTP rows before adding the one-pending-challenge index;
   0074 adds device sync acknowledgement, 0075 adds the bounded mobile-session
   metrics index, and 0076 adds the durable push ticket/receipt lifecycle.
   Investigate a failed migration rather than deleting or reassigning rows
   automatically.
4. Recreate only the changed backend/frontend services, then restart Nginx so
   its upstream address cannot remain stale. Do not recreate PostgreSQL,
   MinIO, Redis or unrelated workers merely to deploy these routes.
5. Verify the Alembic head, service health, `/nginx-health`, the expected 401
   from unauthenticated `/api/v1/mobile/me`, backend logs and an authenticated
   dashboard GC App read before enabling real users.
6. Run controlled Passenger, Client Manager and Coordinator journeys, followed
   by one interrupted document download and one offline attendance/reconnect
   test, before broad rollout.

For an application rollback, return backend/frontend to the recorded previous
image/commit while leaving additive migrations through 0076 in place unless a
separately approved database rollback has been rehearsed against a restored
backup. Do not run an automatic destructive database downgrade in production.
If 0071 fails its preflight, the release stops and the prior application stays
in service while the inconsistent rows are reviewed. Mobile rollback requires
building/publishing a higher-`versionCode` binary from the last-known-good
source and configuration, or using the approved Play Console rollback path;
do not assume an older APK/AAB can install over a newer version. The local
debug-key-signed verification APK is not a store release or rollback artifact.

## Remaining external validation and operational risks

1. Run a real WhatsApp OTP request/verification against the deployed API for
   eligible, ineligible, shared-number, rate-limited, expired and revoked cases;
   retain Meta delivery/failure webhook evidence without recording OTP or PII.
2. Exercise first login and relaunch on low-, mid- and high-tier Android phones,
   then disable networking and open itinerary, QR, passport, visa, ticket and
   common documents from the encrypted cache.
3. Test replacement/revocation while the app is foregrounded and backgrounded,
   including interrupted and ranged downloads through Cloudflare/Nginx/object
   storage, low disk, missing `Content-Length`, wrong MIME and checksum failure.
4. Run two Coordinator devices against the same group/activity, including rapid
   scans, repeated QR values, offline divergence, reconnect, completion and
   deterministic merged counts/missing-passenger views.
5. Validate push delivery, lock-screen redaction, deduplication and deep links
   for all three roles on Android and iOS.
6. Apply migrations to a production-sized database clone, inspect the new
   indexes with query plans, then execute migration upgrade/downgrade policy and
   rollback rehearsal. No production data migration is proven here.
7. Measure real cold/warm start, screen latency, sync bytes, document time,
   memory, database/vault size, battery, crash-free sessions and API
   p50/p95/p99. The synthetic payload benchmark must not substitute for these.
8. Produce the upload-key-signed Android AAB with protected production credentials,
   then compile/archive/sign the iOS project on macOS. Verify physical-device
   upgrade and account switching do not expose the previous account cache.
9. Confirm production EAS update URL/project/signing configuration. Native
   dependency or permission changes require a new binary and cannot be proven
   by an over-the-air JavaScript update alone.
10. Review the explicit no-biometric/no-device-lock product choice against the
    organization threat model and device-loss policy before public release.
11. Inject database, filesystem and Keychain/Keystore cleanup failures across
    process relaunch, then validate the UI retry and support repair path for an
    undeletable encrypted database/vault. Logout deauthenticates immediately,
    independently attempts keys and file/database cleanup, and keeps the
    process-local namespace fence closed, but physical deletion failure still
    needs an operational recovery procedure.
12. Add privacy-reviewed mobile crash, performance, sync-latency, cache-size and
    app-version-adoption telemetry without PII or document metadata. Crash-free
    sessions and version adoption cannot be claimed until that instrumentation
    is implemented and validated on physical devices.
13. Validate encrypted mid-transfer process termination and resume on physical
    Android hardware. Authenticated completed frames resume; a kill during one
    partially written filesystem frame intentionally discards that staging file
    and restarts the transfer rather than trusting truncated ciphertext.

## Deliberate scope and policy boundaries

- The optional group image on the multi-trip selector is not rendered because
  the authoritative group/mobile contract currently has no approved image
  field. No filename, document or client logo is guessed as a replacement.
- Coordinator passenger detail exposes the complete authorized operational,
  imported and custom-field projection, but it does not bypass existing
  least-privilege rules for passport numbers, MRZ, raw passport/visa/ticket
  files, internal notes or AI fields. Those fields require a separate explicit
  backend permission and audit policy before any mobile contract may expose
  them.
- Scanner and incident-entry forms intentionally do not use pull-to-refresh:
  a gesture refresh could interrupt camera or unsaved form state. Their source
  lists and completed/read-only Coordinator pages remain refreshable, while
  sync reconciliation continues silently in the background.
- Worker-only extraction and delivery-state transitions are discovered through
  authoritative manifest reconciliation. The new targeted propagation bridge
  covers interactive passenger/recipient/roster mutations; it does not create
  a second worker business-rule implementation.
- A corrupt encrypted database that still contains queued offline actions is
  preserved and fails closed. Automatic deletion in that condition would lose
  audited user work; a support/export repair workflow remains a future
  operational enhancement.
- A seven-day integrity-check skip applies only after both native SQLite
  connections confirm a clean close. Android/iOS force-stop cannot guarantee a
  shutdown callback, so the marker remains dirty and the next launch checks the
  database. This intentionally favors integrity over startup speed after an
  uncertain shutdown.
- Native PDF/image viewers still require a short-lived plaintext file in the
  application-private cache. It is fenced against logout/revocation and removed
  after viewing/startup cleanup; no plaintext download staging or public
  Gallery/Downloads copy is created.

## Completion rule

This hardening work is repository-verified and Android-emulator verified, but
not release-complete. Release completion still requires store signing, iOS
build evidence, deployed migration validation, real-provider OTP/push evidence,
physical-device offline/security tests and production-representative
performance measurements. Any future ledger entry must state the exact
command/environment/result and must not convert local unit, emulator or
synthetic evidence into a production claim.
