# Current release and storage cutover

This procedure upgrades the existing single-VPS Compose installation. It is not
a bootstrap command for an empty host. Use the exact reviewed, pushed main commit
from the installation's existing checkout and its protected `.env`. Local
qualification used synthetic data; the Hostinger KVM 4 VPS has not been deployed
or migrated by this work.

The source of truth is [release_manifest.json](../backend/app/core/config/release_manifest.json):
target schema `0113_document_follow_up`, upgrading the reviewed
`0112_passport_cover_edits` baseline; workers `worker`, `email-worker`,
`email-ai-worker`, `extraction-worker`, `verification-worker`, `visa-ai-worker`,
`my-photos-worker`, `ecr-worker`; plus the `email-beat` scheduler. The current
manifest accepts the reviewed `0112` baseline or its current `0113` head.
Migration `0113` adds an initially false manual document follow-up flag to
passport submissions. It preserves existing records, images and approval status;
downgrade refuses to discard any active flags.
Stop if the actual schema is outside that contract; do not improvise a
historical helper or skip a failed migration. Migration `0109` requires existing
dashboard users to sign in again; it preserves users, passwords, MFA enrollment
and business records. The data constraints preflight existing rows and stop on
inconsistencies rather than silently deleting or changing them.

## Before the window

Assign a release owner and a recovery owner. Check available host RAM/disk and
certificate health using the [readiness checklist](PRODUCTION_RELEASE_READINESS.md).
Production off-host recovery and external alert delivery remain explicitly
deferred, unverified obligations; this release does not establish either. The
fresh local archive, full decode and data-preservation checks below are enforced
for this upgrade and do not substitute for off-host recovery. Confirm this provider
contains exactly the application bucket and that no other process writes to it.
The helper fences the configured application writers, not arbitrary external
writers or manual S3 clients. Pause those separately. Retained histories need
space in both the untouched source and a separate destination.

Production preparation and activation require the signed, qualified release
inventory. The host needs GitHub CLI attestation verification and read access to
the reviewed release/registry. From the exact pushed checkout, retrieve into a
new protected directory; preserve all prior inventories. Substitute the same
reviewed full SHA in both commands. Select the reviewed KVM4 resource profile
explicitly and export the target schema from the reviewed release contract:

```bash
umask 077
export PATH="/opt/globalconnect-release-tools/gh-2.92.0:$PATH"
export EXPECTED_DATABASE_SCHEMA_REVISION=0113_document_follow_up RELEASE_RESOURCE_PROFILE=kvm4
python3 scripts/release_artifacts.py retrieve --revision <full-40-character-commit-sha> --directory tmp/qualified-<full-40-character-commit-sha> &&
export RELEASE_ARTIFACT_MANIFEST="$PWD/tmp/qualified-<full-40-character-commit-sha>/release-artifacts.json" &&
python3 scripts/release_current.py prepare --revision <full-40-character-commit-sha>
```

The `0113_document_follow_up` value must equal the `schema_revision` in the exact
reviewed checkout's release manifest. An older `.env` schema value is deliberately
rejected unless the operator explicitly supplies this target process environment.
Docker Compose process variables take precedence over `.env`; exporting them
does not change a running container or migrate the database. `prepare` preserves
the old file's schema value. Guarded activation records the target in `.env`
after the fresh archive and prerequisite maintenance checks. The helper's
internal candidate normalization does not bypass the stale-configuration check.
The KVM4 profile itself must have completed qualification; a candidate metadata
status cannot activate. Retain both exports for preparation, activation and retry.

`prepare` verifies the checkout/project and current database/storage identities,
preserves configuration and running image IDs, creates missing independent role
secrets, renders the protected storage identity, and verifies/pulls the exact
CI-qualified image bytes without restarting live services. A local source build
without a signed inventory cannot pass production activation. For legacy MinIO it chooses a fresh
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

The helper retains the existing Compose project and selects these files in order:
`docker-compose.yml`, `docker-compose.prod.yml`,
`docker-compose.storage-production.yml`, and the explicitly selected
`docker-compose.kvm4.yml`, with profile `maintenance`. It then adds
`docker-compose.apns.yml` only when APNs is enabled and applies the generated
immutable application-image overlay for activation.
**Do not run plain Compose `up` to perform this upgrade**, with either two or
any other number of files. That bypasses the resource, backup, copy and writer
fences. Keep `RELEASE_ARTIFACT_MANIFEST`, `EXPECTED_DATABASE_SCHEMA_REVISION`
and `RELEASE_RESOURCE_PROFILE` set to the same reviewed values during
activation. If a new shell is used, restore those exports, including the absolute
manifest path; do not bypass
signature verification or rebuild different image bytes on the VPS.

