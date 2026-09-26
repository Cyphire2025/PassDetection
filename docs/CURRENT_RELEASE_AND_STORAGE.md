# Current release and storage cutover

This procedure upgrades the existing single-VPS Compose installation. It is not
a bootstrap command for an empty host. Use the exact reviewed, pushed main commit
from the installation's existing checkout and its protected `.env`. Local
qualification used synthetic data; the Hostinger KVM 4 VPS has not been deployed
or migrated by this work.

The source of truth is [release_manifest.json](../backend/app/core/config/release_manifest.json):
schema `0107_passport_ecr_checks`; workers `worker`, `email-worker`,
`email-ai-worker`, `extraction-worker`, `verification-worker`, `visa-ai-worker`,
`my-photos-worker`, `ecr-worker`; plus the `email-beat` scheduler. The current
manifest accepts an existing `0107` database only. Stop if the actual schema is
older; do not improvise a historical helper or skip a failed migration.

## Before the window

Assign a release owner and a recovery owner. Check protected off-host backup and
restore evidence, available host RAM/disk and certificate health using the
[readiness checklist](PRODUCTION_RELEASE_READINESS.md). Confirm this provider
contains exactly the application bucket and that no other process writes to it.
The helper fences the configured application writers, not arbitrary external
writers or manual S3 clients. Pause those separately. Retained histories need
space in both the untouched source and a separate destination.

On the Linux VPS, from the existing checkout, substitute the reviewed full SHA:

```bash
python3 scripts/release_current.py prepare --revision <full-40-character-commit-sha>
```

`prepare` verifies the checkout/project and current database/storage identities,
preserves configuration and running image IDs, creates missing independent role
secrets, renders the protected storage identity, and builds/verifies candidate
images without restarting live services. For legacy MinIO it chooses a fresh
named destination volume and evidence directory. Do not edit the generated
`OBJECT_STORAGE_*` values or identity bytes between preparation and activation.
The manifest, environment and identity fingerprints must match.

After preparation succeeds, pause new uploads and message sends at the ingress
or existing operational control, and wait for all workers to be idle. The flag
below confirms that you have paused traffic; it does not configure an ingress
maintenance page itself:

```bash
python3 scripts/release_current.py activate --revision <same-full-commit-sha> --traffic-paused
```

The helper selects all three Compose files in order: `docker-compose.yml`,
`docker-compose.prod.yml`, `docker-compose.storage-production.yml`, with profile
`maintenance`. It adds `docker-compose.apns.yml` only when APNs is enabled.
**Do not run plain Compose `up` to perform this upgrade**, with either two or
three files. That bypasses the copy, evidence and writer-fencing transaction.

## What activation does

1. Rechecks exact prepared images/configuration, schema, all eight worker replies
   and empty active/reserved/scheduled work. It retains a fresh PostgreSQL custom
   archive and verifies its full decode before role/storage changes.
2. Provisions separate bootstrap, migration and restricted runtime database
   identities without clearing tables or changing the existing database target.
3. Persists the storage writer checkpoint **before** stopping the backend,
   workers and beat. This is an expected outage. It starts only the isolated
   storage stage on the new volume and measures that volume's free bytes.
4. Requires free destination capacity of at least **1.25 × all retained source
   object bytes + the largest object + 2 GiB**. This is a copy preflight margin,
   not a growth or availability guarantee. It inventories/copies all versions
   and delete markers and verifies every copied body, metadata/tags, unchanged
   source and exact destination inventory under the migration lock.
5. Stops and verifies the staging process before the stable `minio` service
   opens that same verified volume. The S3 hostname/port and public URLs remain
   unchanged. It verifies the provider/volume/identity/proof, restores the exact
   recorded old writer containers, and tests/reloads Nginx before completing
   the storage checkpoint. It then performs normal candidate application
   activation, schema verification, worker readiness and public HTTPS checks.

Wait for `RELEASE VERIFIED` and inspect representative existing private files,
login, uploads, queue age and logs before reopening ingress. Retain the output
and protected evidence under `tmp/current-release/`. A green helper is not proof
of off-host recovery or human alert delivery.

## Interruption and recovery

Keep traffic paused. Rerun the **same command, revision and existing checkout**.
Pending `tmp/current-release/storage-writer-fence.json` is inspected before the
normal running-backend preflight, so a helper killed after stopping writers can
recover even when the backend is still stopped. The checkpoint records exact
container/image/project/working-directory identities, provider volumes and the
verified cutover proof; it does not store credentials. Recovery validates that
identity and tests/reloads Nginx before marking completion.

The one-off copy process also has a recorded name, image, scope and evidence
mount. Recovery verifies and stops that exact process before restoring writers;
an unknown replacement or a process that will not stop keeps writers fenced.
Killing the helper is not evidence that its Docker copy container has stopped.

Before provider handoff, an unchanged authoritative legacy source can safely
resume its original writers. After handoff starts, only the verified replacement
may resume writers. Missing, stopped, mismatched or ambiguous providers keep
writers fenced and report the checkpoint and required recovery context. Follow
that error with the recovery owner; do not manually start arbitrary containers,
edit the checkpoint, guess an empty destination, or force an old-provider restart.

A lost copy response can leave a valid destination version absent from the
journal. Retry deliberately stops on that ambiguity. If recovery confirms the
legacy source is still authoritative, run `prepare` again to allocate a new
isolated destination, then repeat activation. Both the source and partial target
remain retained. This is not automatic resumption of an uncertain object write.
If handoff is ambiguous, resolve the recorded provider/volume/proof first; a new
preparation is not a way to bypass the recovery gate.

Once new writes reach the maintained provider, the retained MinIO volume is a
historical checkpoint, **not a rollback target**. Keep the new data authoritative.
Review a compatible application-only rollback or restore/reconcile into an
isolated destination using the [DR runbook](PRODUCTION_RESILIENCE_AND_DR.md).
Never delete volumes, run `down -v`, blindly downgrade the database, purge
delivery queues, or replay uncertain provider sends.

The copy rejects source protections it cannot faithfully preserve: object lock,
default encryption, lifecycle, bucket policy, CORS or custom ACLs. Additional
buckets and objects above the reviewed single-object limit also stop it. Plan a
separate reviewed migration for these cases; do not remove protections or data
to satisfy the preflight. Provider version IDs and timestamps change; the private
journal preserves their mapping and original snapshot metadata while bytes,
the complete version inventory and current object/deletion visibility are
verified. See [local preservation evidence](remediation/storage-verification.md).
