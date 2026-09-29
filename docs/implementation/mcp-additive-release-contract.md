# Proposed additive MCP upgrade contract

Status: signed artifact metadata and narrow direct-release components implemented.
The database helper is locally qualified with an actual PostgreSQL archive and
upgrade/retry test. Container cutover has mocked ordering/failure checks; live
execution and the full release procedure remain unqualified.
The existing same-schema release guard remains in force. Existing production
files/data/services remain unchanged. One new isolated retained helper lock was
created for the separate pure Linux export-admission proof, not deployment.

The unpublished MCP candidate currently spans the ordered additive chain
`0113_document_follow_up -> 0114_mcp_connections -> 0115_mcp_workflows ->
0116_mcp_communications -> 0117_mcp_dispatch_origin -> 0118_mcp_pdf_ingestion ->
0119_mcp_contact_imports -> 0120_mcp_whatsapp_media ->
0121_whatsapp_send_intents -> 0122_mcp_gc_push`. Exact migration identifiers
and hashes must be checked against the final candidate before qualification.
The release manifest's `previous_schema_revision` denotes the source release
schema (`0113_document_follow_up`), not the immediately preceding Alembic parent.
Authenticated read-only observation on 2026-09-29 confirms production schema
`0113_document_follow_up` at revision `a18d236f15bd96ea326fe436cdcc28af60ec17b0`.
That source observation does not qualify the unpublished target or its upgrade.

The candidate now declares `deployment_kind=mcp_additive_v1`.
Its signed contract also binds the user's no-deletion instruction: retain
existing containers, source/business files, backup and helper artifacts; cleanup
is prohibited. This is stronger than retaining only persistent volumes. Existing
`compose up` activation can remove replaced application containers and cannot be
reused for this candidate without a separately qualified retention path. No
ordinary cleanup, `--rm`, prune, downgrade or implicit container recreation is
admitted by this contract. The new executor remains an outstanding gate.
`scripts/release_mcp_contract.py` binds the ordered migration identities, exact
source hashes, source/target schemas, initially disabled MCP and read/export
capability policy. Artifact export, promotion and verification validate that
contract. The existing same-schema updater explicitly refuses an additive
artifact even when the target schema is already present. Root initially reported34 passing release contract tests; the newer
connector inventory/manifest lane reports41 passing and1 platform skip. Signed
packaging now includes the hash-bound connector wheel, lock and readme. This
source addition is not proof of a CI run or created release signature. This metadata is not deployment permission or a migration orchestrator;
the protected dispatcher remains unchanged.

## Existing mechanisms and limits

`scripts/release_code_update.py` binds live persistent service identities and the
current schema, refuses configuration/persistence/task-contract changes, verifies
signed images and a backup, drains consumers, promotes a candidate web pair, and
supports same-schema recovery. Keep those checks unchanged for its existing path.

`scripts/release_current.py` supports migration, but its `before_migration()` also
configures persistent resources, provisions identities and invokes the storage
activation workflow. It is not a narrow MCP-only upgrade path. Calling it against
an already-migrated deployment requires qualification of that complete behavior;
do not substitute it blindly for the code-update helper.

`scripts/release_ci_dispatch.py` is the forced SSH command, checks the exact
current-main revision and successful named CI gates, and dispatches the
same-schema updater. Its installed protected copy and dispatch contract must be
updated through the existing owner-controlled release process before it can admit
a new migration-aware release kind. Do not turn it into a generic command runner.

## Narrow new release mode

Add a separately named, tested additive-schema release implementation and an
explicit reviewed release kind in the signed artifact contract. Dispatch on that
verified kind; a user-supplied environment flag must not bypass schema checks.
Reuse existing image, signature, backup, binding, resource and audit helpers.
Do not weaken `CodeUpdate.compatibility()` or accept arbitrary schema pairs.

Its prepared receipt should bind all of the following before stopping writers:

- Exact source/main revision, signed candidate and retained previous image IDs.
- Live schema and reviewed target schema, ordered migration IDs and source hashes.
- Existing Compose project, persistent service/container identities, named volumes,
  storage identity, relevant configuration fingerprints and qualified Nginx diff.
- Distinct runtime and migration identities, current effective grants, verified
  backup/archive checksum, and the rehearsed recovery choice.
- Measured maintenance and activation memory/connection envelopes, queue drain
  evidence and application revision identity.
- MCP deployment enabled flag and database emergency state, both disabled for
  initial activation. Capability enablement occurs only after its own gate.

The proposed source release is `0113_document_follow_up` and the current
candidate target is `0122_mcp_gc_push`, through every reviewed intermediate
revision in order. The narrow database helper accepts only the exact source or
final target with the original backup still verified; intermediate chain states
stop for reviewed forward repair. It must never skip
unknown migration state or silently substitute a new source release. Any other
starting schema needs a separately reviewed chain. This restriction must use the
actual database version, not just an environment variable.

Use the qualified maintenance writer fence for every application writer and
scheduler, preserving broker messages and accepted work. Capture and decode the
backup before mutation. Run the migration from the pinned candidate image using
the existing migration identity; admit the migration helper within the measured
phase envelope. Do not recreate PostgreSQL, Redis, object storage or unrelated
containers. No dump restore, downgrade, queue purge or storage copy belongs to
the ordinary upgrade path.

