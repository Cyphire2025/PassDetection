# My Photos foundational implementation and activation boundary

Status: development/test vertical slice plus inactive, unit-tested AWS Rekognition/S3 provider
adapters. Real biometric matching and production media delivery remain disabled until every
external activation gate in this document is complete.

## Scope and safety statement

My Photos is the passenger-facing, selected-trip experience for finding and privately downloading
event photographs. The application uses the terms **My Photos**, **Set up Face Scan**,
**Face Scan**, and **Verify your face**. It does not describe the flow as Apple Face ID, a
TrueDepth scan, a 3D scan, or device-biometric authentication.

The foundational implementation is designed around server-verified liveness, a group-scoped face
index, and direct external media delivery. The deterministic development provider exercises the
same application contracts without performing biometric verification or recognition. It is not a
security control and must never be represented to a passenger as proof of liveness.

This phase does not activate or require:

- AWS accounts, credentials, IAM resources, Rekognition collections, or paid provider calls;
- production object-storage buckets or delivery URLs;
- real event photographs, passenger faces, passport images, face vectors, or production identities;
- native AWS Face Liveness components on iOS or Android;
- the office archive uploader/rehydration agent; or
- production deployment or a claim of production readiness.

The Hostinger/VPS application remains the authorization and metadata control plane. It must not
proxy a group's 100-200 GB of photographs. Binary thumbnails, previews, and originals are never
embedded in JSON or stored in PostgreSQL.

## Passenger experience

My Photos is scoped to the authenticated passenger and currently selected tenant and trip. The
mobile experience is expected to expose these states explicitly instead of using one ambiguous
spinner:

- feature disabled for the group, provider not configured, no gallery, upload pending, processing,
  indexing, and gallery ready;
- not enrolled, consent required, camera permission required, ready, scanning, secure processing,
  cancelled, expired, rejected, cooldown, unsupported device, and provider unavailable;
- search queued, searching, complete with no matches, complete with matches, and matched media
  being prepared;
- cached offline results, partially cached results, expired or revoked server access, recoverable
  API failure, nonrecoverable failure, and deleted enrollment.

Enrollment consent is versioned and trip-scoped. The explanation covers purpose, data used,
provider processing, retention, revocation, and deletion. Preparation guidance requires one person
in view, even lighting, an eye-level phone, no mask or sunglasses where possible, and a steady
camera. A movement-and-light challenge is preceded by a photosensitivity warning and provides a
movement-only alternative. Local camera guidance can validate permission, framing, and accessible
instructions, but cannot create a production liveness pass.

The gallery uses bounded cursor pages and a virtualized thumbnail grid. It separates Best Matches,
Possible Matches, and the policy-controlled All Group Photos fallback. Grid cells use small
variants, not originals. Preview uses a medium variant or an already downloaded local original.
Original-quality and optimized-quality download actions are explicit. Public Photos/Gallery export
is also explicit and warns that the exported copy is outside PassDetection's control and can
survive application uninstall.

## Recognition and media model

A group gallery is indexed once. Registering or enrolling a late passenger does not iterate over
or reopen all group originals:

1. Register immutable internal media asset identifiers.
2. Validate media and generate grid, preview, and provider-analysis variants while preserving the
   source original.
3. Normalize processing orientation while retaining source metadata.
4. Index every detectable face occurrence into a group-specific provider collection once.
5. Map each opaque provider face identifier to tenant, group, media asset, occurrence, canonical
   bounding box, quality, and index/model version.
6. Publish a complete gallery/index revision atomically.
7. Search a passenger's single usable enrollment reference against the already-published group
   collection.
8. Resolve returned occurrence identifiers to media assets and upsert versioned passenger matches.

One photograph with several enrolled passengers remains one media asset with several face
occurrences and passenger-match associations. It is never copied per passenger. A late enrollment
searches the existing collection; newly added media is indexed incrementally and produces a new
published revision.

Enrollment input must contain exactly one usable face. No-face and multiple-face input is rejected
for retry; the implementation must not silently choose a largest face when another person is
visible.

Match thresholds are backend configuration with an auditable algorithm/configuration version.
Similarity values stay server-side. The client receives only display tiers and does not hardcode a
recognition threshold or display a liveness confidence score. Match feedback supports **This is
me** and **Not me**, leaving room for a second live reference and a future passenger-confirmed event
face. No implementation or product copy promises perfect matching.

Media state is deliberately decomposed. Recognition/index availability, thumbnail/preview
availability, original delivery, and office archive availability are independent. Supported domain
states include registered, awaiting upload, processing, indexed, preview available, original
available online, archived offline, rehydration requested, preparing delivery, delivery available,
expired, failed, and removed. Match metadata can remain available when an original is archived
offline; the application then says the photo was found and is being prepared rather than presenting
a broken download.

## Provider and trust boundaries

