# Travel-document production rollout

This document is the release contract for the WhatsApp, Visa Photo, passport
scanner, Gemini, staff-review, Relation with Qualifier, and public-upload
changes. It separates code evidence from checks that require a running staging
or production-like environment.

## Architecture summary

The existing workflow remains:

```text
durable front/back upload
  -> MRZ/OCR and interactive Gemini extraction
  -> traveller review and correction
  -> durable client submission
  -> asynchronous Gemini verification
  -> deterministic comparison
  -> AI approval or staff review
```

The public browser persists only opaque recovery identifiers in
`sessionStorage`: a bootstrap session id, upload idempotency key, submission id,
and, when enabled, the short-lived Relation with Qualifier bearer token. It
does not persist passport fields or image data there.

PostgreSQL remains the workflow source of truth. Celery provides separate
durable extraction and verification queues. Redis provides global atomic
Gemini admission control and distributed rate-limit counters. Nginx and the
application enforce complementary per-session and shared-network limits.

## Requirement-to-implementation matrix

| Area | Implementation evidence | Verification state |
| --- | --- | --- |
| Approved WhatsApp templates | `message_templates.py`, broadcast planner/provider, group-name-only UI, `whatsapp-approved-template-rollout.md` | Exact 2- and 4-body-parameter fixtures and provider payload tests; controlled Meta send still required |
| Visa Photo terminology and camera | `visa-selfie-camera.tsx`, `visa-selfie-quality.ts`; rear-camera preference, bounded model-inference watchdog, and explicit guided-fallback acknowledgement | Deterministic camera/quality/fallback tests and frontend build; real device calibration still required |
| Eyewear, face, and wall checks | Multi-frame face/eyewear, exposure, blur, tilt and structural background analysis | Synthetic/supplied-image tests; not a certified biometric or eyewear model |
| Passport live scanner | Passport layout, MRZ, portrait, text-block, orientation, quality, stability, and conservative critical-zone finger-obstruction gates | Detector/auto-capture tests and build; international device sampling still required |
| Crop and perspective correction | Four-corner correction with post-transform passport-content validation and original-image fallback | Deterministic correction tests; unsafe correction never replaces the original |
| Wrong-document rejection | Strict Gemini document class/page/quality schema and terminal wrong-document handling | Mocked schema, malformed-response, cover/wrong-page/wrong-document tests |
| Existing Gemini business flow | Durable extraction job before client review; durable verification job after submission | State-machine and use-case regressions |
| Strict Gemini priority | Two Celery queues plus Redis/Lua waiting, dispatching, active, quiet-period and lease state | Unit/concurrency tests; production-like capacity test still required |
| Reported rate-limit path | Public bootstrap, initial upload, follow-up and client-submit policies use separate per-session and aggregate guards | Middleware tests include 100 users behind one NAT; Nginx runtime test still required |
| Upload idempotency/recovery | Stable idempotency header, durable submission reconciliation, controlled reconnect screen | Pure recovery tests, lint, type-check and build |
| Staff approval 409 | Nine-field payload, required expected revision, optional reason, row lock, typed outcomes/conflicts and idempotent audit/QR | Focused route/use-case/repository/frontend tests; live PostgreSQL race test still required |
| Deterministic `NEEDS_REVIEW` | Field-aware Unicode/text/date/passport/country normalization; application owns final status | Exact/format-only/low-confidence/one-character mismatch tests |
| Relation with Qualifier | Per-link flag, canonical allowlist, one-time selection, submission snapshot, staff view and conditional export | Migration/domain/API/frontend/export tests; staging migration still required |
| Frontend reliability | In-flight guards, abort handling, bounded polling, transient bootstrap retry, session recovery | Frontend tests/type-check/build; iOS/Android/in-app-browser exercise still required |
| State machine | `passport-workflow-state-machine.md` | Reviewed against repository states; no duplicate queue states added |
| Observability | Shared fixed-enum upload/classification/verification/approval/rate-limit/camera/scanner events, AI priority counters/gauges, authenticated detailed snapshots, readiness calibration gate | Unit-level snapshots and documented initial alert thresholds; production dashboard/alert wiring still required |
| 100-user objective | k6 bootstrap/upload/poll/idempotency harness with p99 under 40-second gate | Harness syntax verified only; no result may be claimed until staging execution |
| Dependency and image hygiene | Patched Python security-sensitive pins, CI `pip-audit`, HS256-only JWT configuration, patched PostCSS override, and immutable MinIO release digest | Direct pinned Python audit and production npm audit are clean; full Python 3.11 resolution remains a CI/Docker gate |

