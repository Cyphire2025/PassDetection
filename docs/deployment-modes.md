# Choosing a deployment

Ordinary pushes to `main` run CI checks; an explicitly requested CI pause uses
GitHub's `[skip ci]` commit marker and does not count as passing qualification.
Production deployment is a separate,
explicit choice; a background CI run does not later overwrite a fast release.

## Explicit document-distribution VPS Fast exception

`document_distribution_updates_v1` has a narrowly reviewed operator path for the
explicitly requested VPS-based Fast deployment. From the clean, exact main-revision
source clone in the private retained attempt directory, its entrypoint is:

```console
python3 -B scripts/release_retained_update.py --revision <full-main-sha> --mode fast
```

This exception admits only the reviewed 0138→0139→0140 nullable-column migrations,
document worker/task additions, and the exact four-service RAM redistribution.
Ordinary Fast deployment policy remains unchanged. No signed Full artifact is
accepted in Fast mode, and evidence explicitly records `full_ci_qualified: false`.
The installed signed-CI dispatcher continues to invoke Full mode separately.

Fast requires unchanged backend dependency locks. It retains the inspected live
backend/frontend images as runtime bases; it does not apply or qualify native
runtime/Dockerfile changes. Background workers and the scheduler are gracefully
drained while the bounded VPS builders and exact-image migration rehearsal run.
The rehearsal uses synthetic PostgreSQL data and the built image's packaged
migrations/helper, with no application-source overlay or production credentials.
Its private receipt must prove source upgrade, intermediate resume, target replay,
lock failure, original row/catalog/ACL preservation, wrong-baseline rejection and
initially-null new columns. An unknown running helper prevents workers resuming.

Before the live fence or DDL, both release modes additionally run the exact-image
sender/frontend/Redis resource qualifier. The receipt binds image IDs, source
revision, profile/overlay and qualifier/executor hashes, and requires zero pressure
or OOM events and zero provider calls. Fresh host capacity, no swap, the complete
original container inventory, exact migration credentials, verified database archive
and source preservation digest remain mandatory. The new Redis containers retain
the exact original data volumes; the old containers remain stopped and intact.

Recovery uses `--recover-receipt <private-attempt-checkpoint>` with the same source,
revision and mode. It revalidates the original build, migration and resource
receipts and performs forward recovery; it never rebuilds an image, replaces
qualification evidence, downgrades the schema, or restarts source-schema writers
after the migration. Selecting this deployment path does not authorize any
document resend or update broadcast.

## Routine CI feedback

Automatic pull-request and branch checks start with **Plan affected checks**.
The plan compares the complete PR against its base, not just the latest commit,
so an earlier failing change cannot disappear behind an unrelated follow-up.
A push uses its previous commit only when that commit has a successful required
CI gate; otherwise it checks all components, carrying unresolved work forward.
Unknown files and shared CI, dependency-policy or infrastructure changes select
broader checks. The GitHub run summary lists every decision.

Recent successful backend tests, real-service tests, migration rehearsals,
browser journeys and connector tests may be reused when their complete tracked
inputs are identical. This includes tests, dependencies, shared configuration,
CI rules and known cross-component consumers. Evidence comes from GitHub's
actual successful job records, with the original run link and completion time;
an immutable, hash-verified planner artifact binds each result to its original
checkout and PR base. GitHub's current PR association is not historical proof.
Runs created before this evidence was recorded must execute fresh. Evidence
expires after 24 hours. A newer matching-input failure blocks reuse. Missing
history, changed PR bases or ambiguous evidence cause fresh checks. Reused jobs
are visibly skipped and identified as reused in the summary; they are not
described as new test executions.

Backend tests run in four isolated runner jobs, each using four test workers.
The aggregate verifies that all collected tests occur exactly once, combines
every coverage database and applies the existing coverage floors. This uses
more runners concurrently to reduce elapsed time; actual savings depend on
runner availability and test durations.

Image builds and qualification start alongside the other tests. Whole-image
security scans run immediately after building, before the longer runtime
rehearsals. Dependency audits and selected image qualification run fresh.
Only explicit Full releases export and sign deployable image archives.

**Required CI checks** always reports an outcome. It rejects failed, cancelled,
missing or unexpectedly skipped work. Publication also requires fresh image
and connector jobs. A large PR can still require image qualification after a
small follow-up because its cumulative change includes runtime changes; this
flow does not promise that every update completes in a few minutes.

When adding a new cross-component test or build input, update
`scripts/ci_job_inputs.py` in the same change. Updating that policy invalidates
prior verification. Unsupported current Git objects stop planning rather than
silently authorizing a skip.

## Full and Fast releases

