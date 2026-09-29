# Direct VPS release checkpoint

The minimum direct release is live and verified. Retained journal receipt
`journal/0248-direct-release-live-verified.json` records application revision
`efea4e4ac199b65fbf4f3b76a1ed59c4c963bd7e` on schema
`0122_mcp_gc_push`, observed at `2026-09-29T20:52:25.162046+00:00`
(30 September 2026, 02:22:25 IST). All 12 active replacement application services are running,
with zero restarts and zero new OOM events during the verified startup window.
Public liveness, readiness and OAuth protected-resource metadata returned HTTP
200 from both the VPS and Windows. This is startup and readiness evidence, not
combined-load or real Codex qualification. All eight phase gates remain open.

A read-only follow-up at `2026-09-29T21:12:50.298841+00:00` recorded the same
12 application containers plus eight original infrastructure services running.
All ten configured application Docker health checks passed. Frontend and Nginx
have no Docker health check; their public MCP page, API liveness, full readiness
and OAuth resource metadata returned HTTP 200. All replacement cgroup OOM
counters and restart counts remained zero. This approximately 20-minute
post-cutover observation is retained locally in
`outputs/mcp-live-post-startup-20260929.json`; it is not a mixed-workload test.

The user authorized pushing the stable checkpoint to main and deploying on the
existing VPS before hosted CI, then continuing the accepted eight-phase plan.
This is a separate operator path; the signed hosted-CI updater is unchanged.
Every existing container, image, source file, business file, and database row is
retained. New builders, candidate containers, source archives, receipts and
backups are retained too. No cleanup, prune, forced stop, or automatic downgrade
is part of this path. The temporary SSH key keeps its original expiry.

The initial runtime enables MCP with only `mcp:read` and `mcp:export`, and exposes
only the `passport_excel` export family. Source admission allows at most 100
retained rows per source family and 1 MiB of cumulative database-measured text
values before full ORM reads. These are input limits, not a measured heap or
combined production-load capacity claim. The database control starts disabled;
an authenticated active superadmin must explicitly enable and authorize the
connection through the Administration flow. The live MCP Administration page is
visible to the signed-in superadmin. At this checkpoint the database control is
still disabled, pending the user's recent-MFA verification. Browser OAuth,
connector sign-in, a real Codex call and a verified live export have not yet
completed.

`scripts/mcp_direct_release.py` implements explicit prepare, build, stage,
activate, verify, and guarded source-schema recovery phases. Builds derive from
the exact existing backend/frontend image IDs and the existing pinned Node image
ID. They use finite memory/CPU/PID limits, retain hash-pinned dependency additions
in a separate import directory, and verify the backend OpenAPI contract. The
builder budget includes all running host containers and a 2 GiB host reserve.
Workers drain during builds and their original IDs resume afterward.

Activation uses a new set of stopped application containers with unique network
aliases and retained original runtime security/resource settings. It drains
ingress, scheduler and workers, verifies the writer fence, takes and validates a
fresh PostgreSQL custom archive, then applies the exact nine migrations from
`0113_document_follow_up` through `0122_mcp_gc_push` using the existing migration
owner. The full archive was validated and all nine migrations were verified on
the live database. The archive is decoded and hashed; it is not claimed as a
production restore rehearsal. Target-schema recovery is forward repair only.

The live application source remains the exact `efea4e4a` revision above. Operator
corrections are separately retained and journaled; the operator revision at cutover
revision is `e92f086e03e73593b8dc05919fed064f13b02a31`. These later operator changes
do not imply a rebuild or a change to the deployed application source.

The authoritative retained release root is
`/opt/GlobalConnectsDashboard/tmp/mcp-direct-efea4e4ac199b65fbf4f3b76a1ed59c4c963bd7e`.
The following paths are relative to that root. Private receipts contain exact
container/image bindings and must not be copied into public diagnostics.

| Runtime binding | Verified value |
| --- | --- |
| Application source | `source/` at the exact application revision above |
| Repaired runtime images | `images-runtimefix.json` |
| Active container IDs and bindings | `candidates-forward1.private.json` |
| Compose project label | `mcp-direct-efea4e4ac199-runtimefix` |
| Active container names | `mcp-direct-efea4e4ac199-runtimefix-fwd1-<service>` |
| Private network aliases | `mcp-direct-efea4e4ac199-runtimefix-<service>` |
| Nginx configuration | `runtime-nginx/mcp-direct-efea4e4ac199-runtimefix/nginx.conf`; original certificate mount retained |
| Successful verification receipt | `journal/0248-direct-release-live-verified.json` |