## Database migration

`0037_relation_with_qualifier.py`:

- adds `client_groups.relation_with_qualifier_enabled`, defaulting to false;
- creates `qualifier_selections` with hashed unique token, approved-code,
  exclusivity and expiry constraints;
- adds immutable qualifier snapshots to `passport_submissions`;
- enforces one submission per selection and valid Self/relation combinations;
- binds the selection foreign key to the same `group_id`, so a submission
  cannot reference a selection issued for another upload link.

The downgrade removes qualifier selections and snapshots. Do not run it after
real selections exist unless a verified backup and explicit data-loss approval
are available. A safer application rollback is to disable the option for every
link and leave the additive schema in place.

## API contract changes

- Group create/update/read adds `relation_with_qualifier_enabled`.
- Public group read returns the canonical relation option list.
- `POST /api/v1/upload-links/token/{token}/qualifier-selection` creates one
  short-lived selection and returns its raw bearer token once.
- `GET /api/v1/upload-links/token/{token}/qualifier-selection` resumes it with
  `X-Qualifier-Selection-Token`; inactive links cannot resume selections.
- Initial upload accepts `qualifier_selection_token` when the group requires it.
- Public bootstrap calls require `X-Upload-Session-ID`.
- `POST /api/v1/upload-links/token/{token}/telemetry` accepts only fixed
  event/reason pairs and requires `X-Upload-Session-ID`; inactive or invalid
  bearer links return the same empty response without recording, so the route
  does not become a link-validity oracle.
- Initial upload binds `X-Upload-Session-ID` to
  `upload_idempotency_key`; every follow-up, stored-image, discard, and
  client-submit request reuses that private credential and validates it against
  the target submission. The public submission UUID is not an ownership proof.
  Public workflow JSON omits presigned document URLs; previews use credentialed
  blob requests instead.
- Staff approval requires `expected_extraction_revision`, accepts optional
  `review_reason`, and supplies `X-Staff-Approval-Outcome`.
- Staff conflicts return typed `STAFF_APPROVAL_STALE` or
  `STAFF_APPROVAL_UNAVAILABLE` 409 payloads.

## Environment variables

Public upload:

```dotenv
PUBLIC_UPLOAD_BOOTSTRAP_SESSION_RATE_LIMIT_PER_MINUTE=30
PUBLIC_UPLOAD_BOOTSTRAP_AGGREGATE_RATE_LIMIT_PER_MINUTE=600
PUBLIC_UPLOAD_SESSION_RATE_LIMIT_PER_MINUTE=6
PUBLIC_UPLOAD_AGGREGATE_RATE_LIMIT_PER_MINUTE=180
PUBLIC_UPLOAD_FOLLOWUP_SESSION_RATE_LIMIT_PER_MINUTE=120
PUBLIC_UPLOAD_FOLLOWUP_AGGREGATE_RATE_LIMIT_PER_MINUTE=6000
PUBLIC_UPLOAD_RATE_LIMIT_REQUIRE_REDIS=true
```

Gemini scheduler:

```dotenv
GEMINI_EXTRACTION_MAX_CONCURRENCY=32
GEMINI_VERIFICATION_MAX_CONCURRENCY=1
GEMINI_EXTRACTION_TIMEOUT_MS=30000
GEMINI_EXTRACTION_QUIET_PERIOD_MS=2000
GEMINI_RETRY_MAX_ATTEMPTS=3
GEMINI_PRIORITY_CAPACITY_CALIBRATED=false
GEMINI_PROJECT_ALIAS=<operator-verified-safe-alias>
GEMINI_CONFIG_VERSION=<deployment-config-version>
PROCESSING_WORKER_PING_TIMEOUT_SECONDS=1
PROCESSING_WORKER_READINESS_CACHE_SECONDS=15
```

An API key cannot reliably identify its owning Google project at runtime.
Production startup therefore reports only the operator-verified alias, selected
models, sanitized endpoint, configuration version, and whether a key is
present. Cross-check the alias against Google Cloud/AI Studio before setting the
capacity flag; never log the key itself. With Gemini enabled, production
readiness fails for a blank `GOOGLE_API_KEY`, an unconfigured alias, an
uncalibrated capacity flag, or a missing consumer for either exact AI queue.
This is a configuration/worker gate and does not make a provider request or
prove that the key is authorized.

