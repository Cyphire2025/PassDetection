# Choosing a deployment

Every push to `main` runs CI checks. Production deployment is a separate,
explicit choice; a background CI run does not later overwrite a fast release.

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
migration or downgrade**. The Companies/traveller Full transition below is a
separate, narrowly admitted additive lane. Existing database, Redis, private object storage,
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

## Companies and returning travellers: exact additive Full transition

The `companies_traveller_reuse_v1` manifest selects
`scripts/release_companies_retained_update.py` through the same qualified Full
entrypoint. Its only first-install path is `0129_travel_tracker` through the
four hash-bound migrations `0130_company_directory`, `0131_traveller_reuse`,
`0132_traveller_source_seek`, and `0133_traveller_document_impact`. Fast cannot
perform this transition. After the target is installed, ordinary compatible
Full/Fast updates retain all the existing same-schema guards; the additive
manifest does not authorize new model or configuration changes.

The signed image contract binds the exact migration sources, order and policy.
The source admission policy allows only the reviewed persistent files, the
schema-default change in Compose, and four new bounded traveller schedules.
Existing queued-task signatures, schedules, worker topology, mounts and resource
limits cannot change through this exception. CI must complete the populated
PostgreSQL restore/upgrade rehearsal, including the interrupted concurrent-index
case, before signed image promotion. Local unit tests alone do not qualify this
database rollout.

The updater stages stopped replacement containers, drains ingress and the
scheduler, proves existing workers idle, and fences both application generations.
It then retains a custom-format source database backup, its SHA-256 and private
receipt, and fully decodes the archive with `pg_restore`. The migration helper
uses the signed backend image and the exact inspected database network endpoint
and maintenance identity. Its 1 GiB memory/swap ceiling, one CPU and 256-process
limit are checked before a unique execution gate opens. The host keeps its
2 GiB resource reserve; a bounded 30-minute helper timeout does not kill a helper
that may still be performing database work. SQL statements have a 120-second
budget and lock acquisition a five-second budget. The migrations run separately,
so `CREATE INDEX CONCURRENTLY` is outside an enclosing transaction.

Before any DDL, a separate signed, fenced helper captures the original retained
rows/catalog/ACL preservation digest. Its private receipt binds that digest to
the original backup and release proof. Every migration or validation-only resume
must match this same digest before and after work; it cannot replace the baseline
with the current state of a partially migrated database.

Every original container, image, volume, backup and failed helper remains
retained. After any migration revision commits, **never restart the old 0129
application**. An interruption leaves a private forward-recovery receipt. Use
the same recovery command above with the same Full attempt and signed manifest;
the updater requires the original source backup and receipt, unchanged source,
images, database and fence bindings, and a stopped prior migration helper. It
resumes only the remaining revisions and starts target containers only after
the exact target schema is verified. Reaching the target Alembic revision without
a successful final validation receipt triggers a signed validation-only helper.
A prior complete validation receipt permits application recovery after legitimate
target application writes, without requiring those tables to be empty again.
A helper that is still running, a lost
source backup, changed bindings or an unknown schema stops recovery for operator
inspection. There is no automatic rollback, downgrade or blind retry.

The release preserves the existing application environment. Public traveller
disclosure remains disabled by default and requires separately configured
cryptographic keys and explicit company/group permission policies. Installing
the schema does not grant reuse authority or infer consent from historical rows.
