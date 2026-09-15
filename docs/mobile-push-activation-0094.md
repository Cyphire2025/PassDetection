# GC App push notification activation after schema 0094

## Observed production state on 15 September 2026

The supplied read-only diagnostic reports backend revision `be04cb836e108176746971f15425cb96bc52ca1e` and schema `0094_whatsapp_receipt_inbox`. The API runtime has `MOBILE_PUSH_PROVIDER=disabled`, two stored active Android/production Expo registrations, and no device-delivery attempts for the listed announcements. This confirms a disabled provider in the backend runtime; worker configuration must also be checked.

One published announcement has two queued recipients. An older revoked emergency announcement also has a queued recipient. A disabled provider preserves queued work, so enabling it can process existing due work, including notification types other than announcements.

The notification guard rechecks an announcement's current source before attempting delivery. Withdrawn, retired, missing or incorrectly scoped sources cannot be sent. A source being edited concurrently is deferred. Confirmed/provider-pending delivery evidence is preserved.

Receipt reconciliation also claims the current notification before its device-delivery rows. This keeps cancellation and receipt processing in a consistent lock order. A late provider receipt can record device delivery without changing a cancelled announcement back to sent or queued.

## 1. Release the backend guard while push remains disabled

Use the exact pushed revision from the handoff:

```bash
cd /opt/GlobalConnectsDashboard || exit 1
git pull --ff-only origin main &&
python3 scripts/release_notification_guard.py prepare --revision FULL_VERIFIED_COMMIT_SHA
```

After `PREPARED`, pause new uploads and deliberate message sends:

```bash
cd /opt/GlobalConnectsDashboard || exit 1
python3 scripts/release_notification_guard.py activate --revision FULL_VERIFIED_COMMIT_SHA --traffic-paused
```

This helper requires schema 0094, verifies a fresh backup, builds backend/shared worker images, activates seven workers and Beat before the backend, and checks service health. It does not rebuild or restart the frontend or enable push. Preserve `tmp/notification-guard-release/` and its recovery images. The expected marker is:

```text
RELEASE VERIFIED: FULL_VERIFIED_COMMIT_SHA; schema 0094_whatsapp_receipt_inbox; backend, seven workers and beat; frontend unchanged.
```

This release also retains PostgreSQL temporary backup archives, any failed partial backup or private-write files, and exited one-off schema-check/no-op migration containers. It performs no artifact cleanup or pruning. Temporary files can contain private data and keep their restricted permissions; retain them with the verified backups. The original migration helpers keep their existing cleanup behavior.

Activating new code still requires Compose to replace the backend, seven worker and Beat application containers. Their old images remain under recovery tags. The helper preserves database contents, uploaded files and named volumes, and does not recreate the database or storage services. It updates the release environment/manifest files atomically and retains the original `.env` backup; this is not a promise to keep every old application container or every prior version of a manifest.

## 2. Compare the effective runtime settings

This prints only non-secret settings and whether a token is present:

```bash
cd /opt/GlobalConnectsDashboard || exit 1
for service in backend worker email-beat; do
  docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T "$service" python -c 'import json,os,sys; from app.core.config.settings import get_settings; s=get_settings().mobile; print(json.dumps({"service":sys.argv[1],"revision":os.getenv("APP_REVISION"),"mobile_enabled":s.enabled,"push_provider":s.push_provider,"push_access_token_present":bool(s.push_access_token)}))' "$service" || break
done
```

The general `worker` consumes the `passport_ocr` queue used for dispatch and receipt collection. `email-beat` schedules the tasks. Editing `.env` alone does not change a running container's environment; controlled recreation is required after a verified configuration change.

Run `python scripts/diagnose_mobile_notifications.py` in the backend container again after release. The queue inventory includes all notification types and distinguishes due, future and expired rows. It describes queue state before recipient/source/device authorization; a due count is not a prediction of successful delivery.

## 3. Verify the correct Expo project

Public identifiers observed in local production-package Android v1.0.3 artifacts:

| Setting | Value |
|---|---|
| Expo project | `ee38a107-f450-48b6-ac4d-43bce25494ae` |
| Expo slug | `group-companion` |
| Android package | `com.globalconnects.groupcompanion` |
| Firebase project | `group-companion-c2c30` |
| Firebase sender/project number | `429195724409` |

Local artifact configuration does not independently prove which binary every production device has installed. The local Firebase client configuration is present, but it is not evidence that Expo holds the FCM V1 server credential.

Sign in to the Expo account used for this project. Inspect its Android credentials for an assigned FCM V1 service account matching the Firebase project above. Follow [Expo's FCM V1 credential guide](https://docs.expo.dev/push-notifications/fcm-credentials/) if setup is missing.

Also inspect whether enhanced push security is enabled. `MOBILE_PUSH_ACCESS_TOKEN` is an Expo access token and is required when that protection is enabled. It must never contain Firebase service-account JSON or a Firebase private key. A missing token by itself is inconclusive when enhanced security is off. See [Expo's additional push security documentation](https://docs.expo.dev/push-notifications/sending-notifications/#additional-security).

## 4. Enable and test after configuration and audience review

Before changing the provider from `disabled` to `expo`, review pending due notifications and ensure existing published content is intended for those recipients. Unpublish obsolete test announcements using the normal dashboard. Do not clear the queue indiscriminately.

Use a dedicated test group/account to verify published content, device registration, dispatch, provider tickets, provider receipts and visible phone alerts separately. The configured initial receipt delay is 900 seconds; a provider ticket can therefore remain awaiting receipt during that interval. A successful provider receipt still does not prove that a phone displayed or sounded an alert.

Enabling push and changing credentials remain deployment actions; neither diagnostic command nor the guard release performs them. Keep notification credentials out of chat and Git.