WhatsApp values that the operator must set manually:

```dotenv
WHATSAPP_WELCOME_TEMPLATE_NAME=<exact approved welcome template name>
WHATSAPP_PASSPORT_LINK_TEMPLATE_NAME=<exact approved passport template name>
WHATSAPP_TEMPLATE_LANGUAGE=<exact approved language code>
```

The template-name fields are centralized in backend settings and the
repository-root `.env`; they are intentionally blank in `.env.example`.

## Dependency controls

The release updates `python-jose`, `python-multipart`, Pillow, `pillow-heif`,
`pypdf`, and Sentry SDK to audited fixed pins. CI resolves the production
requirements under Python 3.11 and runs `pip-audit`. The sole explicit
`ecdsa` advisory exception is constrained by the typed and tested HS256-only
JWT setting, so the affected ECDSA path is not selectable by configuration.

MinIO is pinned to an immutable multi-architecture release digest instead of
`latest`. Next's nested vulnerable PostCSS 8.4.31 is replaced with a scoped npm
override to PostCSS 8.5.15. A clean `npm ci`, all frontend tests, lint,
type-check, production build, and `npm audit --omit=dev` verify the resolved
dependency graph; remove the override after a future Next release natively
depends on an equally new or newer patched PostCSS version.

## Operational metrics and initial alerts

`/api/v1/health/metrics` and `/api/v1/health/diagnostics` require an
authenticated `SUPER_ADMIN`. Public liveness and readiness remain limited to
non-sensitive gate status. Shared Redis metrics use fixed labels only and
collapse unknown reasons to `other`; they never include tokens, traveller
fields, passport numbers, raw provider bodies, or browser fingerprints.
The TLS Nginx virtual host intentionally discards its unredactable
request-context error stream because legacy public paths contain bearer tokens.
Production diagnosis must retain the sanitized Nginx access log and
application/upstream metrics instead.

The production collector must calculate windowed deltas from the cumulative
Redis counters. Initial release thresholds are:

- extraction end-to-end p99 over 40 seconds for 5 minutes (critical at 45);
- Gemini 429 or timeout ratio over 2% for 5 minutes (critical at 5%);
- extraction queue p95 wait over 5 seconds for 5 minutes (critical at 15);
- upload failure ratio over 5% for 5 minutes;
- any aggregate upload-limit rejection during a controlled broadcast;
- any Redis coordination failure or required-worker readiness failure,
  critical when sustained for 2 minutes.

Do not page on ratio thresholds with fewer than 20 requests in the window.
`NEEDS_REVIEW`, wrong-document, approval-conflict, Visa Photo rejection and
passport-scanner rejection rates require a staging baseline before paging
thresholds are selected. Dashboard and alert-manager provisioning remains an
external release task.

## Staged deployment

Run these commands from the host PowerShell terminal in
`C:\Users\nipun\Desktop\PassDetection`, not from host Python and not from an
arbitrary container:

1. Back up PostgreSQL and the relevant MinIO buckets. Verify a restore into an
   isolated staging copy.
2. Populate every required secret and the variables above. Keep
   `GEMINI_PRIORITY_CAPACITY_CALIBRATED=false`.
3. Provision the trusted Nginx certificate/key files before startup. Plain
   HTTP exposes only `/nginx-health`; every application request receives a 308
   redirect to HTTPS. If an upstream load balancer terminates public TLS, its
   Nginx hop must still use TLS rather than forwarding sensitive traffic to
   port 80.
4. Drain WhatsApp jobs before changing the template contract.
5. Validate and build:

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
   python scripts/verify_compose_runtime.py
   docker compose -f docker-compose.yml -f docker-compose.prod.yml build backend frontend worker extraction-worker verification-worker nginx
   ```

   The production override is mandatory. It removes the development `/app`
   bind mounts, restores the backend image's Gunicorn command, forces
   `APP_ENV=production`/`APP_DEBUG=false` for backend workers, forces the API
   onto durable Celery dispatch and fail-closed Redis public-upload limiting,
   and keeps the frontend container and build on an explicit `NEXT_PUBLIC_*`
   allowlist instead of injecting the server `.env`. The production build also
   clears `NEXT_PUBLIC_DEV_APP_URL` so a development origin is not baked into
   the client bundle. Never run the capacity gate or production rollout from
   `docker-compose.yml` alone.

6. Apply the migration in staging:

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
   docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic current
   ```