## What activation does

1. Rechecks signed images, current advisory-policy expiry, prepared configuration,
   the actual physical-host budget and zero host swap, original project/schema,
   all eight worker replies and empty active/reserved/scheduled work.
2. Persists `resource-maintenance.json` **before** stopping the backend, frontend,
   beat and drained consumers. This outer fence remains active across persistent
   resource changes, storage handoff, migration and candidate application startup.
   This is an expected maintenance outage. A fresh PostgreSQL custom archive is
   retained and its full decode verified before data-service or role changes.
3. Applies the qualified persistent resource transition under live phase budgets.
   Redis processes are paused, checked, resized and unpaused with identical IDs
   and in-memory state. PostgreSQL replacement preserves its exact existing data
   volume, bootstrap settings and cluster identity and verifies row/sequence
   fingerprints. ClamAV retains its signature volume. It then provisions the
   separate bootstrap, migration and restricted runtime database identities.
4. Saves the inner storage checkpoint while the outer fence already holds all
   writers stopped. Starts only the isolated storage stage on the new volume and
   requires free destination capacity of at least **1.25 × all retained source
   object bytes + the largest object + 2 GiB**. This is a copy preflight margin,
   not a growth or availability guarantee. It inventories/copies all versions
   and delete markers and verifies every copied body, metadata/tags, unchanged
   source and exact destination inventory under the migration lock.
5. Stops and verifies the staging process before the stable `minio` service
   opens that same verified volume. The S3 hostname/port and public URLs remain
   unchanged. It verifies provider/volume/identity/proof and tests/reloads Nginx.
   Completing the inner checkpoint leaves old application writers stopped under
   the outer resource fence; it does not briefly restore the old deployment.
6. Applies the additive schema upgrade from the exact prepared image, then admits
   and starts the candidate workers, beat, API and frontend without dependency
   recreation. Verifies schema, running image/revision identities, worker replies,
   public HTTPS readiness, every actual memory/CPU/swap cap and total live budget.
   Only those completed checks mark the outer maintenance checkpoint complete.

Wait for `RELEASE VERIFIED` and inspect representative existing private files,
login, uploads, queue age and logs before reopening ingress. Retain the output
and protected evidence under `tmp/current-release/`. A green helper is not proof
of off-host recovery or human alert delivery.

## Interruption and recovery

Keep traffic paused. Rerun the **same command, revision and existing checkout**.
Pending `tmp/current-release/resource-maintenance.json` and the inner
`storage-writer-fence.json` are inspected before normal running-backend preflight,
so interruption after stopping writers can resume with those writers still
stopped. The protected outer checkpoint binds original/replacement container,
image, project, working-directory, mount, network and configuration identities.
It contains full protected container configuration and must be treated as secret
material, not attached to public logs. Storage evidence binds authoritative
provider volumes and verified copy proof. Recovery first re-fences any verified
partially activated candidate, then recovers only the recorded persistent
processes; it does not automatically restart old application images.

The one-off copy process also has a recorded name, image, scope and evidence
mount. Recovery verifies and stops that exact process before continuing maintenance;
an unknown replacement or a process that will not stop keeps writers fenced.
Killing the helper is not evidence that its Docker copy container has stopped.

Before provider handoff, recovery proves the unchanged legacy source remains
authoritative. After handoff starts, it requires the verified replacement.
Neither path bypasses the outer fence to restart old writers. Missing, stopped,
mismatched or ambiguous providers keep
writers fenced and report the checkpoint and required recovery context. Follow
that error with the recovery owner; do not manually start arbitrary containers,
edit the checkpoint, guess an empty destination, or force an old-provider restart.

A lost copy response can leave a valid destination version absent from the
journal. Retry deliberately stops on that ambiguity. Preserve the source, partial
destination, journal and checkpoints for a specifically reviewed reconciliation.
`prepare` refuses to replace an active outer maintenance checkpoint; allocating
another destination or editing a checkpoint is not an approved recovery shortcut.
If handoff is ambiguous, resolve the recorded provider/volume/proof first. This
is not automatic resumption of an uncertain object write.

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
