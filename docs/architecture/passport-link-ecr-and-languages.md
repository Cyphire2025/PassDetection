# Passport-link ECR, instruction languages, and PDF review

Group creation and editing store the new options in the existing versioned
`upload_configuration` JSON. Legacy configurations default to ECR disabled and
English instructions. Public clients receive only that link's configuration.

## ECR on passport links

The Passport section includes an ECR toggle. When device uploads are available,
enabling it requests the address details page and prevents that page from being
unchecked until ECR is disabled. The page selection disclosure starts open.
Camera collection already captures both personal and address details pages.
The backend independently validates these rules.

Only a finalized `passport_back_s3_key` is eligible. Front pages, outer covers,
visa photographs, draft uploads, and extracted passport text are never alternate
ECR sources. An optional passport that was not supplied has no AI request.

Final submission stages a durable check in the same database transaction as the
submission, then publishes a worker notification after commit. A broker outage
therefore does not lose the work. Scheduled recovery also discovers existing
finalized back pages when ECR is enabled later for a group.

The `passport_ecr_checks` ledger binds results to a submission, source key,
generation, and worker lease. It records source SHA-256, model, attempt counts,
token usage, timestamps, and a fixed reason code rather than passport contents.
Workers recheck opt-in, source identity, and their lease after pacing and before
each provider attempt, and again before saving. A disabled group or replaced
source invalidates an in-flight result. A request already sent before a toggle
cannot be recalled, but its result cannot be saved as current afterward.

Passport checks and Documents batches use the same `ecr_checks` queue, one worker
process, and eight asynchronous lanes by default. Each task drains at most 32
images and places further work at the queue tail. Images stay in private object
storage until an available lane reads one bounded image. The shared ECR-only
pacer defaults to 120 provider attempts/minute, including retries. Existing
interactive extraction and verification retain their separate scheduler.

Provider attempts and job executions are bounded separately. Infrastructure
recovery cannot turn a failed image into an unlimited provider retry loop.
Handled database/pacing interruptions and cancellation return uncompleted jobs
to the queue without exhausting their image retry allowance. Already reserved
provider attempts stay charged. Claim and refund transactions settle before
cancellation propagates, and an image-specific exception does not cancel
neighbouring checks.
Completed results survive worker restarts; the existing deployment must retain
the dedicated ECR worker and Beat scheduler. Rate and concurrency values are
capacity controls, not a guarantee of latency or classification accuracy.

## Excel behavior

Single-group, selected-passport, combined-group, and WhatsApp tracking exports
include an `ECR` column when at least one included group enables it. The lookup
is restricted to the authorized agency and exported submission IDs. It compares
each exported snapshot's back-page key with the current source, so a newer image
cannot contribute a verdict to an older exported snapshot.
Application replacements use fresh storage identities. This relies on the
application's immutable-source convention; manually overwriting a completed
check's bucket object under the same key is outside that export guarantee.

| Cell | Meaning | Font |
| --- | --- | --- |
| `ECR` | Readable back page with the phrase | Red, bold |
| `NA` | Readable back page without the phrase | Black |
| `PENDING` | Check has not finished or the source changed | Amber |
| `REVIEW` | Wrong, unreadable, ambiguous, or missing back page | Amber |
| `ERROR` | Check failed after bounded handling | Amber |
| Blank | ECR disabled for that row's group, or traveller not submitted | Default |

The red and black styles reuse the standalone ECR exporter. Unresolved checks
are never represented as `NA`, and user-entered passport fields cannot supply an
ECR verdict. Exports are snapshots: download again after pending work completes.

## Optional instruction languages

Miscellaneous includes a Multiple languages switch and ten optional languages:
Marathi, Hindi, Telugu, Kannada, Gujarati, Bengali, Odia, Malayalam, Tamil, and
Urdu. English is always the default, is first in the public selector, and is not
an option to check in group settings. Enabling multiple languages requires at
least one additional language. Disabling the switch retains saved choices for
later use while public pages display English.

