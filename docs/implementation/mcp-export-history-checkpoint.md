# Passport export history read checkpoint

Reviewed on 2026-09-30 in the isolated `codex/mcp-export-history` checkout,
based on `60fa04916529b2a2d5c613b990a834314517a658`. This finite slice adds
`list_group_export_history` and `get_group_export_history`. Local qualification
does not establish deployment, real Codex acceptance or Phase 4 closure.

The later [integrated release checkpoint](mcp-read-expansion-release-checkpoint.md)
records the 6,029-test combined regression, deployment of `ee648457` and actual
Codex acceptance of one history/detail page. Full enumeration, linkage to the
earlier delivered operation, file availability and the broad phase gates remain open.

## Contract and authority

Both tools require a current active superadmin connection with `mcp:read`, an
explicit agency UUID and group UUID, and the existing website
`AuthorizationPolicy.require_export_data` decision for that exact group. They
do not require or grant file-generation, artifact recovery or completion
authority. An export-only connection cannot call them. Retained image-export
history remains observable when image generation is disabled for the release.
Every request and cursor page rechecks current authority; an old checkpoint or
prior connection grants no continuing access.

The list requires `kind=passport_excel|passport_images`, a page size of 1–100
(default 25), and an optional signed cursor bound to the actor and all filters.
The detail requires a history UUID and numbered page, with 1–100 rows per page
(default 50). Both default `include_personal_details` and `include_deleted` to
false. Personal opt-in reveals the list's retained actor email or the detail's
frozen name, phone, email and passport number, with a separate fixed-metadata
sensitive-read audit. No personal values enter audit payloads.

Retained deleted groups require explicit `include_deleted=true` and current
website permission. This deliberately follows the read policy, unlike the
generation/options adapter's narrower current-exportable scope. Archived and
deleted groups retain history, while their current operational roster is empty
under the canonical lifecycle filter. Hard-deleted groups and history are not
reconstructed. Superadmins may observe another creator's checkpoint in the same
authorized group; the website's staff-owner restriction remains unchanged.

## Canonical semantics and bounds

Only `status=completed`, `format_version=1` rows are returned. List order is
completion timestamp descending, then UUID descending. The signed cursor uses
a completion-time cutoff, so an older prepared export completed after page one
does not enter that page walk. Counts and source membership remain live; this
is not a repeatable-read snapshot or a promise against manual removal.

New-submission counts compare one bounded set of current canonical roster IDs
against each cumulative checkpoint. They do not compare against an incremental
file's smaller exported subset or use submission timestamps. An invalid
cumulative checkpoint is returned as incompatible with a zero count explicitly
described as unknown. Detail validates exported IDs and frozen person snapshots
independently, preserves original order, and rejects invalid count/order/value
relationships without partial people. `record_available` means only that a
same-agency/group source row exists now; it is not file availability, current
roster membership, permission to recover an artifact or evidence of delivery.
Pending WhatsApp contact counts remain separate from exported passport counts.

The website list/detail routes use the shared pure item/person projectors and
domain validators without changing HTTP shapes, defaults or business policy.
The repository's exact group predicates are shared with its existing website
list. Invalid stored ID values are no longer copied into logs.

The MCP repository selects at most 5,001 scalar current-roster IDs to enforce
the website history ceiling of 5,000; it never hydrates passport/OCR objects.
This is independent of the smaller release limit for generation source rows.
Selected history rows are locked with SHARE NOWAIT, and their chosen metadata
and JSON columns are admitted by aggregate UTF-8 byte size before materializing
JSON. Artifact metadata is excluded from both admission and projection. The
configured checkpoint-byte budget is reported explicitly; current release
qualification used 1 MiB, while configuration permits up to 16 MiB. Each
checkpoint contains at most 5,000 people, and serialized output is capped at
512 KiB. Oversized complete data returns a static limit error, never truncation.
Even a small detail page may be unavailable when its complete retained snapshot
exceeds admission limits, because integrity validation covers the whole payload.

Authority locks precede group and history locks. Source contention returns a
static retryable busy result; a five-second async deadline bounds awaited work.
Cancellation leaves rollback to the existing invocation/session boundary.
There is no workbook rendering, storage initialization/access, artifact or
operation creation, history mutation, provider send, download or completion.
Only the normal fixed read audit and optional sensitive-read audit are written.

## Finite inventory reconciliation

Exactly six existing implementation records (source/OpenAPI/frontend for list
and detail) change from `planned` to `implemented_unverified`. Existing surface
contracts, dispositions, phases and inherited adapter requirements are retained.
Two new tool rows describe the actual metadata-only read effects. Completion
routes and all unrelated workflows remain unchanged. Inherited artifact and
delivery requirements apply to associated export workflows, not an assertion
that metadata discovery downloads or completes them.

## Local evidence

- Combined functional qualification passed 103 tests in 29.66 seconds: all new
  history cases, existing website history/repository behavior, release-family
  registration, Excel options/generation and staff access/visibility.
- After the final limit-label refinement, all 27 new functional cases passed
  in 11.25 seconds. These overlap the combined run. Actual local ASGI calls
  cover successful metadata/audit envelopes, static failures, read-only schema
  hints, export-only denial and capability narrowing between cursor pages.
- Independent PostgreSQL qualification passed 19 cases in 7.98 seconds using
  a fresh retained synthetic schema. It covers canonical website parity,
  another creator's same-scope history, privacy and safe sensitive audits,
  completion-cutoff/tied-UUID ordering and concurrent late completion,
  5,000/5,001 roster and checkpoint boundaries, aggregate UTF-8 admission before
  JSON materialization, group/history NOWAIT contention, cancellation during
  an authority wait with rollback/retry, fresh authority, retained deletion
  opt-in, and empty import-only pending history. This uses ORM-created tables;
  it does not qualify migrations, runtime DB roles or production capacity.
  Receipt: `outputs/mcp-export-history-postgresql-2.xml`. Earlier fixture-only
  failure evidence remains retained separately.
- Strict mypy passed for ten source files; scoped Ruff, 87 quality-budget
  ratchets and `git diff --check` passed. Root reviewed the ten exact new
  infrastructure edges and added the narrow architecture contract.
- Inventory drift checking passed with 1,496 surfaces and 71 tools; all 12
  inventory contract tests passed. An independent object comparison confirms
  exactly six implementation-only replacements and two new tool rows, with
  every existing contract, requirement, disposition and phase preserved.
- The full backend non-service regression passed on the final application/test
  source: **5,931 passed, 3 skipped, 332 deselected, 162 subtests passed** in
  **1,003.84 seconds** (16 minutes 43 seconds), process exit zero. Receipts:
  `outputs/backend-regression-history-20260930T053006.xml` and the matching
  `.log`. These counts overlap the focused checks and do not include the
  separate PostgreSQL lane. Root will qualify the later merged read-expansion
  candidate with its own combined regression.

No provider, VPS, production storage or real Codex activity is performed by
this slice's qualification. Coverage remains `implemented_unverified`; local
test success does not close deployment or broader workflow acceptance gates.