Provider-specific request and response types stop at adapter boundaries:

- the liveness provider creates short-lived single-use sessions and obtains the authoritative
  result server-side;
- the face-index/search provider indexes occurrences and searches an existing group collection;
- the media provider registers immutable storage references, reports variant availability, and
  issues or prepares narrowly scoped delivery authorization; and
- application services own consent, state machines, authorization, idempotency, match tiers,
  pagination, jobs, retention, and audit events.

The production target is Amazon Rekognition Face Liveness using
`FaceMovementAndLightChallenge`, with a movement-only accessibility/photosensitivity alternative,
and Rekognition group collections for occurrence indexing and late-enrollment search. AWS models
must not leak into application/domain schemas.

The native bridge is intentionally narrow. JavaScript initiates a backend-created session,
presents an official native component, and receives only lifecycle outcomes such as completed,
cancelled, expired, failed, or unavailable. Camera frames and liveness video never transit the
JavaScript bridge. The app must never embed or receive long-lived AWS credentials. The official
native component may separately obtain short-lived, least-privilege credentials from a reviewed
Cognito Identity Pool or custom temporary-credential broker solely to call
`StartFaceLivenessSession`; the backend still owns session creation, result retrieval, thresholding,
and the decision that liveness passed. Each retry creates a new session. Provider audit-image
retention defaults to disabled; reference-frame retention is allowed only when strictly necessary
for current and later gallery-revision searches, for an explicitly reviewed trip/enrollment window,
and with matching object lifecycle and deletion rules.

The deterministic provider is permitted only when the backend is explicitly configured for local
development or automated tests. A mobile flag cannot select it. Production startup/configuration
must reject the development provider, and missing production providers fail closed with the stable
capability state **Face Scan is not available yet**. There is no local-camera fallback that invents
a successful result.

## Authorization and API contracts

Every operation derives identity from the authenticated session and verifies tenant membership,
passenger ownership/delegation, group relationship, group lifecycle, feature capability, and exact
asset/enrollment group ownership. Account, passenger, trip, media, device, provider, and storage
identifiers supplied by a client are locators only, never authorization evidence.

Mobile contracts are strict on both sides:

- Pydantic and Zod reject unknown fields and malformed state combinations;
- bounded strings and arrays, stable machine error codes, and sanitized provider failures;
- idempotency keys on enrollment, liveness completion, and search mutations;
- stable cursor/keyset pagination with a hard server maximum and published-revision semantics;
- no provider face identifiers, storage keys, permanent URLs, stack traces, or raw provider errors;
- no thousands-row gallery payload in the general mobile synchronization snapshot; and
- realtime messages, when used, are invalidation hints followed by an authoritative refetch.

Short-lived direct media delivery authorization is issued only after server authorization. Delivery
objects are scoped to one passenger/group/asset/variant and have a bounded expiry. The VPS returns
metadata and authorization; external object storage streams the bytes.

## Durable jobs and publication

Indexing, variant generation, face search, and media preparation are durable, idempotent jobs on a
dedicated media route/queue. Jobs use bounded batches, checkpoints, attempt counts, retry backoff
with jitter, cancellation, terminal failure visibility, and lease/heartbeat recovery where the
worker topology supports it. Redelivery cannot publish duplicate occurrences or active matches.

Gallery publication is atomic: incomplete or partially failed work remains on an unpublished
revision until completeness policy passes. Partial asset failures remain observable. New revisions
supersede old match rows without deleting immutable media or rewriting every original.

Ingestion validation must eventually reject MIME/signature mismatch, unsafe types, corrupt media,
extreme dimensions/decompression bombs, duplicate hashes, unsupported provider renditions, and
invalid orientation metadata. Provider-analysis derivatives never modify originals. Overlapping
analysis tiles and canonical coordinate deduplication are an optional optimization only after a
representative-event benchmark demonstrates a need.

## Private downloads and retention

My Photos uses a dedicated gallery-media quota and durable queue rather than silently inheriting
the smaller document-vault quota. Files reside in application-private persistent storage, are
excluded from OS backup/restore where supported, and are namespaced by account, tenant, trip,
immutable asset ID, and quality. Manifest records address files; external filenames and storage
keys are never trusted as filesystem paths.

Download bytes are consumed from the authenticated Expo native response stream and immediately
encrypted into independently authenticated AES-GCM frames of at most 256 KiB. Only ciphertext is
written to the backup-excluded persistent staging file; there is no plaintext filesystem transfer
target or whole-media JavaScript buffer. Each short-lived authorization is range-, size-, and
asset-scoped, and every response must provide the exact status, content range, content length, and
allowed media type. The authorized total size and SHA-256 digest are verified by inspecting the
complete framed ciphertext before an atomic promotion makes the manifest report completion.
Cancellation, handled failure, and corruption leave at most authenticated ciphertext that recovery
can validate or discard. Devices whose runtime cannot expose the response body as a stream fail
closed with `NATIVE_STREAM_UNAVAILABLE`; they never fall back to a plaintext download. Signed
release-build validation on physical iOS and Android devices is still required to prove the Expo
streaming and filesystem behavior on supported production runtimes.
The queue coalesces duplicate asset/quality requests and repeated Download All actions, applies a
configurable conservative concurrency limit, checks free-space headroom, persists progress, uses
bounded jittered retry, refreshes expired authorization, and resumes valid byte ranges when the
provider supports them.