The 12 active services are `backend`, `frontend`, `nginx`, `email-beat`, `worker`,
`email-worker`, `email-ai-worker`, `extraction-worker`, `verification-worker`,
`visa-ai-worker`, `my-photos-worker` and `ecr-worker`. The original project's 12
application containers are stopped and retained. Its eight infrastructure
services remain in place. Existing source, images, containers, files and business
data remain retained, including failed candidates, helper containers and backups.

Backend-based replacements explicitly use `Entrypoint: []`, preserving the
original intended command instead of inheriting the image builder's Python
entrypoint. The earlier failed runtimefix worker is stopped with restart disabled
and retained. Runtime ownership was repaired in a new derivative image and
validated as UID 1001 before cutover; the previous image remains retained. The
email scheduler heartbeat arrived on its normal 60-second Beat schedule, after
which full readiness and Beat health passed.

Do not run normal `docker compose up` from the retained original
`/opt/GlobalConnectsDashboard` checkout at
`a18d236f15bd96ea326fe436cdcc28af60ec17b0`, and do not restart its old application
containers. That source and those clients expect schema `0113_document_follow_up`,
while the shared database is now at `0122_mcp_gc_push`; they are not the active
runtime mapping above. A normal Compose invocation could also recreate retained
containers or introduce competing schedulers/workers. Subsequent maintenance must
bind the exact active receipt and retain the existing resources. The guarded
source-schema recovery path applies only before migration and must not restart
old-schema clients now; any recovery requires a qualified forward repair.

Local evidence at this source checkpoint:

- Final broad backend run: 5,805 passed, 3 skipped, 285 service-integration tests
  deselected, and 162 subtests passed in 737.98 seconds, with exit code zero.
  Command: `python -m pytest -q -o addopts='' -m 'not service_integration'`.
  All three skips require Linux fork/path semantics unavailable on Windows.
  The frozen backend tree is identical to application revision `efea4e4a`;
  subsequent changes are operator helpers and documentation. The complete log
  and JUnit report are retained locally as
  `outputs/backend-regression-20260929T2107Z.log` and its `.xml` sibling. This
  supersedes the earlier broad run with eleven subsequently fixed failures;
  it does not replace the excluded real-service or production qualification.
- Frontend: 1,093 Vitest tests and 714 contract tests passed, with TypeScript and
  module budgets passing.
- Final passport export/source admission/envelope/architecture check: 24 passed;
  actual PostgreSQL export concurrency checks: 3 passed; scoped mypy/Ruff and 87
  backend module budgets passed.
- Connector: 95 tests passed. Rebuilt local version 0.2.0 wheel SHA-256:
  `9ddb16aa489e6cfd3e403f0778955c76f6c8bb050f81e3724368efec06518214`.
- Database helper: 9 focused tests plus a real PostgreSQL backup/decode/hash,
  five-second lock failure/transaction rollback, successful retry, retained row,
  disabled control and target retry proof passed.
- Post-cutover operator checks: 67 joined direct-helper tests passed, including
  15 build tests and 10 container tests. Future builds now commit explicit runtime
  configuration through the Docker API and inspect the returned image's command,
  cleared entrypoint, runtime user, work directory, revision, health check and
  stop signal before accepting it. Commit requests have a bounded 120-second
  timeout; ordinary control calls retain 15 seconds. An uncertain commit is not
  retried automatically. These new checks mock Docker and do not claim another
  live build or deployment.

The checksum-verified connector 0.2.0 wheel is also installed into a dedicated
Windows environment at `%LOCALAPPDATA%/GlobalConnects/mcp-connector/0.2.0`, backed
by CPython 3.11.15 independently of the managed checkout. Its pinned runtime
dependencies were installed with required hashes, the executable reports 0.2.0,
and access to its Windows Credential Manager entry succeeds. The entry is still
empty pending browser authorization; no Codex connection or live file transfer
is implied. The wheel SHA-256 is
`9ddb16aa489e6cfd3e403f0778955c76f6c8bb050f81e3724368efec06518214`.

The production build, bounded ownership repair, backup validation, migration and
public readiness have now succeeded. Browser authorization, real Codex use,
verified live export, the remaining allowed workflow coverage and combined
production-load qualification remain outstanding. This checkpoint does not
complete the full plan.
