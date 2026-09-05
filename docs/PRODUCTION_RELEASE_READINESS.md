# Production release, storage identity, and resource preflight

This is the operator procedure for audit findings **S07, O02, and O03** in
`outputs/dashboard-audit-2026-09-05.md`. It complements
[the disaster-recovery runbook](PRODUCTION_RESILIENCE_AND_DR.md). The policy and
offline checks in this repository do not provision an identity, deploy a release,
or establish that production backups, load handling, or recovery work.

## 1. Prepare the release record

Name the release owner and rollback owner. Record the candidate source revision,
reviewed image digests, Compose files, host/VM memory available to Docker, current
database revision, previous image digests, and the backup/restore evidence link.
Use a protected local release directory for environment files and rendered
Compose output; these can contain credentials. Keep them out of Git, CI artifacts,
screenshots, and support messages.

Production uses both `docker-compose.yml` and `docker-compose.prod.yml`. The base
file alone has development behavior. The override requires separate
`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` and restores the production API command,
private network bindings, readiness checks, and service resource ceilings.

Before upgrading, resolve the MinIO maintenance decision. The currently pinned
MinIO community image is a 2025 release. The official community repository is
marked archived as of 25 April 2026. A pinned digest gives reproducibility; it does
not establish ongoing security maintenance. Record a maintained distribution or
managed S3 service, compatibility rehearsal, patch owner, and update cadence.
No storage migration is performed by this work. See the
[upstream repository status](https://github.com/minio/minio).

## 2. Provision the application storage identity before application rollout

| Credential | Owner and purpose | Application access |
| --- | --- | --- |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | Storage administrator; bucket provisioning, policy management, recovery | Never use as `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | Dedicated application user with the policy below | Only the configured application bucket |
| Backup writer / restore administrator | Separate off-host account and recovery process | Never supplied to the API or workers |

For an existing installation, first use its currently authorized administrator
to provision and test the new application user. Keep the existing storage bucket
and volume intact. Set `MINIO_ROOT_*` to the actual administrator identity before
introducing the production override, and set `S3_*` to the new application user.
Do not rotate the administrator blindly while simultaneously changing application
credentials. Rotate it in a controlled follow-up after the application identity
has been verified and the recovery access path has been recorded.

For a new installation, start and initialize the storage service privately first,
then create the bucket and user before starting the API or workers. The
application's startup path can create a missing bucket when credentials allow it;
this production policy intentionally does not allow `s3:CreateBucket`. A missing
or unauthorized bucket is a provisioning error, not a reason to grant root access.

The [application policy template](../deploy/minio/app-policy.template.json) grants
only bucket location/listing and object read/write/delete within one explicit
bucket. The repository uses these for bucket readiness, bounded listing,
upload/download, metadata/range reads, signed GETs, same-bucket copies, and
retention-aware deletion. `CopyObject` uses source `GetObject` and destination
`PutObject`; `HeadBucket` uses `ListBucket`. See the
[S3 API permission mapping](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-with-s3-policy-actions.html).

The template grants no bucket administration, all-bucket listing, object-version
deletion, governance bypass, policy changes, or backup-bucket access. Keep backups
outside the application bucket: every key in that bucket must remain readable,
writable, and deletable by the application for existing workflows. Future
multipart/object-lock/KMS changes need an explicit policy review. Separate AWS
My Photos provider credentials also need their own reviewed policy; this MinIO
template does not grant Rekognition or other AWS provider permissions.

The following example runs in Bash on an authorized administration host from the
release checkout. `storage-admin` is an already configured, protected `mc` alias
to the intended private MinIO endpoint. Use a compatible, verified `mc` binary.
Inspect the target endpoint before making changes. Do not use `mc --json` when
creating users because user-creation JSON can contain the new secret.

```bash
umask 077
export APPLICATION_BUCKET='passdetection-passports' # Exact S3_BUCKET_NAME
export RELEASE_PREFLIGHT_DIR="$(mktemp -d)"
python - <<'PY'
import json, os, re
from pathlib import Path
bucket = os.environ["APPLICATION_BUCKET"]
if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or ".." in bucket:
    raise SystemExit("Use the existing application bucket's valid literal name")
template = Path("deploy/minio/app-policy.template.json").read_text()
policy = json.loads(template.replace("__APPLICATION_BUCKET__", bucket))
Path(os.environ["RELEASE_PREFLIGHT_DIR"], "app-policy.json").write_text(
    json.dumps(policy, indent=2) + "\n"
)
PY
mc mb --ignore-existing "storage-admin/$APPLICATION_BUCKET"
mc admin policy create storage-admin passdetection-app "$RELEASE_PREFLIGHT_DIR/app-policy.json"
mc admin user add storage-admin passdetection-app
# Enter the new independent secret at the hidden terminal prompt and store it securely.
mc admin policy attach storage-admin passdetection-app --user passdetection-app
mc admin user info storage-admin passdetection-app
```

The placeholder `__APPLICATION_BUCKET__` is replaced locally; it is not a MinIO
environment variable. The two resulting resource ARNs must name exactly the
intended bucket and its objects. The app user must have no additional broad
policies or group memberships. The
[MinIO multi-user guide](https://github.com/minio/minio/blob/master/docs/multi-user/README.md)
documents policy creation/attachment; the
[client user-creation implementation](https://github.com/minio/mc/blob/master/cmd/admin-user-add.go)
documents the interactive secret prompt and JSON output behavior.

Before changing production application credentials, verify the policy in an
isolated storage rehearsal using disposable fixtures. As the application user,
prove an application-bucket fixture can be uploaded, listed, read, copied,
metadata-checked, and deleted. Prove another administrator-created fixture bucket
cannot be listed/read/written/deleted, and administrator/policy APIs are denied.
Perform destructive negative tests only against disposable fixtures, never real
backups. Retain operation names, expected/actual results, and timestamps without
secrets or passenger data. Then set the application's `S3_*` credentials, verify
readiness and representative existing objects, and retain the last scoped user
until the rollback window closes. This repository has not run that production
identity rehearsal.

A local rehearsal on 5 September 2026 exercised this exact template against the
isolated Docker QA MinIO image, using a disposable user, policy, and two synthetic
fixture buckets. All 21 recorded assertions passed: permitted application-bucket
operations succeeded, six cross-bucket operations returned HTTP 403, and server,
policy, and user administration returned `AccessDenied`. The `mc admin info`
command returned exit code zero despite its explicit `AccessDenied` response;
check the structured response as well as the process status. The temporary user,
policy, both buckets, containers, and private environment file were removed;
independent administrator `HeadBucket` checks confirmed HTTP 404 for both buckets.
Redacted local evidence is in
`outputs/dashboard-qa/service-integration/minio-policy-results.json` and
`minio-policy-cleanup.json`. This verifies the template on the local pinned image;
production identity provisioning, credential cutover, representative-object
checks, and backup isolation remain release-operator steps.

## 3. Check the actual host resource envelope

Render the exact release configuration with real deployment overrides. Do this
on the release host from its checkout, where `.env` is the protected runtime file.
`--no-env-resolution` avoids expanding service env files; interpolated values can
still contain secrets. It is not a redaction option. The
[Compose configuration reference](https://docs.docker.com/reference/cli/docker/compose/config/)
describes the rendered JSON and output options.

```bash
umask 077
export RELEASE_PREFLIGHT_DIR="$(mktemp -d)"
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml \
  config --format json --no-env-resolution --output "$RELEASE_PREFLIGHT_DIR/compose.json"
python scripts/verify_deployment_resource_budget.py "$RELEASE_PREFLIGHT_DIR/compose.json" \
  --host-memory-gib 24 --reserve-gib 2
python -m unittest discover -s scripts -p test_verify_deployment_resource_budget.py
```

Replace `24` with memory actually available to Docker, not installed laptop RAM;
replace `2` with a measured allowance for the host OS, runtime, agents, and other
resident processes. Retain the summarized checker output and settings inventory,
not the secret-bearing rendered file. Stop the release if rendering or checking
returns nonzero. Never use `--no-interpolate` or `--no-normalize` for this check.

As measured from `.env.example` with both Compose files on 5 September 2026,
default container ceilings sum to **20.875 GiB**. A 2 GiB host reserve gives a
22.875 GiB arithmetic minimum. A 16 GiB Docker host fails this envelope; 24 GiB
passes the arithmetic with only 1.125 GiB beyond that reserve. This is not a
24 GiB production sizing guarantee. Re-render after any concurrency, replica,
service, or memory change. Larger available memory is useful only alongside CPU,
storage IOPS/space, database connections, and measured latency/queue performance.

The checker rejects absent/invalid ceilings, invalid host values, unbounded
replica configurations, and host memory overcommit. It counts explicit `scale`
and `deploy.replicas`, including profile services present in the model. Its
Celery check uses the maximum declared concurrency or autoscale count and a
conservative initial floor of 256 MiB per parent plus 128 MiB per child. That
floor is a configuration guard, not measured OCR/process capacity. API workers
selected by image CMD, shell wrapper commands, CLI `up --scale` overrides,
rolling-update overlap, non-Compose processes, CPU overcommit, database pools,
disk capacity, and task-specific peak RSS need separate validation. Represent
replica changes in the rendered configuration before using the result.

Keep extraction concurrency at the reviewed value until a representative load
run measures RSS and p95/p99 latency for mixed scanned PDFs, image-heavy documents,
native PDFs, malformed inputs, and simultaneous uploads. Include ClamAV signature
reload, OCR child processes, PostgreSQL maintenance, and worker retry/recovery.
Record queue age, rejection rate, container OOM events, disk latency, and database
connection saturation. Tune one bound at a time and repeat the workload.

Redis `maxmemory` controls dataset pressure; it is not a container RSS ceiling.
Persistence/replication buffers can sit outside that accounting, and copy-on-write
fork overhead must be measured during persistence activity. `noeviction` rejects
new writes at pressure, so alert on failed writes as well as memory. Preserve
the security, broker, realtime, and cache domain separation. Do not switch a
durable/security domain to cache eviction to hide pressure. See the
[Redis memory-accounting guidance](https://redis.io/docs/latest/develop/reference/eviction/).

## 4. Rehearse the forward migration and rollback decision

The current candidate's reviewed schema head is `0090_upload_configuration`,
which follows `0089_revoke_legacy_refresh` and descends from
`0088_merge_my_photos_hardening`. Preserve the merge topology
described in the DR runbook. Verify the exact checkout's migration head and
`EXPECTED_DATABASE_SCHEMA_REVISION` together before release. Record migration
duration and readiness results on a restored, isolated database before scheduling
the production window.

The `0090` migration adds nullable upload-link configuration and passport cover
storage keys. Existing links retain their collection defaults. Apply this
schema before starting application code that reads those columns, and use
`0090_upload_configuration` for the runtime readiness revision.

The `0089` migration revokes unknown/legacy refresh credentials. Current keyed
hash rows remain valid; affected historical sessions must sign in again. Its
downgrade intentionally does not revive revoked tokens. Reverting to code that
accepts legacy tokens is not an acceptable rollback. Keep a reviewed image that
understands the deployed schema and preserves the authentication fix; if none is
available, pause traffic and fix forward with the release owner.

For the controlled production release, capture a recoverable database/object
checkpoint and retain old image digests and protected configuration versions.
Quiesce incoming writes/schedulers and allow workers to finish or record their
in-flight work before a change that needs a consistent recovery boundary. Do not
purge broker queues, reset delivery statuses, or rerun ambiguous provider sends.
Apply the reviewed migration once, start the candidate, and inspect readiness,
error rate, login, private-object access, and queue age before reopening traffic.

If acceptance fails, contain new writes and worker dispatch first. Use the
pre-reviewed compatible application image/configuration rollback when the schema
allows it. If data recovery is required, follow the isolated restore/reconciliation
procedure in the DR runbook; do not issue a blind Alembic downgrade or overwrite
the only live volume. Preserve logs and delivery ledgers. Reconcile unknown send
outcomes with provider evidence before retrying. Record the decision, observed
data loss, elapsed recovery time, and who authorized reopening. Never use
`docker compose down -v` as a rollback step.

## 5. External evidence required before production readiness is claimed

| Gate | Required retained evidence | Current evidence boundary |
| --- | --- | --- |
| Separate storage identities | Effective user/group policy, app fixture checks, denied cross-bucket/admin checks, working private-object access, rotation/recovery owner | Template and configuration contract exist; deployed identity and policy are unverified |
| Supported storage lifecycle | Maintained provider/distribution, compatibility test, patch/update owner and cadence | Current community upstream archive requires a deployment decision |
| Resource capacity | Exact rendered envelope; real host/VM limits; representative load and restart/fork measurements; OOM/latency/queue graphs | Offline arithmetic and regression tests are local evidence only |
| Database recovery | Encrypted off-host base backups plus WAL/PITR, retention policy, restricted restore credentials, isolated restore at requested timestamps | Not established by named Docker volumes or logical CI fixtures |
| Object recovery | Off-host versions/inventory/checksums, encryption/key separation, app denied backup deletion, isolated object/DB-reference reconciliation | Not established by a local MinIO volume or this policy template |
| Durable/security Redis recovery | Broker/ledger reconciliation, security state fail-closed/reauth policy, tested persistence/failover, cache/realtime rebuild | Runtime configuration does not prove recovery under an outage |
| Monitoring and response | External HTTPS uptime/readiness probe, expiring-certificate alert, backup-age/failure alert, queue/DB/storage/OOM alerts, named recipient and tested delivery | Local health checks and metric exporter availability do not prove external notification |
| Audit durability | Restricted export to an independent retention boundary, integrity verification and documented retention/legal-hold access | Application audit records alone do not establish off-host immutable retention |
| Rollback and restore drill | Candidate/previous image digest inventory, reviewed schema compatibility, restored fixture checks, RPO/RTO measurements, owner sign-off | No production deployment, rollback, or off-host restore was performed in this work |

Store the runbook and recovery access instructions somewhere reachable during a
primary-host outage. Assign each row to a named owner and an evidence location;
an empty or expired evidence row remains an open operational gate.
