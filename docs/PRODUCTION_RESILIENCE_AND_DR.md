# Production Resilience and Disaster-Recovery Evidence Runbook

## Status and purpose

This runbook defines the recovery contract for PassDetection's durable data,
media, queues, security state, and derived realtime state. It is an operating
contract and evidence checklist. It does **not** state that production high
availability (HA), point-in-time recovery (PITR), backup restoration, or
failover has already been proven.

For the candidate release procedure, bucket-scoped application storage identity,
host resource preflight, and schema-aware rollback decision, see
[Production release readiness](PRODUCTION_RELEASE_READINESS.md).

The CI migration rehearsal is deliberately narrower: it creates a synthetic
PostgreSQL database at revision `0085_platform_retention_controls`, populates
representative records, takes a logical backup, restores it to a fresh
database, upgrades the restored database through both sibling revisions and
the reviewed merge head, and verifies data, backfills, and constraints. The
reviewed graph remains:

```text
0085_platform_retention_controls
  +-- 0086_my_photos_foundation
  +-- 0087_enterprise_hardening
          \   /
      0088_merge_my_photos_hardening
```

Do not rebase, renumber, linearize, or deploy one sibling as the final release.
Production deploys must resolve to the single `0088` merge head or a later
reviewed descendant.

## Evidence boundary

| Evidence class | What it demonstrates | What it does not demonstrate |
| --- | --- | --- |
| Source review | Recovery logic, migration topology, safety guards, documented responsibilities | A backup exists, a restore succeeds, or infrastructure is available |
| CI PostgreSQL rehearsal | Synthetic `0085` logical dump/restore, forward migration to head, preserved representative rows, reviewed backfills and database constraints | Production volume, encrypted backup storage, WAL/PITR, replica promotion, regional failover, object restoration, Redis recovery, or a measured production RPO/RTO |
| Staging recovery drill | Recovery on production-like topology and data volume, application reconnect behavior, measured restore timing | A production provider/account/region can recover under incident conditions |
| Production operational proof | Provider backup evidence plus an independent restore, PITR, HA failover, object recovery, Redis-domain recovery, application validation, and retained timestamps/results | Future availability; evidence expires and drills must recur |

A green CI run must never be reported as “production DR is complete.” A backup
job reporting success must never be reported as “restore is proven.” Recovery
is proven only by restoring into an isolated target, validating it, recording
observed data loss and elapsed time, and retaining the evidence.

## Proposed recovery objectives

These are initial engineering objectives, not confirmed customer SLOs. The
product owner, data owner, infrastructure owner, security owner, and provider
contracts must approve them. An objective becomes a proven SLO only after
repeated drills meet it at representative scale.

| Recovery class | Included state | Proposed RPO | Proposed RTO | Required proof |
| --- | --- | ---: | ---: | --- |
| A: transactional safety | PostgreSQL agencies, identities, groups, passports, attendance, rooming, delivery ledgers, retention controls, audit metadata | 5 minutes | 30 minutes | PITR to multiple requested timestamps, counts/checksums, application reconnect, write/read validation |
| B: durable media | Passport and My Photos originals/variants in object storage plus PostgreSQL object references | 15 minutes | 4 hours for full service; priority objects within 60 minutes | Versioned-object restore, inventory/checksum reconciliation, access-control validation, signed-download smoke tests |
| C: durable asynchronous work | Celery broker state and work that cannot be reconstructed from PostgreSQL | 5 minutes | 60 minutes | Broker restore/failover plus idempotent replay and database-ledger reconciliation |
| D: security coordination | Rate-limit, challenge, revocation, lease, and fencing state held outside PostgreSQL | 0 minutes where loss weakens security; otherwise explicitly documented | 15 minutes | Domain-specific fail-closed test, expiry validation, forced reauthentication where safe recovery is impossible |
| E: derived state | Caches, realtime fan-out, presence, disposable query results | Not applicable; rebuild from durable sources | 15 minutes | Flush/rebuild test, no durable-data loss, reconnect and stale-data invalidation checks |