Translations are prewritten copy, with no translation service or additional AI
request. The public selector appears on passport-page upload and visa-photo
upload. It changes only the passport introduction and page descriptions, plus
the visa warning and two sample captions. Headings, action buttons, and sample
illustrations remain unchanged. The preference is scoped to the link and kept
in browser session storage between steps; denied storage falls back to memory.
Urdu descriptions use right-to-left text without reversing the page layout.

## Multiple-PDF assignment review

Document Distribution includes a `Multiple PDFs` filter and affected-person
count, with an assigned PDF count on each matching row. The server counts
distinct matched storage keys per passenger ID in the current document scope.
People with identical names remain separate. Several ledger rows referencing
one physical PDF count once. Counts cover the complete review result rather
than only the currently rendered rows and refresh after assignment changes.
Search and filtered Excel export apply to the selected filter.

The filter is a review aid. It never unassigns, merges, replaces, or sends files.
Existing duplicate-filename decisions and delivery behavior remain intact.

## Deployment and verification boundary

This change requires migration `0107_passport_ecr_checks`, following
`0106_ecr_checker`. Update `EXPECTED_DATABASE_SCHEMA_REVISION` to
`0107_passport_ecr_checks`; other existing ECR environment values can stay as
configured. Build consistent backend/general-worker/ECR-worker/scheduler images,
apply `alembic upgrade head`, and update the frontend using the explicit
`docker-compose.yml` plus `docker-compose.prod.yml` production layers.

Before large production use, verify readiness and worker health, then exercise
an enabled and disabled link, an ECR and a non-ECR back page, language changes
across both upload steps, and the generated Excel. Check memory, queue delay,
provider errors, and successful images/minute while ordinary passport traffic
also runs. Local unit and mocked-browser tests do not establish PostgreSQL lock
behavior or throughput on the VPS.

Implementation checks include configuration/legacy serialization and validation,
all existing Excel-export regressions, workbook verdicts and actual cell colors,
cross-agency and stale-source gating, lease takeover and cancellation, bounded
provider attempts, queue continuation publication failure, and the persisted
1,000-image simulation. The simulation uses SQLite and simulated provider,
storage, and Redis; it verifies work accounting and the eight-lane bound, not
real service performance.

The frontend production build and TypeScript check pass. Mocked browser journeys
exercise group creation/editing and language changes across both public steps on
desktop/mobile, including reload, fallback, and Urdu bidirectional text. The
repository-wide maintainability budget check still reports the pre-existing,
unchanged `dashboard-settings-page.tsx` budget overage.

Whole-backend quality checks also expose unrelated failures in unchanged files:
three Ruff import-order findings (`traveller_welcome_preview.py`,
`whatsapp_exports.py`, `whatsapp_source_groups.py`) and eight mypy errors across
`traveller_destinations.py`, `document_distribution_delivery_preview.py`,
`admin.py`, `whatsapp_exports.py`, and `whatsapp_send.py`. Focused lint and strict
type checks for this feature pass; the entire repository is not being reported
as passing every quality gate.

Final focused validation totals: 435 backend tests and two subtests across configuration/export
and readiness (192), existing classifier/ECR API/migration (82), standalone
bounded runtime (25), PDF assignment/export (7), and passport ECR plus final
submission/contact/route regressions (129). The pre-push check also extracted
final-submission transaction side effects into a focused helper; the changed
submission and export routes satisfy their size/complexity ratchets. The global
backend ratchet still flags existing unrelated routes.
Frontend checks passed 98 settings/language
unit/component tests, 14 PDF model/contract tests, one PDF filter interaction
test, and seven mocked browser journeys. The final Urdu mobile and repeated
cancellation regressions were rerun after their fixes; those reruns are not
counted as additional distinct cases. Migration topology and development/
production Compose configuration checks passed.
