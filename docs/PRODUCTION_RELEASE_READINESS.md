# Production release readiness

This is the current operator gate for the existing PassDetection installation.
Use [Current release and storage cutover](CURRENT_RELEASE_AND_STORAGE.md) for the
short prepare/activate commands and interruption recovery. The historical
September 5 policy rehearsal remains useful evidence, but its two-file MinIO
rollout commands are superseded by the current three-file release path.

The current code and maintained storage provider were qualified locally with
synthetic data. **The Hostinger KVM 4 VPS has not been deployed or migrated in
this work.** Repository tests do not prove that its external backups, retention,
alerts, runtime grants or capacity satisfy production requirements.

An operator-run read-only SSH inventory on 26 September observed approximately
15 GiB RAM, no swap, 125 GiB free on a 193 GiB root filesystem, the existing
checkout at `/opt/GlobalConnectsDashboard`, and the expected application services
including legacy MinIO running. This establishes basic host inventory only.
The second bounded search found local application PostgreSQL archives, the newest
returned dated 21 September. Their contents were not inspected or restored; this
does not prove integrity, object/Redis coverage, off-host protection or PITR.
The running application revision remains the original audit baseline. Direct
schema/effective-grant/WAL checks were pending at that snapshot. A second
read-only inspection on 27 September confirmed live schema
`0107_passport_ecr_checks` and the runtime role's superuser, CREATEDB and
CREATEROLE privileges. The local restricted-role fix has therefore not reached
production. WAL/PITR qualification remains deferred. No configuration or data
was changed by either inspection.

The owner's signed-in Hostinger account then confirmed weekly automatic backups
stored off-server: available backups dated **23 September, 17:37 (64.22 GB)** and
**16 September, 15:34 (31.73 GB)** show **Malaysia**, with matching successful
creation records; this VPS is in **India — Mumbai 2**. The displayed timezone was
not established. This confirms backup existence, not an application-consistent
restore, deletion protection, PITR or measured RPO/RTO. No backup was restored,
created, deleted or rescheduled. The provider's **1h 54m estimate is not a measured
RTO**. See the [read-only inspection record](C:/Users/nipun/Desktop/PassDetection-Independent-Audit-2026-09-26/24-VPS-Read-Only-Inspection.md).

## Release contract and recorded identities

[release_manifest.json](../backend/app/core/config/release_manifest.json) declares
target schema `0113_document_follow_up`, reviewed previous schema
`0112_passport_cover_edits`, and all **eight** worker services/nodes:
`worker`/`general`, `email-worker`/`email`, `email-ai-worker`/`email-ai`,
`extraction-worker`/`extraction`, `verification-worker`/`verification`,
`visa-ai-worker`/`visa-ai`, `my-photos-worker`/`my-photos`, and `ecr-worker`/`ecr`.
`email-beat` is the scheduler, not a ninth worker. Settings, runtime checks,
Compose mirrors, CI and `scripts/release_current.py` use or validate this contract.
The current manifest accepts the reviewed `0112` baseline or current `0113`
head. Any other database revision needs its own reviewed upgrade rehearsal;
stop on an unknown/missing revision. Migration `0109` invalidates existing
dashboard sessions, requiring a fresh sign-in; it preserves business records,
passwords and MFA enrollment.

Record the release/recovery owners, full pushed main revision, exact running and
candidate image IDs, existing Compose project/checkout, schema, named volumes,
backup evidence and maintenance window. Keep `.env`, rendered configurations,
identity files and `tmp/current-release/` private and available after a restart.
These files can contain credentials or sensitive object keys. They do not belong
in Git, CI artifacts, screenshots or support messages.

The current helper selects `docker-compose.yml`, `docker-compose.prod.yml` and
`docker-compose.storage-production.yml`, with profile `maintenance`; APNs adds
its reviewed overlay only when enabled. The base file alone is development
configuration. The two-file base/production path retains legacy MinIO for
transitional compatibility and is **not the current deployment procedure**.
Starting the three-file override directly also bypasses the required copy and
writer fence. Use the release helper; see the dedicated procedure above.

## Database and storage authority