Queue states are queued, waiting for Wi-Fi, waiting for media preparation, downloading, paused,
retrying, completed, cancelled, failed, corrupt, expired authorization, and removed. Native
indefinite background execution is not claimed in this phase. Active work pauses safely when the
app cannot run, and the durable queue resumes when the same account returns and the application is
active.

Ordinary sign-out clears authentication, decrypted memory, preview/render caches, temporary viewer
files, sensitive navigation, query state, and active network operations. Completed My Photos
downloads and their encrypted retained manifest remain locked to the originating account on that
installation. A different account cannot discover filenames, thumbnails, counts, metadata, queue
state, or usable keys. The same authenticated account can unlock and reconcile completed files
without downloading them again.

This follows the application's existing ordinary account-lock behavior, which also retains the
encrypted account database, vault, keys, and durable queues for same-account recovery. My Photos
still has a dedicated quota, queue policy, and user-visible storage controls rather than inheriting
document-size assumptions. Explicit local removal, Clear My Photos Storage, account deletion,
device/application data wipe, uninstall, and a security-driven destructive revocation delete the
applicable retained data and, for account destruction, the account vault key. A photo-only removal
deletes its ciphertext and manifest without destroying the shared account vault key used by other
private vault content. **Remove downloaded copies**, **Delete Face Scan**, and
**Remove my face-search data** are separate actions; deleting enrollment does not silently delete
downloaded event media.

## Privacy-safe observability

Backend metrics may record gallery state transitions, queue depth, aggregate asset and occurrence
counts, job latency/failure category, rehydration requests, API page latency, authorization denials,
provider availability/throttling, and idempotent redelivery. Mobile metrics may record fixed event
names and aggregate timing/bytes for open, consent, scan lifecycle, search, first content, page
errors, thumbnail failures, downloads, resume, checksum failure, low storage, queue recovery, and
grid blank-area performance.

Metrics and logs must never contain photographs, face frames/crops/video, provider face identifiers,
liveness session identifiers, storage URLs, access tokens, passport data, raw provider payloads,
confidence values, or unnecessary personal identifiers. Correlation identifiers are random,
bounded, and non-biometric; failure reasons use a fixed low-cardinality vocabulary.

## Acceptance budgets and evidence

The following are engineering budgets for the controlled development scenario. A unit test passing
a structural bound is not a device-performance measurement.

| Concern | Development acceptance budget | Evidence classification |
|---|---|---|
| Gallery page size | Default 48; server hard maximum 60 | Contract/static test |
| Client records retained for first content | Initial page/window only; no 5,000-row eager request | Unit/integration instrumentation |
| Grid render batch | At most 24 items per batch and shared odd window size 5-7 | Existing mobile static list budget plus feature test |
| Metadata first-page API | Local controlled p95 <= 250 ms after warm process; record environment and query count | Measured only when the endpoint and database fixture run |
| Metadata page database work | Constant bounded query count per page; no query per asset | SQL instrumentation/EXPLAIN evidence |
| Search job memory | Bounded batch/checkpoint; never materialize all originals or binary media | Job scale test and worker observation |
| Download concurrency | Default 2, configurable within reviewed safe range | Queue unit/integration test |
| Download retry | Bounded exponential backoff with jitter and finite attempts | Deterministic clock/random test |
| Checksum | SHA-256 and exact authorized size before promotion | Corruption/short-write tests |
| Synthetic catalog | At least 5,000 assets, 57 representative matches, shared asset, mixed orientation/availability | Deterministic fixture tests |
| Release-device first meaningful content | Target p95 <= 1.5 s on defined staging network and reference devices | Future physical release-build measurement |
| Release grid responsiveness | No sustained blank region; collect frame/blank-area and memory evidence | Future Hermes release profiling |

Pre-feature repository evidence on the implementation workstation established a clean mobile
baseline: 162 Jest suites and 972 tests passed; aggregate coverage was 62.55% statements, 54.94%
branches, 58.57% functions, and 66.21% lines. Mobile typecheck, lint, dependency compatibility,
Expo Doctor, runtime audit, and maintainability gates also passed. Backend Ruff, compile, and
quality budgets passed. These numbers are baseline regression evidence, not evidence that My Photos
has been measured on a device.