RPO is measured as the difference between the chosen recovery point and the
latest durable record known before the incident. RTO starts when the incident
commander declares recovery and ends only when the controlled production
reopen criteria pass. Provider “backup completed” timestamps are inputs, not
substitutes for those measurements.

## Ownership and prerequisites

Every production environment must name people, not only teams, for these roles:

- Incident commander: authorizes containment, recovery point, and reopen.
- PostgreSQL recovery owner: backups, WAL archive, restore, consistency checks.
- Object-storage recovery owner: versions, replication, inventory, restore.
- Redis/Celery recovery owner: classifies each Redis database/keyspace and
  reconciles durable work.
- Application validation owner: migrations, readiness, smoke journeys, data
  checks, and controlled traffic restoration.
- Security and privacy owner: key access, evidence handling, legal holds,
  retention, and breach assessment.
- Business/data owner: accepts the recovery point and verifies critical records.

Before an incident, maintain tested access to provider consoles and APIs,
break-glass credentials with time-bound approval, an inventory of regions and
accounts, current infrastructure-as-code, dependency/contact lists, and an
out-of-band communication channel. Store this runbook somewhere available when
the primary platform is unavailable.

## Backup and resilience design

### PostgreSQL

Production PostgreSQL requires all of the following controls:

1. Automated base backups plus continuous WAL archiving sufficient for the
   approved PITR window. A nightly logical dump may add portability but is not
   a substitute for PITR or HA.
2. TLS in transit. Backups and WAL encrypted at rest with a managed key. Backup
   ciphertext and its decryption key must not share the same deletion boundary.
3. A separate backup account/project with least-privilege write credentials,
   restricted restore credentials, retention enforcement, and immutable or
   deletion-protected copies. Routine application credentials must not delete
   backups.
4. Region or failure-domain separation appropriate to the approved disaster
   scenario. A replica in the same failed zone is not regional DR.
5. PostgreSQL checksums and provider integrity signals monitored. Alert on WAL
   archive lag, backup age, failed verification, replica lag, storage pressure,
   and recovery-window erosion.
6. A documented HA mode. Synchronous replication reduces acknowledged-write
   loss but can reduce availability; asynchronous replication can lose recent
   acknowledged writes. Record the chosen tradeoff against the approved RPO.
7. Forward-only application recovery. Take a recovery point before a schema
   release, rehearse the populated previous-release upgrade, and restore then
   migrate forward. Never rely on a destructive Alembic downgrade as DR.

The database append-only audit trigger and integrity chain are defense and
tamper-detection controls, not an external immutable/WORM audit archive. Export
audit evidence to an independently administered immutable sink, monitor export
lag, and include sink continuity and restore in production drills before
claiming immutable audit retention.

The backup catalog must record database/server major version, migration
revision, start/end time, encryption key identifier (never the key), backup and
WAL locations, retention expiry, size, checksum/provider integrity result, and
the identity of the automation or operator.

### Object storage

PostgreSQL is the control plane and object storage is the media plane. Recover
them as one consistency domain even though they use separate systems.

- Enable server-side encryption with managed keys, TLS, versioning, deletion
  protection, lifecycle policies, and access logging.
- Replicate or copy to an independent failure domain according to the approved
  RPO. Replication status and replication lag must be observable.
- Generate a scheduled inventory containing bucket, object key, version ID,
  size, checksum, encryption status, retention/legal-hold status, and last
  modified time. Protect the inventory as sensitive metadata.
- Preserve one physical media asset when the data model has multiple matches or
  references; recovery must not duplicate originals to recreate relationships.
- Test restoration of current, previous, deleted, quarantined, and legally held
  versions. Verify that restored access policies remain private and that signed
  downloads authorize the correct tenant and object rendition.
- Reconcile PostgreSQL references against the object inventory in both
  directions. Missing referenced objects are data loss. Unreferenced objects
  require quarantine and lifecycle review, not immediate deletion during a DR
  event.