| Identity | Required boundary |
| --- | --- |
| PostgreSQL bootstrap owner | Existing database, maintenance/provisioning only; never passed to API or workers |
| PostgreSQL migration identity | Separate role for reviewed Alembic DDL; not runtime authority |
| PostgreSQL runtime identity | Explicit application privileges; no role escalation, schema DDL, audit mutation or ownership bypass |
| Existing MinIO administrator (`MINIO_ROOT_*`) | Source enumeration/reads for the migration; preserve the actual current credentials |
| Maintained-provider administrator (`OBJECT_STORAGE_ADMIN_*`) | Separate provisioning/recovery authority; never runtime S3 credentials |
| Application S3 identity (`S3_*`) | Existing application bucket only; ordinary object operations, no bucket/IAM administration or permanent version deletion |
| Off-host backup/restore identities | Independent account/retention boundary; not supplied to API or workers |

`prepare` adds missing independent credentials and captures the original private
configuration. It does not rotate the existing source administrator blindly.
`activate` verifies a fresh PostgreSQL archive, provisions role boundaries, and
copies source objects to a separate named destination. The source is read only
from the copy client's perspective. Unsupported bucket protections, multiple
source buckets, unrecorded destination objects, source changes, metadata/tag
changes, identity mismatch and inadequate disk capacity prevent activation.

The reviewed replacement is digest-pinned SeaweedFS 4.47. Its production shape
keeps master/volume/filer HTTP and gRPC ports on container loopback and exposes
only authenticated S3 to the application network, at the existing `minio:9000`
name. A protected read-only identity file binds runtime privileges; the cutover
proof binds the verified target volume/provider. No original MinIO volume is
mounted into the replacement. The historical [MinIO policy template](../deploy/minio/app-policy.template.json)
remains a legacy reference; it is not the maintained provider's identity format.
Use [storage_identity.py](../scripts/storage_identity.py) through the helper.

Local evidence includes actual application-adapter operations, denied anonymous,
cross-bucket, admin and permanent-version deletion, 1,001 paginated historical
versions, source preservation, tamper rejection and fault boundaries. It does
not establish deployed identities. See [storage verification](remediation/storage-verification.md)
and the [database qualification](../backend/scripts/qualify_database_roles.py).
Credential rotation remains a separate reviewed procedure after the cutover.

## Capacity, downtime and consistency gates

Pause ingress for new uploads and sends, and stop any independent/manual writers.
The `--traffic-paused` flag is an operator assertion, not an automatic ingress
barrier. Exact worker active/reserved/scheduled snapshots must be empty. The
helper journals and stops the backend, all eight workers and beat during object
inventory, copy, full read-back verification and provider handoff. **Expect
service downtime proportional to retained object history.** This is a single-VPS
maintenance operation, not near-zero-downtime deployment or high availability.

Destination free-space preflight requires at least 1.25 times all retained body
bytes, plus the largest body, plus 2 GiB. Preserve source space, backup archives
and evidence as well. Do not delete historical versions to fit the target.
Physical disk pressure elsewhere can invalidate earlier headroom; monitor it
through the window. Never run staging and stable storage processes concurrently
on their shared replacement volume.

After `prepare` has populated protected storage configuration, render the exact
model privately for host-resource and manifest checks (Linux Bash):

```bash
umask 077
release_preflight_dir="$(mktemp -d)" &&
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.storage-production.yml --profile maintenance \
  config --format json --no-env-resolution --output "$release_preflight_dir/compose.json" &&
python3 scripts/release_manifest.py --rendered-config "$release_preflight_dir/compose.json" &&
python3 scripts/verify_deployment_resource_budget.py "$release_preflight_dir/compose.json" \
  --host-memory-gib <actual-memory-available-to-docker> --reserve-gib <measured-host-reserve>
```

Use actual numeric measured values for the placeholders and include the APNs
file if enabled. `--no-env-resolution` is not redaction: interpolated fields can
still contain secrets. Keep the rendered file private. This checker counts all
rendered profile services conservatively; concurrent copy/staging and normal
application phases still need their own capacity review. Stop on a failed check.
The September 5 total of 20.875 GiB described an older two-file topology and must
not be used as the current envelope or proof that this VPS is adequately sized.