Post-feature automated evidence on the same workstation is:

- full backend regression: 2,114 passed, 13 skipped, and 126 subtests passed in 118.89 seconds;
- focused backend My Photos/policy/migration: 68 passed in 6.20 seconds;
- real PostgreSQL/FastAPI service integration: one end-to-end scenario passed in 9.37 seconds;
- full mobile coverage: 205 suites and 1,201 tests passed, with 57.26% statements, 49.92%
  branches, 55.51% functions, and 60.58% lines; all eight critical-module floors passed;
- mobile TypeScript, full ESLint, runtime dependency audit, Expo dependency compatibility and
  Doctor (21/21), public configuration, maintainability, and guarded release-workflow contracts
  passed;
- canonical Python 3.11 mobile OpenAPI generation and verification passed; all 28 My Photos object
  schemas reject additional properties and all 13 My Photos operations require bearer security;
- production-mode Expo exports passed for Android (3,140 modules, 9.3 MB Hermes bytecode bundle)
  and iOS (3,050 modules, 9.1 MB Hermes bytecode bundle); these are bundle checks, not native
  compilation or physical-device evidence; and
- the deterministic 5,000-record load contract passed all six assertions.

A disposable local PostgreSQL 18 run upgraded 0085 -> 0086, downgraded back to 0085, and
re-upgraded to 0086. It inserted 5,000 assets in 4.50 seconds and completed the two-passenger
57-match/shared-asset search scenario in 182.58 milliseconds. Single controlled page reads measured
48.81 milliseconds for 34 Best rows and 25.07 milliseconds for 23 Possible rows with seven SQL
statements each; the committed integration budget permits at most nine including authorization
queries. A summary API request measured 197.81 milliseconds. These are workstation single-run
measurements, not p95 production or device-performance claims. The page contract defaults to 48,
hard-caps at 60, and never returns the 5,000-row gallery in one request.

The local workstation has Python 3.13, while backend CI and canonical mobile OpenAPI generation
require Python 3.11; the OpenAPI gate was therefore run in the canonical repository container.
The repository-wide strict mypy command has pre-existing debt: 68 errors remain in six legacy
modules, with no My Photos file in the failure set. `alembic check` likewise reports only known
pre-existing agency/user/refresh-token/client-group/passport/rooming drift and no My Photos
operation. Android and iOS native compilation, physical-device camera/streaming behavior, and
release-device performance remain unmeasured in this phase.

No release claim may infer frame rate, memory, background behavior, camera quality, liveness
correctness, or native bridge safety from Jest, a browser, Expo Go, or an emulator.

## Labelled-pilot evaluation harness contract

Real-event calibration is deliberately outside the source repository because it requires
separately consented biometric material. The future evaluator should consume two protected,
versioned datasets joined only by opaque pilot case IDs:

- a ground-truth table containing case ID, opaque passenger ID, immutable asset ID, whether the
  passenger is present, face-size bucket, lighting bucket, angle bucket, occlusion bucket, and
  reviewer agreement; and
- a result table containing case ID, provider/model version, analysis-rendition version,
  threshold-configuration version, returned tier, search latency, index outcome, and enrollment
  retry count.

The evaluator must reject duplicate case/asset identities, missing labels, unknown enum values,
unreviewed threshold versions, and results from a different gallery/index snapshot. It should
produce only aggregate metrics and bounded failure case IDs, never face images, storage URLs,
provider face identifiers, session identifiers, or passenger names.

For each version and representative segment it calculates:

- recall and false-rejection/missed-photo rate;
- wrong-person/false-acceptance rate;
- precision for Best Matches and Possible Matches separately;
- performance by face size, lighting, angle, and occlusion;
- indexing success/failure and faces indexed per applicable asset;
- search latency distribution; and
- enrollment retries and no-face/multiple-face rejection counts.

Threshold comparison uses a reproducible sweep over protected stored similarity results or repeated
provider evaluation, subject to the provider retention agreement. A threshold change creates a new
configuration version and a new report; it never rewrites historical evidence in place. Release
approval records dataset version, reviewer agreement criteria, minimum segment sizes, selected
thresholds, known exclusions, and rollback thresholds. Small or unrepresentative segments are
reported as insufficient evidence, not silently pooled into a success claim.

## Definition-of-done evidence checklist

This table is an acceptance ledger, not an implementation plan. **Implemented and tested** is
limited to the development/test vertical slice. It does not activate or validate AWS, production
object storage, the native liveness SDKs, or physical-device behavior.