### Redis and Celery

Do not assign one recovery policy to every Redis key. Maintain an explicit
keyspace/database inventory and classify each domain:

| Domain | Recovery behavior |
| --- | --- |
| Celery broker / durable work | Use persistence and replica/failover settings consistent with Class C. Prefer PostgreSQL outbox/ledger records and idempotency keys so jobs can be reconciled and safely replayed. Acknowledgement timing and visibility timeouts must prevent silent loss and uncontrolled duplication. |
| Identity challenges, revocation, fencing, destructive-action leases | Fail closed when Redis is unavailable if accepting traffic could weaken authorization. Restore only if freshness/expiry semantics remain trustworthy; otherwise invalidate outstanding challenges, fence sessions, and require reauthentication. |
| Rate limits and abuse counters | Fail closed for high-risk authentication, recovery, upload, and destructive endpoints. Record the explicit degraded behavior for lower-risk limits. Never silently reset a security boundary during recovery. |
| Realtime pub/sub and presence | Treat as disposable. Restart from PostgreSQL truth, force clients to reconnect, invalidate stale cursors, and republish only current authorized state. |
| Query/cache data | Discard and warm gradually from PostgreSQL. Apply concurrency limits to avoid a cache-miss stampede during reopen. |

Redis persistence files are encrypted in the same way as other backups. Validate
RDB/AOF loading, replication/failover, expiry behavior, and application
degradation independently for each domain. Restoring an old security keyspace
without checking expiry can be less safe than discarding it and fencing users.

### Configuration, secrets, and observability

- Keep infrastructure, network policy, storage policy, queue routing, scheduled
  jobs, dashboards, and alerts in reviewed infrastructure-as-code or an
  equivalent versioned source.
- Back up configuration without embedding plaintext secrets. Secrets are
  restored from the secret manager; test key availability and rotation without
  copying private keys into CI artifacts or operator notes.
- Preserve logs, metrics, traces, audit-chain verification output, and provider
  control-plane events in an independent observability boundary with approved
  retention.
- Export a dependency manifest and record the exact application image digest,
  migration revision, and configuration version used during recovery.

## Recovery procedure

### 1. Declare and contain

1. Open an incident record and appoint the incident commander and recovery
   owners. Record all timestamps in UTC.
2. Classify the failure domain: application, database primary, zone, region,
   object store, Redis/broker, credentials, corruption, deletion, or security
   compromise.
3. Stop or fence unsafe writes. Preserve evidence. Do not purge queues, rotate
   keys, delete objects, or promote replicas until the failure mode and blast
   radius are recorded.
4. Capture last-known-good database transaction/WAL position, object inventory
   timestamp, broker state, deployed image digest, Alembic revision, and
   provider event timeline.

### 2. Choose the recovery point

The incident commander, database owner, security owner, and business/data owner
approve one recovery point. For corruption or malicious deletion, choose a
point before the first bad write, not merely the newest available point. Record
the expected data-loss window and compare it to the RPO before restoration.

### 3. Restore into isolation

1. Restore PostgreSQL into a new isolated target or promote a verified replica;
   do not overwrite the only surviving copy.
2. Confirm server/version compatibility, database checksums, expected migration
   revision, critical table counts, tenant samples, attendance uniqueness,
   identity fencing, retention/legal-hold state, delivery ledgers, and audit
   continuity.
3. If restoring a previous release, run the populated upgrade path to the exact
   reviewed head. Run `alembic current`, `alembic check`, and the migration
   topology verifier. Do not independently deploy `0086` or `0087` as the final
   head.
4. Restore or expose the selected object versions. Reconcile object inventory
   with database references and validate encryption/access policies.
5. Restore durable Redis/Celery state only under its domain policy. Reconcile
   database outbox/ledger rows with queued and completed jobs. Replay only with
   idempotency protections. Discard disposable caches and realtime state.

### 4. Validate the application

Against the isolated recovery environment, verify at minimum:

- `/live` and dependency-aware `/ready` with bounded timeouts;
- admin, agency, coordinator, and passenger authentication/authorization;
- representative passport metadata and private object download;
- attendance session roster, existing scans, offline idempotent replay, and
  closeout counts without loss or duplication;
- rooming, group access, WhatsApp/delivery ledger, audit querying and audit-chain
  verification;
- My Photos gallery/media references without rescanning or duplicating stored
  originals;
- Celery execution, retry, dead-letter/error visibility, and duplicate
  suppression;
- realtime reconnection, tenant authorization, cache invalidation, and a fresh
  snapshot after reconnect;
- monitoring, alerts, audit emission, backup jobs, and key access in the target.

Use automated checks plus named human validation of critical records. A 200
response alone does not prove data correctness.

### 5. Controlled reopen

1. Record observed RPO and RTO and obtain the incident commander's go decision.
2. Restore traffic in stages: internal validation, read-only or low-risk traffic,
   a small tenant cohort, then general traffic. Apply queue and cache warming
   limits.
3. Watch database error/latency/locks, replica and WAL lag, object errors,
   Redis memory/evictions, queue age/depth/retries, authorization failures,
   attendance conflicts, and realtime disconnects.
4. Keep the failed environment isolated until the evidence and rollback window
   are approved. Do not reintroduce it as a replica without rebuilding and
   validating it.

## Failover-specific requirements

An HA failover drill must measure detection time, decision time, promotion time,
DNS/proxy convergence, connection-pool recovery, stale-primary fencing,
application retry behavior, job duplication/loss, and final data divergence.
Test abrupt primary loss as well as a controlled switchover. A provider console
showing a promoted replica is insufficient; the application and data checks
above must pass.

A regional drill must also prove that dependencies, object replicas, secrets,
keys, Redis/Celery, network policy, DNS, observability, and operator access are
available in the recovery region. A database-only regional restore is not a
working PassDetection recovery.

## Required evidence artifact

Every rehearsal or incident retains a tamper-evident evidence package with:

- unique drill/incident ID, environment, scenario, scope, owners, approvals;
- UTC start/end times and an event timeline;
- source and target regions/accounts, without credentials;
- application image digest, configuration version, PostgreSQL version, and
  Alembic revision before and after;
- selected recovery point, latest known durable write, observed data-loss
  window (RPO), and observed service-restoration time (RTO);
- backup identifiers, encryption key identifiers, sizes, checksums/integrity
  results, WAL/object inventory ranges, and retention expiry;
- restore/failover command or automation version and sanitized output;
- before/after counts, checksums/samples, referential reconciliation, queue
  reconciliation, audit verification, and application journey results;
- failures, manual interventions, exceptions, unresolved gaps, corrective owner
  and due date;
- final go/no-go decision and business/data-owner sign-off.

CI retains only its JSON manifest; the temporary synthetic dump and databases
are destroyed. Production evidence must be encrypted, access-controlled, and
retained under the incident/audit policy. Never place production data, backup
contents, secrets, private keys, recovery tokens, or plaintext PII in CI
artifacts or tickets.

## Cadence and acceptance gates

Minimum starting cadence, subject to approved risk and regulatory requirements:

- Continuously monitor backup/WAL/replication age and failures.
- Daily automated backup integrity/catalog checks.
- Monthly targeted restore of selected PostgreSQL records and object versions.
- Quarterly full isolated PostgreSQL PITR plus object/queue reconciliation at
  representative scale.
- Semiannual HA failover and application reconnect drill.
- Annual regional recovery exercise, and after material architecture/provider
  changes.
- Run the CI populated `0085` restore-upgrade rehearsal on every change that can
  affect migrations or the release gate.

A drill passes only when approved data checks succeed, no unexplained loss or
duplication remains, security controls retain their intended failure behavior,
observed RPO/RTO meet the approved objectives, evidence is retained, and every
material exception has an owner and deadline. Otherwise it is a failed drill
that produced useful evidence—not a successful recovery claim.