After upgrade, verify the target version, new schema objects, indexes and check
constraints, preserved business counts/checksums, append-only audit protection,
and runtime grants. `provision_database_roles.py` configures default privileges
for migration-owned tables. Read-only production catalog evidence at19:02:45UTC
on2026-09-29 verifies current separate identities, migration ownership and default
new-table/new-sequence runtime grants. A disposable PostgreSQL proof also migrated
0113-to0122 under the migration identity without subsequent GRANT and verified
restricted runtime access. This supports using existing configured identities;
actual candidate-head grants still require verification after migration.
The runtime must not gain DDL, role administration, audit mutation, or additional
storage authority. Start admitted candidate services using the expected target
schema and exact revision; verify health, the existing application workflows and
disabled MCP boundary before routing public traffic. Drain old connections under
the existing resource envelope. Retain the receipt for interrupted resumption.

## Recovery must preserve the additive schema

The new migration explicitly refuses downgrade once a grant exists. Recovery
must retain MCP history, tokens, audits and business data. An earlier image is
not automatically a safe recovery target merely because the schema additions
are additive: `runtime_readiness.py` checks an exact configured schema revision,
and existing helpers bind expected schema into the launch configuration.

The current signed contract selects forward repair while preserving the target
schema. That recovery execution still needs qualification. An alternative prior-
behavior recovery build would require a separately reviewed contract:

1. A tested recovery build of the previous application behavior that explicitly
   accepts the new additive schema and keeps MCP disabled; or
2. Forward repair from the retained target schema and candidate artifacts while
   the writer fence and maintenance state remain active.

Do not silently override the previous image's schema expectation to make its
readiness probe pass. A compatibility receipt must prove old application reads,
writes, workers and queued payloads on the migrated populated database before
allowing that recovery image. Preserve the previous images regardless, but do not
claim automatic rollback when it has not been tested.

## Required implementation and evidence touchpoints

| Area | Existing contract / required work |
| --- | --- |
| Schema defaults | Manifest, settings import, `.env.example`, Compose defaults and migration topology must agree on the final reviewed head. |
| Migration rehearsal | Extend `backend/scripts/rehearse_postgresql_upgrade.py` with a focused populated 0113-to-target case in addition to the existing 0085-to-head lane. Verify all old records and new constraints; test lock timeout and interrupted retry. |
| HTTP/worker authority | Real PostgreSQL separate-session code/refresh/revoke races; revocation before queued dispatch; multi-process access and emergency disable. |
| Release orchestration | Dedicated operator unit scenarios for each checkpoint/failure; live binding drift, superseded revision, invalid signatures, malformed receipt, missing backup, wrong schema, grant failure and memory/pool overrun must stop safely. |
| Routing | Exact `/mcp`, OAuth authorization/token and authorization/protected-resource discovery paths reach the intended backend with appropriate request limits, streaming timeouts and TLS/host identity. Website/API routing stays covered. |
| Configuration | Public HTTPS issuer/resource/front-end origins and explicit approved client redirects must match the deployed hostname. Runtime credentials are not published in browser bundles or generated setup instructions. |
| Full qualification | Exact candidate images, populated PostgreSQL, existing private storage/antivirus/Redis/worker infrastructure, real Codex connector and combined website/MCP workload. |
| Promotion | Signed inventory now records and validates the release kind/ordered chain/source hashes. Protected CI and the installed dispatcher still need a qualified path that admits that exact kind. Existing approval, data-retention and no-prune contracts remain intact. |
| Controlled activation | Reads/exports only after their acceptance evidence, then qualified creation/uploads and communications; emergency disable and download/queued-action fencing verified throughout. |

Until these touchpoints have passing evidence, updating the manifest or adding a
migration is source preparation only. It does not authorize running the current
same-schema dispatcher against the new release or establish production readiness.

## Authorized direct-release component checkpoint, 2026-09-30

The user separately authorized a minimum stable direct deployment before CI.
`scripts/release_mcp_database.py` supplies an exclusive private custom-format
backup, full `pg_restore` archive decode, SHA-256 receipt and exact image-bound
migration request. `backend/scripts/apply_mcp_additive_upgrade.py` verifies all
nine source hashes and identities before database access, uses the existing
migration owner, enforces five-second lock/120-second statement limits, and
requires the final disabled MCP control. It does not provision roles or launch
containers. The caller supplies the fresh writer/drain/database binding fence.

Nine unit checks and one actual PostgreSQL16.15 test pass. The latter retains a
unique local database/role/archive/receipt, migrates0001-to0113, captures and
decodes its real backup, rejects an altered source hash, forces a lock-timeout
rollback to0113, retries to0122, preserves the fixture business row, verifies
disabled MCP and retries at target using the original unchanged backup. Evidence
is retained under `outputs/mcp-direct-database-21c3fd023669/`. Full archive decode
does not claim a restore rehearsal.

The direct container modules have27 focused mocked checks covering retained
clones, budgets, ordered ingress/scheduler/worker drain, migration failure,
source-only recovery, public revision/discovery checks and cgroup evidence.
Preparation captures original cgroup counts; continuously running services are
compared across builds, stage and fences. New helpers/candidates must start with
zero OOM events and retain their identity/start/restart/counters through checks.
Original historical Nginx151 OOM/3 kill counts remain evidence. Before stopping
an original process its counters are checked again; after cgroup teardown the
retained exit/OOM/restart state is available, not a surviving cgroup counter.
Live execution remains the release owner's qualification step.

`recover-original` requires exact source0113, no running candidate/helper or
unexpected container, unchanged infrastructure and clean retained originals;
every start is capacity checked. `resume-workers` has the same source-release
fence. Neither path starts old-schema clients after the target migration, removes
resources or performs a downgrade. The protected hosted-CI dispatcher is unchanged.
