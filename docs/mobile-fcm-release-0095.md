# Direct FCM code release: schema 0094 to 0095

Use `scripts/release_mobile_fcm.py` for the initial direct FCM code release from `0094_whatsapp_receipt_inbox` to `0095_mobile_fcm_delivery`. It builds and activates the backend, frontend, seven workers and Beat. Provider configuration, Firebase credentials and the Android application rollout are separate steps; this helper does not infer or enable them.

## Before preparation

- Confirm the production checkout is the exact tested, pushed main commit supplied in the release handoff. The helper checks the full commit SHA, tracked-file cleanliness and the existing Compose project.
- Confirm production is at schema `0094_whatsapp_receipt_inbox`. A database already at `0095_mobile_fcm_delivery` is accepted only for a retry with this same commit's preserved pre-migration backup evidence.
- Review the current effective provider setting before activation. The helper preserves it; activating new code with an already enabled provider can resume due work. Keep push disabled during the code rollout if delivery has not yet been authorized and configured.
- Allow disk capacity for new images, recovery image tags, a fresh PostgreSQL archive and retained temporary artifacts. The helper verifies that the existing database container matches the prepared backend's database identity.

### Credential directory prerequisite

Production mounts only `/opt/global-connect-secrets/fcm` into the general worker at `/run/gc-fcm`, read-only. The explicit `!override` replaces the development `./backend:/app` bind completely. Backend, Beat and the other workers receive no credential mount. Confirm the production Docker Compose version accepts this override before activation.

Create or preserve the host directory before preparing the release; `create_host_path: false` intentionally prevents Compose from creating an unexpected path. It may be empty while push is disabled. When an authorized Firebase service-account file is available, its runtime path is `/run/gc-fcm/service-account.json`. Keep the host file outside Git and image build contexts, readable only by the account that needs it. Do not overwrite an existing credential without inspecting its ownership and intended project through a separate authorized setup step.

The current backend runtime image uses `appuser` with UID/GID `1001`. Verify the effective worker user when setting directory traversal and file-read permissions; a root-only directory/file will not be readable by this worker. The bind mount remains read-only inside the container.

Set the same absolute `MOBILE_PUSH_FCM_CREDENTIALS_FILE=/run/gc-fcm/service-account.json` in the shared runtime environment before selecting `MOBILE_PUSH_PROVIDER=fcm`; all application processes validate the setting, while only the general worker mounts and reads the file. The production worker override pins that path explicitly. Creating the empty directory and deploying this mount do not enable push or supply credentials.

## Prepare the exact revision

```bash
cd /opt/GlobalConnectsDashboard || exit 1
git pull --ff-only origin main &&
python3 scripts/release_mobile_fcm.py prepare --revision FULL_VERIFIED_COMMIT_SHA
```

Preparation records the currently running image IDs under recovery tags before building backend/shared worker/frontend images. It verifies the embedded revision and records exact image IDs and a configuration fingerprint. It does not migrate the database or activate services. Keep `tmp/mobile-fcm-release/` and the recovery image tags.

## Activate after pausing new work

Pause new uploads, deliberate message sends and other producers that could add work during activation. Check the relevant broker queues as well as worker state: the helper requires all seven workers to report no active, reserved or scheduled tasks, but that snapshot alone cannot guarantee an empty broker or prevent new tasks from being produced.

```bash
cd /opt/GlobalConnectsDashboard || exit 1
python3 scripts/release_mobile_fcm.py activate --revision FULL_VERIFIED_COMMIT_SHA --traffic-paused
```

The helper checks the prepared images and unchanged configuration, then saves a private custom-format PostgreSQL archive of schema 0094. It requires the application tables in the archive, full archive decoding with `pg_restore`, and matching database-container/host-copy checksums. This is archive verification; it is not a restore rehearsal.

Only after that backup is verified does it preserve the original `.env`, update the revision/schema pins, and request exactly `alembic upgrade 0095_mobile_fcm_delivery`. It checks the resulting schema and rechecks idle workers before activation. All seven workers and Beat activate first, followed by the backend and frontend. Image IDs, revision/schema settings, worker responses, backend readiness, Nginx configuration and public HTTP readiness must pass before the final marker:

```text
RELEASE VERIFIED: FULL_VERIFIED_COMMIT_SHA; schema 0095_mobile_fcm_delivery; backend, frontend, seven workers and beat.
```

Application containers must be replaced to load the new images. Database contents, uploaded files, named volumes and recovery images are preserved; the helper does not recreate database/storage services. It also retains temporary PostgreSQL archives, failed partial backup/private-write files and exited one-off schema/migration containers, including failures. There is no release-artifact cleanup, volume deletion, image pruning or automatic rollback. Atomic updates replace the release environment/manifest files while retaining the original `.env` backup.

## Retry rules

- If migration has not completed and the schema remains 0094, retrying activation captures another fresh verified backup and retains the earlier records.
- If migration completed to 0095 but activation failed or stopped, retry the **same commit** with its original release directory intact. The helper validates and reuses that commit's pre-migration 0094 archive; it cannot replace missing or corrupt evidence with a post-migration dump.
- A different commit on an existing 0095 database requires a separately reviewed same-schema release path. Do not repurpose this helper or substitute another commit's backup evidence.
- Configuration changes after preparation require preparation again. The first recorded recovery images and original `.env` backup remain preserved across retries.
- A failure after some application services have activated may leave a mixed deployment. Keep new work paused until the exact prepared revision is fully verified. There is no automatic downgrade or rollback to images that could reintroduce notification defects.

## Delivery verification is separate

The final release marker confirms code/schema/service activation. It does not prove that credentials are configured, an Android device has registered a direct FCM token, a notification was accepted by Firebase, or an alert appeared on a phone. After the separate credential and Android rollout steps, review pending audiences and use a dedicated test account/group to verify each stage. Keep service-account credentials and device tokens out of Git, chat and release logs.
