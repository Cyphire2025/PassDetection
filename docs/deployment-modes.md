# Choosing a deployment

Every push to `main` runs CI checks. Production deployment is a separate,
explicit choice; a background CI run does not later overwrite a fast release.

Use **Full** for security/dependency changes, broad changes, or a thoroughly
qualified release. In GitHub Actions open **CI/CD — PassDetection Platform**,
choose **Run workflow**, select `main` and `deployment_mode: full`. This runs
the complete checks, publishes signed image digests and deploys those exact
images after all required jobs pass. `deployment_mode: none` runs checks without
production promotion. The actual workflow display name can change; the file is
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

The updater requires live and candidate schema `0129_travel_tracker`, unchanged
schema/model/configuration source and compatible queued tasks. It runs **no
migration or downgrade**. Existing database, Redis, private object storage,
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