7. Start the complete staging topology:

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d backend frontend worker extraction-worker verification-worker nginx
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec nginx nginx -t
   docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
   Invoke-WebRequest http://localhost/api/v1/health/ready
   ```

   Both dedicated workers must be healthy, and readiness must report
   `gemini_extraction_worker=available` and
   `gemini_verification_worker=available`. Their container probes target the
   exact Celery node and active queue, so a pong from an unrelated worker does
   not satisfy the check. The API caches its bounded queue inspection for 15
   seconds per process; allow that window after starting or replacing a worker.

8. Verify old links, one disabled and one enabled Relation with Qualifier link,
   staff approval, wrong-document handling, and both controlled WhatsApp sends.
9. Pre-seed verification work and run the controlled k6 harness with 100
   approved non-production fixture pairs. Capture backend, Redis, PostgreSQL,
   proxy and host resource metrics.
10. Tune concurrency from measured evidence. Only after the release gates pass,
   set `GEMINI_PRIORITY_CAPACITY_CALIBRATED=true` and recheck readiness.
11. Repeat the migration, controlled smoke checks, and coordinated
    backend/worker/frontend/Nginx rollout in production.

## Rollback

- Stop new WhatsApp sends and drain/reconcile the queue before changing code or
  template names. Restore backend, worker, both names and language together.
- Roll back backend, frontend and Nginx rate-limit/header changes as one unit.
  A new backend with an old frontend fails safely because required headers are
  absent, but delegates cannot proceed.
- Stop the dedicated AI workers before reverting queue routing. Do not leave
  tasks routed to queues with no consumers.
- Disable Relation with Qualifier on all links before an application rollback.
  Prefer leaving migration `0037` applied. Downgrade only from a verified backup
  when deleting persisted selections is explicitly acceptable.
- Permanent group deletion with data removal deletes all referenced passport
  front, thumbnail, back and Visa Photo objects, then deletes submissions
  before their restricted qualifier selections.
- Manager-owned data deletion and the global/agency passport-data purge use the
  same deduplicating collector, so front, thumbnail, passport back and Visa
  Photo objects are all included before database rows are removed.
- Restore the prior frontend image to roll back camera checks. Existing durable
  submissions remain server-readable.

## Manual release checklist

- [ ] Existing disabled Relation link follows the unchanged single/family flow.
- [ ] Enabled link forces one passenger and exactly one Self/relation choice.
- [ ] Friend, arbitrary relations, both paths and skipped selection are rejected.
- [ ] Refresh restores active/consumed relation choice and saved submission.
- [ ] Rear camera is preferred with no camera selector; fallback is controlled.
- [ ] A failed or stalled Visa Photo model exposes retry plus an explicit
  guided acknowledgement; positively detected eyewear keeps fallback locked.
- [ ] Glasses and structurally cluttered white backgrounds block Visa Photo.
- [ ] Plain white/off-white wall, one centred face and acceptable lighting pass.
- [ ] Aadhaar, PAN, cover, blank/generic page, sideways and upside-down scans do
  not auto-capture.
- [ ] Fingers entering the portrait, printed-detail, or MRZ zones block capture;
  a small edge grip that does not enter critical content remains usable.
- [ ] Minor skew is corrected; unsafe crop returns the original.
- [ ] Wrong documents receive a bounded traveller-safe message with no raw
  Gemini response.
- [ ] 100 shared-NAT bootstrap and upload requests receive no app/proxy 429.
- [ ] Verification does not start while extraction is waiting/dispatching/active.
- [ ] Lost upload response/reload reconnects or safely replays one idempotency key.
- [ ] Exact normalized fields AI-approve; one meaningful difference needs review.
- [ ] Two simultaneous staff approvals create one transition/audit/QR.
- [ ] Delayed AI completion cannot downgrade staff approval.
- [ ] Welcome preview has two body variables; passport preview has four; neither
  sends a dynamic header or organization parameter.
- [ ] Logs contain no image, raw prompt, token, full passport number or personal
  field values.

## Release blockers that cannot be waived by unit tests

- The 100-user k6 run must execute against a production-like Docker topology and
  controlled Gemini project before the capacity flag is enabled.
- Nginx syntax/runtime, PostgreSQL row-lock races, Redis/Lua multi-worker
  behavior, migration upgrade/downgrade rehearsal, Meta delivery and real mobile
  camera behavior require live services.
- Published Gemini RPM/TPM limits alone do not prove concurrent latency.