Use **Full** for security/dependency changes, broad changes, or a thoroughly
qualified release. In GitHub Actions open **CI/CD — PassDetection Platform**,
choose **Run workflow**, select `main` and `deployment_mode: full`. This runs
the complete checks, publishes signed image digests and deploys those exact
images after all required jobs pass. `deployment_mode: none` runs checks without
production promotion. Both manual choices run every check fresh, without
historical result reuse. The actual workflow display name can change; the file is
`.github/workflows/ci.yml`.

To retry a failed promotion or deployment, use **Re-run failed jobs** on that
same workflow run. Publication can reuse an existing release only when its tag
and every retained artifact match exactly. A fresh Full run for an already
released commit may produce a different run inventory or build output and will
be refused; existing release artifacts are never overwritten.

Use **Fast** for small code-only changes when the shorter path is appropriate.
It builds on the VPS, checks the API contract and application startup, takes a
database backup, and checks health after cutover. It does **not** qualify the
change with the full CI/browser/security test suite or create signed CI images.
The receipt always records `mode: fast`; it never reports full qualification.
Dependency, schema, persistent model, storage, deployment configuration and
queued-task contract changes are refused. Choose Full for dependency changes;
schema or persistent configuration changes need a separate reviewed rollout.
The exact document-distribution exception above and Companies additive exception
below provide such rollouts for explicitly selected operator Fast releases;
neither relaxes ordinary Fast.

The selector prints a read-only plan unless `--execute` is supplied. Use the
full 40-character SHA that is currently on `main`:

```text
python scripts/release_deploy.py --mode full --revision <40-character-main-SHA>
python scripts/release_deploy.py --mode full --revision <40-character-main-SHA> --execute

python scripts/release_deploy.py --mode fast --revision <40-character-main-SHA> --key <administrator-private-key>
python scripts/release_deploy.py --mode fast --revision <40-character-main-SHA> --key <administrator-private-key> --execute
```

Both choices use Git to verify current `main`. The Full command also requires
authenticated GitHub CLI; the GitHub Actions button works without installing it.
Fast requires a separate administrator SSH key with a verified host key.
The CI deployment key remains a restricted `deploy-qualified:<SHA>` entrypoint;
it cannot request Fast or execute an arbitrary shell command. Never copy an
administrator key into GitHub Actions. `expected_revision` binds a Full manual
dispatch to the selected SHA; the workflow and VPS reject a superseded commit.

## VPS behavior and recovery

The installed `/opt/globalconnect-release-tools/release_ci_dispatch.py` launches
a retained systemd job so a disconnected terminal does not kill the deployment.
Install reviewed dispatcher changes outside the checkout as root before first
use. The dispatcher downloads exact source into a new private directory below
`/opt/GlobalConnectsDashboard/tmp/mcp-direct-<SHA>-<attempt>/source` and runs its
`scripts/release_retained_update.py`. Logs, source, images, builders, database
backup and step receipts stay on the VPS. Receipts contain private runtime
configuration and must never be attached to public issues or CI artifacts.

The updater discovers the exact running services from Docker inspection. It
supports the existing retained-clone layout without inventing missing Compose
file labels. It preserves existing environment settings, resource limits,
mounts and networks. It creates new app/proxy containers, drains old ingress
and application processes, then starts and checks the replacement set. There
is a bounded serving pause; do not promise zero downtime. Fast builds may pause
background workers temporarily to preserve the host memory reserve.

The ordinary updater requires matching live and candidate schema, unchanged
schema/model/configuration source and compatible queued tasks. It runs **no
migration or downgrade**. The document-distribution and Companies/traveller
transitions are separate, narrowly admitted additive lanes. Existing database, Redis, private object storage,
volumes, prior containers and images remain intact. It does not advance the
historical `/opt/GlobalConnectsDashboard` checkout: infrastructure still has bind
mounts there, and changing those files could affect serving containers. The
deployed revision is recorded in the running application and retained source.

Full mode has one narrow configuration exception for the frontend diagnostic
route allowlist: it must equal the frontend contract and the exact set of actual
page templates, with dynamic identifiers represented only by placeholders.
It does not permit arbitrary application configuration changes.

Before cutover it creates a PostgreSQL custom-format dump and verifies that
`pg_restore --list` can read it. This is an archive check, not a restore drill;
Full CI separately requires the populated PostgreSQL restore/upgrade job.
After activation, it checks local application readiness and public readiness
for the exact revision and verifies all previously retained resources remain.

Ordinary cutover failures stop the new app processes before restarting the
exact old container IDs. Recovery never rolls back business data. If a process
cannot drain, a builder is still running, or the schema changes unexpectedly,
the updater stops with retained evidence; it does not force-kill processes,
delete resources, retry automatically, or start overlapping writer sets.

