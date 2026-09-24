# ECR Checker

Documents now includes a third workflow at `/documents/ecr-checker` for checking
the printed phrase **EMIGRATION CHECK REQUIRED** on Indian passport back pages.
This is phrase detection, not a legal assessment of a traveller's eligibility.

## Operator workflow

1. Select up to 1,000 JPG/JPEG, PNG or WebP images, at most 10 MiB each.
   Include the whole back page, especially its top section. Existing passport
   upload security also applies (the default pixel limit is 24 megapixels).
2. Keep the page open until uploads finish. The browser sends three small
   concurrent upload chunks, each containing at most five files / 20 MiB.
   Each API process admits one ECR chunk for reading and image preparation at
   a time; other requests wait with their upload spools. Waiting does not hold
   a database connection. A cancelled admitted request retains its slot until
   its operation settles, so a decoder thread cannot outlive its memory slot.
3. Processing runs on the server. Reopen a saved check or reload its URL to
   see progress. Interrupted uploads can resume in the same browser tab by
   reselecting the original files. Duplicate filenames keep separate identities.
4. Download Excel once every selected image has reached a terminal outcome.
   The two columns are `File name` and `ECR`. Positive results are red `ECR`;
   readable back pages without the phrase are black `NA`. Uncertain images
   are `REVIEW`, and failed checks are `ERROR`. Neither is converted to `NA`.
5. Retry failed checks while their stored images remain available. Invalid
   uploads need a new batch with corrected images. Stored source images expire
   after seven days by default; result rows and Excel exports remain available.

## Runtime and accuracy boundaries

- Gemini model: `gemini-3.5-flash`, using the existing `GOOGLE_API_KEY`.
- High media resolution, minimal thinking, strict JSON and 200 maximum generated
  tokens. The prompt is about 100 text tokens and excludes personal-data output.
- Only a complete, valid response confirming a readable whole back page can
  yield ECR or NA. Wrong pages, blur, glare, cropped areas and ambiguous wording
  request review. Truncated/provider-invalid responses are failures.
- Malware scanning precedes storage. Original bytes are hashed for upload
  idempotency; stored images are normalized to a maximum dimension of 2,000
  pixels and stripped of metadata. The storage checksum applies to normalized
  bytes, independently of the original-upload checksum.
  The ECR upload path applies its size bound during security normalization,
  before allocating extra orientation/color copies. Other upload workflows
  retain their existing dimensions. ECR image preparation has two thread-held
  slots per process, including after caller cancellation; opaque RGB images
  skip the unnecessary transparency buffers.
- Tenant isolation and staff ownership match the Documents workflow. Coordinators
  and client managers cannot use ECR. Images are stored in the private bucket
  under the `ecr-checks/` namespace; storage keys are not returned to the browser.

## Throughput

The dedicated `ecr-worker` consumes `ecr_checks` with one Celery process and eight
asynchronous image lanes. Each task processes a maximum of 32 images before
requeuing the remainder, allowing passport-link checks and other batches to share
the worker. Queued images stay in private object storage and broker messages
contain only identifiers. An available
lane claims one image, persists its result, then claims the next. The runtime never
loads all 1,000 image bodies together. Database connections are held only for short
transactions during processing.

Redis spaces ECR provider attempts to **120 requests per minute** by default
(one start every 500 ms), including retries and across ECR workers. The concurrency
limit remains eight: increasing the request rate does not create more active image
lanes. Slow responses naturally reduce throughput. Interactive passport calls keep
their existing scheduler; this limiter only governs ECR requests.

The production worker has a 1 GiB memory limit and a one-CPU limit. These contain
worker resource use; they do not prove that the whole VPS has enough free memory.
Prefetch is one and completed results are durable, so an interrupted batch resumes
its unfinished work. Keep one ECR worker with the default memory allocation;
increasing process/container count multiplies active lanes and memory requirements.

At 120 successful requests/minute, the ideal processing floor for 1,000 images is
about **8.3 minutes**. Even 3,000 attempts (three for every image) need at least 25
minutes at that rate. Uploads, image preparation, response latency, backoff and
storage add time; these are capacity calculations, not measured completion times.
The 30-minute target requires at least 33.4 successful images/minute. The higher cap
leaves scheduling/retry headroom while bounded concurrency controls resource use.
Production throughput must still be measured on the actual VPS.

Key settings (defaults are provided in `.env.example`):

| Setting | Default | Purpose |
| --- | --- | --- |
| `ECR_MAX_CONCURRENCY` | `8` | Asynchronous image lanes per batch worker |
| `ECR_REQUESTS_PER_MINUTE` | `120` | Shared ECR attempt pacing, including retries |
| `ECR_GEMINI_MODEL` | `gemini-3.5-flash` | Explicit model, independent of passport extraction |
| `ECR_GEMINI_TIMEOUT_SECONDS` | `45` | Provider operation budget excluding quota admission wait |
| `ECR_GEMINI_MAX_ATTEMPTS` | `3` | Bounded transient provider attempts |
| `ECR_IMAGE_MAX_DIMENSION` | `2000` | Maximum stored/provider image dimension |
| `ECR_RETENTION_DAYS` | `7` | Retained source image lifetime |
| `ECR_WORKER_MEMORY_LIMIT` | `1g` | Production worker container memory limit |
| `ECR_WORKER_CPUS` | `1.0` | Production worker CPU allocation limit |