| # | Acceptance requirement | Status | Evidence |
|---:|---|---|---|
| 1 | My Photos is discoverable in the passenger experience | Implemented and tested | Selected-trip card/routes plus `my-photos-trip-card.test.tsx` |
| 2 | Scope is the currently authorized trip | Implemented and tested | Real PostgreSQL tenant/group/passenger denials plus mobile context, account/trip switch, and stale-response tests |
| 3 | Major unavailable, loading, empty, error, and success states | Implemented and tested | Strict summary-state catalog, failure-copy, capability, queue, and rendered-state suites |
| 4 | Consent and Face Scan setup flow | Implemented and tested | Versioned consent API, camera-permission flow, reducer/controller lifecycle, movement-only, backgrounding, and accessibility tests |
| 5 | Deterministic development Face Scan can be exercised | Implemented and tested | Server-authoritative development provider, demo bootstrap, controller simulator, and real PostgreSQL/FastAPI scenario |
| 6 | Missing/incomplete production provider configuration fails closed | Implemented and tested | Independent settings and provider-factory guards reject development outside `APP_ENV=development`, reject partial AWS selection, and require explicit AWS scope, KMS, retention, calibration, key-ring, and temporary-credential configuration |
| 7 | Domain, migration, APIs, authorization, jobs, and provider abstractions exist | Implemented and tested | Alembic 0086, ten-table model/constraint suite, strict OpenAPI/API tests, provider tests, and worker recovery/redelivery tests |
| 8 | Late enrollment searches the existing 5,000-asset index | Implemented and tested | Real PostgreSQL scenario retains exactly 5,000 assets/6,000 indexed occurrences while searching existing mappings |
| 9 | Representative passenger receives 57 matches | Implemented and tested | Synthetic fixture and real PostgreSQL API assert 34 Best plus 23 Possible matches |
| 10 | One asset is shared by two passengers without media duplication | Implemented and tested | One immutable asset has two authorized passenger-match associations; database uniqueness and scale-contract tests pass |
| 11 | Stable cursor pagination and virtualized lazy rendering | Implemented and tested | Replayed/nonoverlapping/final-null cursor tests, hard maximum 60, bounded client gallery window, and virtualized grid tests |
| 12 | Grid thumbnails never load 4K originals | Implemented and tested | Variant/source and tile tests require thumbnail grid sources; originals are explicit viewer/download sources only |
| 13 | Download one, selected, and all work in development | Implemented and tested | Queue/repository/UI, selection, Download All enumeration, duplicate-coalescing, and delivery-authorization tests |
| 14 | Encrypted durable queue survives restart and ordinary logout | Implemented and tested | Ciphertext-frame, manifest/restart, runtime registry, session-lock, storage-lifecycle, and same-account recovery tests |
| 15 | Different account cannot see local photos or metadata | Implemented and tested | Account-namespaced SQLCipher manifest/enumeration tests and auth-context/runtime fencing tests |
| 16 | Low storage, corruption, interruption, cancellation, and retry | Implemented and tested | Space-plan, exact-range, short-write, checksum, atomic-promotion, cleanup, pause/resume, retry, and reconciliation suites |
| 17 | Indexed but offline media shows preparation/rehydration | Implemented and tested | Backend rehydration coalescing and availability contracts plus gallery/state passenger-copy tests |
| 18 | Reproducible 5,000-asset scale test passes against defined budgets | Implemented and tested within non-device scope | Six load-contract assertions plus real PostgreSQL 5,000-asset/page-query evidence; release-device render/memory/FPS remain future |
| 19 | Relevant quality gates pass or blockers are separated | Implemented and tested with recorded legacy exceptions | Backend/mobile/load/OpenAPI/Compose gates above pass; legacy mypy and Alembic drift are separately identified and contain no My Photos operation/file |
| 20 | No AWS resources, paid calls, production links, or real biometric data | Implemented and source-verified | My Photos source/dependency scan and production-provider guards pass; fixtures contain generated media bytes and synthetic UUID identities only |
| 21 | Inactive adapters are not represented as production proof | Implemented and tested | Capability/copy/logging contracts distinguish the development simulator, inactive AWS adapter code, and still-missing AWS/native/device/pilot activation evidence |
| 22 | Documentation defines the future AWS/native/storage boundary | Documented | Activation checklists below and explicit release statement |

## Inactive production provider boundary

The backend now contains testable production adapters, but every production choice and required
value remains unset by default. The only default provider selection is `disabled`. Selecting one
production adapter without the complete set
`aws_rekognition` / `aws_rekognition` / `s3` fails configuration validation. Activation also fails
until region, private buckets, separate liveness/media KMS key IDs, a stable scope-derivation secret,
a versioned active reference-signing key and bounded previous-key ring, a calibrated match config,
an explicit reference-retention window, and a reviewed native temporary-credential mode are set.
No My Photos setting accepts an AWS access key, secret access key, or mobile credential.

The implemented boundary is:

- `CreateFaceLivenessSession` is backend-owned, sends a stable idempotency token, maps the two
  challenge modes, always sends an S3 output location and explicit KMS key, and sends
  `AuditImagesLimit=0` by default. AWS documents the three-minute, single-use session and
  idempotency behavior in the
  [CreateFaceLivenessSession API](https://docs.aws.amazon.com/boto3/latest/reference/services/rekognition/client/create_face_liveness_session.html).
- The raw AWS `SessionId` is only the short-lived native launch/result handle. `Get` results are
  server-owned and statuses, confidence, threshold, no-face, multiple-face, pending, expiry,
  throttling, and provider failures are normalized to stable application outcomes. AWS's result
  shape is documented in
  [GetFaceLivenessSessionResults](https://docs.aws.amazon.com/boto3/latest/reference/services/rekognition/client/get_face_liveness_session_results.html).
- A pass is not represented by the three-minute session ID. The adapter requires the returned
  `ReferenceImage` to be the exact expected S3 output-prefix object, verifies its exact version with
  `HeadObject`, requires `aws:kms` and the configured liveness KMS key, verifies exactly one face,
  and stores only a signed, tenant/group-bound opaque reference handle. The handle contains an
  expiry for the explicitly configured retention window (up to one reviewed year), supports active
  signing-key rotation through at most three previous verification keys, and resolves to the exact
  S3 object/version for later `SearchFacesByImage` and enrollment deletion. Once it expires, search
  fails closed and the passenger must re-enroll; the S3 lifecycle must expire the object no earlier
  than the handle and must provide a final deletion backstop.
- Collection IDs are derived from a separate stable HMAC scope key and cannot be selected by a
  client. The adapter implements idempotent create/describe, `IndexFaces`, exactly-one-reference
  `SearchFacesByImage`, `DeleteFaces`, and collection deletion. It uses the documented 4,096 search
  and deletion bounds and stable per-asset external IDs. See
  [IndexFaces](https://docs.aws.amazon.com/boto3/latest/reference/services/rekognition/client/index_faces.html),
  [SearchFacesByImage](https://docs.aws.amazon.com/boto3/latest/reference/services/rekognition/client/search_faces_by_image.html),
  and [DeleteFaces](https://docs.aws.amazon.com/rekognition/latest/APIReference/API_DeleteFaces.html).
- Media keys are canonical, immutable, tenant/group-derived object references. Registration and
  delivery require exact size, MIME, dimensions, delivery version, `aws:kms`, the configured media
  KMS key, and S3-native `ChecksumSHA256` with `ChecksumType=FULL_OBJECT` from `HeadObject`.
  Uploader metadata SHA-256 alone is not accepted, and composite multipart checksums fail closed.
  Every registered object becomes a signed opaque key-plus-`VersionId` handle; indexing,
  availability, authorization, presigning, cancellation deletion, and re-head verification all use
  that exact version. S3's opaque VersionId boundary is 1,024 UTF-8 bytes and the persistence
  boundary is 4,096 bytes. Authorization persists only a short opaque HMAC grant, never a URL. The
  authenticated content route resolves that grant to a fresh HTTPS presigned `GetObject` URL and
  returns a 307 so the GET and Range header are preserved. Redirects include a no-store expiry
  header and accept only the exact configured custom S3 host/port/bucket path or the reviewed native
  AWS bucket/region host/path; userinfo, HTTP, fragments, wrong ports, lookalike hosts, and wrong keys
  fail closed. The URL is neither persisted nor logged by application code. AWS documents presigning in
  [Boto3 presigned URLs](https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html)
  and single-range retrieval in
  [S3 GetObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html).
- Synchronous SDK calls run through bounded asynchronous thread offload. Factory-created clients
  have explicit connect/read timeouts, standard bounded retries, and bounded pools; tests inject
  clients without contacting AWS. The default factory uses the standard AWS credential chain and
  passes no static key arguments. The native component must use temporary credentials as described
  by [AWS IAM temporary credentials](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp.html).

### Inactive production gallery-ingestion control plane

The backend now has a non-public, executable metadata control plane for media that was uploaded
directly to the reviewed S3 bucket. It is intentionally a trusted CLI, not an unauthenticated bulk
HTTP endpoint and not a binary proxy. An active agency admin or super admin must authenticate with
password plus a fresh replay-protected TOTP. Each batch remains bounded to 100 assets, one manifest
to 5,000 assets/50 batches, one JSON file to 1 MiB, and one authenticated file set to 50 MiB.

`register` accepts an ordered file list or directory, prompts once, preflights a single immutable
manifest header, and registers batches sequentially in independent idempotent transactions. A safe
rerun replays completed batch fingerprints and continues at the missing indexes. `--finalize` is
accepted only with every declared batch; no index job or partial publication exists before that
explicit final step. Provider choices, AWS scope/key identities, collection/model identity, match
configuration version, thresholds, retention policy, and availability window are frozen for the
manifest. A deployment/configuration change between batches is rejected instead of mixing policy
versions.

```text
python backend/scripts/register_my_photos_manifest.py register <batch-dir-or-files...> --actor-email <admin> --finalize
python backend/scripts/register_my_photos_manifest.py status --agency-id <uuid> --group-id <uuid> --manifest-identity <id> --actor-email <admin>
python backend/scripts/register_my_photos_manifest.py cancel --agency-id <uuid> --group-id <uuid> --manifest-identity <id> --actor-email <admin>
```

`status` reports received and missing batch indexes, counts, job state, cancellation state, and the
durable fingerprint checkpoint. `cancel` is safe only for an unpublished target. A running worker
is first stopped through `cancellation_requested_at`; repeated cancellation resumes bounded exact
provider-face and versioned-media deletion, accepts idempotent provider not-found outcomes, then
removes only that target revision's staged occurrences, variants, assets, and batch rows. A
previously published revision and all of its live provider/policy/window fields remain unchanged.
The active-revision uniqueness fence excludes fully cancelled manifests so a new manifest identity
can retry the same next revision. The command may need to be repeated while a worker stops or when
more provider-deletion batches remain.

Successful indexing still does not mutate the live gallery configuration while a successor is in
flight. `publish_gallery_revision` verifies exact manifest/job fingerprints and full coverage, then
atomically flips media/index revision, provider collection/model, match configuration, retention,
availability window, and publication status. Failed or cancelled indexing leaves the old gallery
readable. None of this source-level evidence proves the real S3/KMS/IAM, Rekognition, queue,
production database, backup, cost, or outage behavior; those activation gates remain below.

## Activation checklist

### External object storage

- [ ] Select a reviewed regional object-storage service and residency policy.
- [ ] Create private buckets/containers for source, analysis, preview, thumbnail, and temporary
      delivery variants with public access disabled.
- [ ] Configure service identities, encryption keys, multipart/resumable uploads, checksums,
      retention, lifecycle deletion, access logs, and object versioning as reviewed.
- [x] Implement and unit-test the media provider adapter without permanent URLs.
- [ ] Integration-test the adapter against the reviewed real bucket/KMS/role configuration.
- [ ] Prove short-lived asset/variant authorization, range semantics, exact length, checksum,
      expiry refresh, cancellation, and cross-tenant denial.
- [ ] Run failure, cost, quota, regional outage, and deletion/restore rehearsals.

### Office archive uploader and rehydration agent

- [ ] Define an authenticated device identity and least-privilege enrollment/revocation process.
- [ ] Validate canonical paths, MIME signatures, decompression limits, duplicate content, and
      immutable checksums before upload.
- [ ] Implement checkpointed multipart upload directly from the office archive to object storage;
      never through the VPS.
- [ ] Require office checksum verification, index mapping verification, variant verification, and
      retention approval before cloud-original deletion.
- [ ] Implement leased rehydration requests, resumable transfer, idempotent acknowledgement,
      bounded retries, terminal visibility, and delivery TTL cleanup.
- [ ] Rehearse an offline office archive, partial disk failure, process kill, duplicate request,
      credential revocation, and backlog recovery.

### Rekognition group face indexing

- [ ] Provision one reviewed, tenant/group-isolated collection strategy and backend-only IAM role.
- [x] Implement and unit-test the provider adapter for collection lifecycle, occurrence indexing, deletion, and
      search without leaking AWS models into domain/API code.
- [ ] Integration-test the adapter against real group collections, service quotas, and the selected
      provider-analysis rendition.
- [ ] Benchmark provider-compatible renditions and dense/wide group images before enabling tiles.
- [ ] Validate exactly-once occurrence mappings, canonical bounding boxes, duplicate callbacks,
      per-asset idempotency, partial failures, model/index versioning, and atomic publication.
- [ ] Prove late enrollment searches the existing collection without reopening 5,000 originals.
- [ ] Add provider quota, throttling, outage, reconciliation, collection deletion, and cost alarms.

### Rekognition Face Liveness backend sessions

- [x] Implement and unit-test backend session creation and result retrieval without long-lived AWS
      credentials in app configuration or mobile code. The native component still requires a
      reviewed temporary-credential provider for `StartFaceLivenessSession`.
- [x] Default to `FaceMovementAndLightChallenge`; map and unit-test the movement-only alternative.
- [x] Enforce single use, short expiry, new-session-per-retry, retry limits, cooldown, replay
      protection, idempotency, and server-authoritative completion.
- [x] Reject no-face and multiple-face reference images at the provider boundary.
- [x] Disable audit-image retention by default in code and require an explicit reference-frame
      retention value before AWS selection can validate.
- [ ] Approve the real reference-frame retention, bucket lifecycle, KMS/key-rotation policy, and
      deletion schedule only if search requires it.
- [x] Sanitize adapter errors and keep provider IDs/URLs out of public error contracts.
- [ ] Prove deployed logs/analytics contain no sessions, frames, provider
      response blobs, or liveness confidence.

### Native iOS liveness bridge

- [ ] Add the official supported AWS iOS/Swift Face Liveness component in an Expo development-build
      compatible native module/component.
- [ ] Keep frames/video native and expose only bounded lifecycle events to JavaScript.
- [ ] Handle cancel, background, privacy cover, screen-capture policy, call interruption, network
      loss, expiry, orientation, VoiceOver, Dynamic Type, reduced motion, and photosensitivity.
- [ ] Test signed development and Release builds on representative physical iPhones.
- [ ] Review binary size, SDK supply chain, privacy manifest, entitlements, crash logs, memory, and
      camera lifecycle before rollout.

### Native Android liveness bridge

- [ ] Add the official supported AWS Android Face Liveness component in the generated/prebuild
      native project boundary.
- [ ] Keep frames/video native and expose only bounded lifecycle events to JavaScript.
- [ ] Handle permission denied/blocked, missing/front-camera failure, cancel, background, privacy
      cover, phone interruption, network loss, expiry, orientation policy, TalkBack, font scale,
      reduced motion, and photosensitivity.
- [ ] Test signed development and Release-Hermes builds on supported API levels and representative
      low/mid Android hardware.
- [ ] Review dependency compatibility, R8 rules, binary size, SDK supply chain, privacy declarations,
      crash logs, memory, and camera lifecycle.

### Media-delivery authorization

- [x] Bind every backend grant to authenticated passenger, tenant, group, immutable asset, variant,
      delivery version, byte size/checksum, and short expiry.
- [x] Reject cross-group media identifiers and revoked, superseded, expired, removed, or
      unavailable variants.
- [x] Implement fresh presigned resolution and range-preserving redirect without scope widening.
- [ ] Prove refresh/resume behavior with the native encrypted downloader against real S3 on physical
      release devices.
- [ ] Confirm thumbnails/previews/originals travel directly from object storage/CDN and never as
      JSON/Base64 or bulk VPS proxy traffic.
- [ ] Load-test authorization and object delivery separately and monitor cache isolation,
      bandwidth, egress cost, expiry, and denial metrics.

### Real-event threshold calibration

- [ ] Obtain separately consented, labelled pilot photographs representing actual MICE lighting,
      angles, face sizes, occlusion, group density, aging, glasses, and appearance changes.
- [ ] Define recall, wrong-person/false-acceptance rate, false-rejection rate, Best precision,
      Possible precision, face-size segments, scan retries, search latency, and indexing failures.
- [ ] Version datasets, provider/model, renditions, thresholds, and configuration.
- [ ] Select thresholds from measured event data and reviewed risk tolerances, not vendor marketing.
- [ ] Establish human review/escalation and threshold rollback procedures.
- [ ] Delete or retain pilot biometric material only under its reviewed consent and retention plan.

### Security and privacy review

- [ ] Complete biometric-purpose, consent, jurisdiction, retention, deletion, data-residency,
      processor/subprocessor, incident-response, and data-subject-request reviews.
- [ ] Threat-model provider sessions, callbacks, collection isolation, media grants, local retained
      vaults, account switching, rooted/jailbroken devices, backups, screenshots, analytics, and
      operator access.
- [ ] Verify transport and storage encryption, key rotation, least privilege, secret management,
      rate limits, replay protection, audit redaction, deletion propagation, and backup exclusions.
- [ ] Inspect signed-device storage after logout, account switch, removal, revocation, force-stop,
      reboot, restore, reinstall, and uninstall.
- [ ] Approve passenger copy, photosensitivity alternative, accessibility behavior, and public
      export warning.

### Controlled pilot and rollback

- [ ] Enable the feature server-side only for named pilot tenants/groups with trained support and
      an All Group Photos fallback policy.
- [ ] Establish go/no-go budgets for match quality, enrollment completion, provider failures,
      authorization errors, delivery integrity, search latency, and support incidents.
- [ ] Rehearse capability disablement while preserving lawful passenger deletion/export rights.
- [ ] Rehearse provider outage, queue drain, gallery unpublish/re-publish, threshold rollback,
      native build rollback, credential revocation, and media-delivery shutdown.
- [ ] Monitor privacy-safe metrics and review wrong-person feedback before expanding the cohort.
- [ ] Record pilot acceptance, residual risks, owners, expiry dates, and rollback authority.

## Release statement

Real AWS Face Liveness, real Rekognition facial indexing/matching, and production cloud media
delivery are **not active** in this phase. The feature must not be called fully production-ready
until real-account adapter integration, the gallery-ingestion/admin seam, storage/IAM/KMS/lifecycle
activation, temporary native credential brokering, native physical-device validation,
security/privacy review, representative MICE calibration, and a controlled pilot with a tested
rollback have all passed.