Arithmetic is only a preflight. Measure representative PDF/image/OCR workloads,
ClamAV reload, queue age, CPU, RSS/OOM, disk latency and PostgreSQL connections.
Include replica/surge overlap, worker child processes and Redis persistence
fork overhead. Redis `maxmemory` is a dataset limit, not total RSS; do not change
durable/security Redis to cache eviction to hide capacity failures. Mixed-load
latency/backlog limits and restart behavior remain required operating evidence.

## Recovery and reopening traffic

Follow the checkpoint recovery instructions in [the current procedure](CURRENT_RELEASE_AND_STORAGE.md).
Rerunning the same command checks pending writer recovery before requiring a
running backend. Changed writer identities, unknown providers and ambiguous
handoff fail closed. A failed Nginx test/reload leaves the checkpoint pending.
Keep the original source and partial target intact. A lost PUT response does not
permit deleting the uncertain target version or treating the copy as complete.

Once the target receives new writes, the old MinIO volume is historical and
must not be reactivated as an automatic rollback. The helper does not downgrade,
restore over live tables, delete volumes, purge queues or replay uncertain sends.
Choose a reviewed compatible application-only rollback or isolate/reconcile data
with the [DR runbook](PRODUCTION_RESILIENCE_AND_DR.md). Preserve authentication
fixes and delivery ledgers; legacy revoked refresh credentials must remain
revoked. Never use `docker compose down -v` as recovery.

Require the helper's final `RELEASE VERIFIED` result, actual schema, exact
application image IDs, all eight worker replies, backend readiness and public
HTTPS checks. Inspect existing private objects, a new upload, login and backlog
before reopening traffic. Record outage duration and any recovery decision.
The helper's public probe currently targets `https://tech.gctravels.com`; a
separate installation/domain requires reviewed configuration, not bypassing the
probe. Keep trusted certificates and their external expiry monitoring current.

## Operational evidence still required

| Gate | Required production evidence | Current boundary |
| --- | --- | --- |
| Runtime authority | Actual effective DB grants and provider identity, private-file reads, denied administrative operations, rotation owner | Code/local adversarial tests pass; live old runtime role is confirmed privileged and requires the guarded rollout |
| Maintained storage lifecycle | Qualified release on the intended host, patch owner/cadence, historical-object checks after cutover | Maintained provider and copy qualified locally; no live cutover claimed |
| Resource capacity | Exact host envelope, workload throughput/latency/backlog bounds, restart/fork/OOM measurements | Local arithmetic and synthetic journeys are not capacity proof |
| Database recovery | Encrypted off-host backup plus WAL/PITR to an operator-selected timestamp, independent retention and restricted restore credentials | Weekly off-server Hostinger backups confirmed; local current-schema restore and row digests pass. Provider-backup restore consistency, deletion protection and PITR remain unproved |
| Object recovery | Off-host versions/inventory/checksums, independent deletion protection and DB-reference reconciliation | Weekly off-server VPS backups exist; object coverage/consistency and independent protection require a restore drill. Local retained versions and restore pass |
| Redis-domain recovery | Durable-broker and delivery-ledger reconciliation, security reauthentication policy, persistence/failover drill | Runtime configuration and worker replay alone are insufficient |
| Monitoring/response | Off-host collection and retention, approved SLOs, named primary/backup responders, received/acknowledged fault alerts | Real local Prometheus firing/recovery is proved; external routing/receipts are unknown |
| Audit durability | Restricted independent retention, integrity verification, access/legal-hold policy | Local audit records and runtime mutation denial do not prove independent retention |
| Restore/rollback | Reviewed candidate/previous image inventory, schema compatibility, representative RPO/RTO and reopening approval | No production rollback, PITR or off-host restore performed |

Assign each row an owner and evidence location with an expiry/retest date. Keep
recovery access instructions outside the primary host. Validate the resulting
private evidence package with [verify_operational_evidence.py](../scripts/verify_operational_evidence.py);
passing the validator checks its declared fields, not the truth of external
claims. An unverified or expired row remains an open operational gate.