The database is the durable ledger. A renewable ownership lease prevents duplicate
delivery from running an already-owned batch. Recovery runs every minute and
republishes queued or expired work. Completed item results survive restarts;
only interrupted work is retried. A process crash between a provider response
and database commit can still lead to a repeated billable call.

## Cost and observed live results

Google's standard Gemini 3.5 Flash rate checked on 24 September 2026 was
$1.50 per million input tokens and $9.00 per million output tokens, including
thinking. High-resolution Gemini 3 images use approximately 1,120 image tokens.

- The supplied positive sample returned ECR in 2.63 seconds: 1,219 input tokens,
  18 output tokens and zero thinking tokens. That is $0.0019905 per image, or
  **$1.99 per 1,000 equivalent calls**.
- Eight concurrent calls using that same sample all returned ECR in 2.33 seconds
  wall time, each with 1,219 input / 14 output / zero thinking tokens.
- A blank synthetic image returned REVIEW, not NA.
- At 1,320 input and the full 200 generated-token allowance, 1,000 calls cost
  about **$3.78**, excluding retries, taxes and other infrastructure.

These are classifier smoke tests, not an accuracy study across different passports
or a production 1,000-file performance test. The metadata-only live report is
`outputs/ecr-checker/live-smoke.json` (no passport fields or images).

Sources: [pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash),
[media resolution](https://ai.google.dev/gemini-api/docs/media-resolution),
[project rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

## Deployment

The standalone checker was introduced by **0106_ecr_checker**. The current
passport-link extension also requires **0107_passport_ecr_checks**. See
[passport-link ECR and languages](passport-link-ecr-and-languages.md) for its
workflow and shared queue behavior. Use the repository's explicit production
Compose layering: `docker-compose.yml` plus `docker-compose.prod.yml` (add the
APNs overlay only where already configured).

Set `EXPECTED_DATABASE_SCHEMA_REVISION=0107_passport_ecr_checks` in the production
environment alongside the ECR settings. Readiness requires an exact revision
match. Build `backend`, `worker` and `frontend` with the release `APP_REVISION`:
the API uses a Compose project image while all background workers share the
explicit `passdetection-backend` image. Rebuilding only the API leaves the worker
image stale.

Build the backend/worker and frontend images, run `alembic upgrade head` using
the new backend image, and update the API, general worker, scheduler, dedicated
ECR worker and frontend. Reload/recreate nginx for its ECR multipart upload
allowance. Existing worker images should stay consistent with the release.
Confirm `ecr-worker` health, scheduler/general-worker health and
`/api/v1/health/ready`, then run a small real batch and verify its Excel before
tomorrow's full upload. The default 120 attempts/minute needs approximately
150,000–160,000 input tokens/minute at full utilization for typical images, plus
capacity for other Gemini features. Check worker/container memory during that
small run before increasing concurrency or scaling the worker.

No production deployment or live PostgreSQL/Redis/S3 queue test was performed
in the implementation session: the local Docker engine was unavailable.

## Implementation validation

- 127 backend tests and three subtests passed across focused runs: 58 classifier,
  20 runtime, 48 ECR-route/upload-security/upload-validator, and one migration
  test. Coverage includes parsing/retries/image bounds, API permissions/upload
  races/commit acknowledgement loss, durable worker recovery, Excel content/colors,
  and migration upgrade/downgrade compatibility.
- Memory admission tests verify two simultaneous ECR preparation threads, one
  upload operation per API process, no body reads while waiting, and slots held
  until decoder threads settle even when callers are cancelled repeatedly.
- The durable worker test processed 1,000 real SQLite result rows with simulated
  provider/storage/Redis, preserving 1,000 duplicate filenames and a maximum of
  eight concurrent calls. SQLite transaction serialization emulates the batch
  lock; PostgreSQL lock behavior was not exercised.
- Nine frontend unit/component tests and two mocked Playwright journeys passed,
  including upload/reload/retry/download and 1,000 results at a 390px viewport.
- The complete production frontend build, focused backend Ruff/mypy, migration
  topology and development/production Compose contract checks passed.
- Release revision alignment passed 14 readiness and migration-rehearsal unit
  tests. The actual PostgreSQL rehearsal was not run locally.
- The unrelated repository-wide frontend module-budget check still fails for
  `features/settings/components/dashboard-settings-page.tsx` (336 lines versus
  325, complexity 8 versus 7). That file is unchanged from HEAD.