For an interrupted job, inspect its private journal and container state first.
Use the latest complete private step receipt from the same attempt when an
operator resumes recovery:

```text
python3 -B <attempt>/source/scripts/release_retained_update.py --revision <SHA> --mode full --manifest <attempt>/artifacts/release-artifacts.json --recover-receipt <attempt>/<timestamp>-<phase>.private.json
```

For a Fast attempt use `--mode fast` and omit `--manifest`. A recovery receipt
must belong to that exact attempt, source, revision and mode. Do not invoke
old schema-specific direct-release scripts for a new release.

## Companies and traveller portal: exact additive transition

The `companies_traveller_reuse_v1` version 3 contract selects
`scripts/release_companies_retained_update.py`. It admits only the current
`0135_company_removal_history` baseline through the three hash-bound revisions
`0136_returning_drafts`, `0137_company_directory`, and
`0138_verified_portal_lookup`. Older baseline contracts are historical evidence,
not permission to skip their migrations. Once 0138 is installed, ordinary updates
retain the existing same-schema guards.

This is a separately reviewed additive rollout. An explicitly authorized direct
VPS run uses the operator build path (`mode: fast`) and records
`full_ci_qualified: false`; it is not Full CI qualification. The signed Full
entrypoint remains available. Ordinary Fast never admits arbitrary migrations,
persistent-model changes, task contracts or configuration changes.

The source contract binds migration hashes, order, preservation policy and exact
source/target revisions. Admission permits only the reviewed persistent files,
the Compose schema default, and two new zero-argument task modules/schedules:
`travellers.returning_drafts` and `companies.refresh_directory`, every five
seconds on the existing `passport_ocr` queue. Existing task signatures, schedules,
worker topology, resource limits, networks and mounts remain unchanged.

The migrations create eight empty draft/directory tables, add one nullable keyed
passport lookup column and its index, and extend two actor CHECK constraints with
the truthful `verified` label. They do not relabel old grants, change original
documents or submissions, merge identities, populate drafts, or backfill identity
data during DDL. Directory and lookup projections are populated later by bounded
application jobs; incomplete indexing remains visible in the UI.

Before production DDL, the exact candidate image must pass an isolated PostgreSQL 16
rehearsal. It restores a 700-person synthetic roster with existing identities,
three document versions, available/pending private asset references, queued work
and manager history. It proves every retained row, catalog item and ACL unchanged;
runtime grants on new tables; rollback after injected draft, directory and actor
constraint failures; interrupted forward resume; wrong-baseline and wrong-owner
rejection; and idempotent completion. Two existing contact concurrency tests also
run. This is targeted migration evidence, not a production load-capacity claim.

The rehearsal uses a disposable internal Docker network, synthetic credentials,
no published ports and bounded 512 MiB PostgreSQL/helper containers. Resource
admission includes all running container caps and retains 2 GiB for the host.
The existing background-quiescence scope pauses scheduler/workers during the
operator build/rehearsal and resumes them before normal cutover. Existing web
requests continue during that phase. All owned disposable resources must be
removed successfully before the rehearsal can qualify.

Before stopping ingress, cutover drains and stops the scheduler/workers. A stuck
warm shutdown therefore fails before the website is stopped. It then fences both
application generations and retains a custom-format source database backup, hash,
and private receipt, fully decoded using `pg_restore`. The image-bound migration
helper retains its one GiB memory/swap ceiling, one CPU, 256-process limit,
120-second SQL statement limit and five-second lock limit. A 30-minute helper
timeout does not authorize killing a helper that may still be running DDL.

An image-bound baseline helper hashes all original rows in bounded 100-row streams,
together with retained schema and ACL evidence. Only the reviewed additive catalog
differences are normalized. Every resume must match the original backup and
baseline; a partly migrated database cannot replace that baseline.

Every original container, image, volume, private file and backup remains retained.
After any new revision commits, never restart a 0135 writer. Interruption requires
forward recovery from the same attempt, source, immutable images, backup,
baseline and stopped helper. Reaching 0138 alone is insufficient: final validation
must succeed before application activation. A completed validation receipt permits
later application recovery after legitimate writes, without requiring the new
tables to remain empty. There is no automatic downgrade or blind retry.

All writer services must already have the same complete reuse configuration.
The rollout retains its existing lookup/encryption keys, version and disclosure
switch in the private custody receipt; missing or inconsistent configuration is
rejected. It never provisions replacement keys for existing encrypted history,
changes a disabled disclosure switch, or grants public access through migration.
