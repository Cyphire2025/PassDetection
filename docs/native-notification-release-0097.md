# Native notifications and separate authored alerts — release 0097

See [the operator guide](gc-app-notifications-0097.md) for the dashboard workflow.

## Delivery and app builds

Android uses **VPS → Google FCM → Android**. iPhone uses **VPS → Apple APNs → iPhone**. Neither path uses Expo's notification relay. The Expo native notification library still supplies device permissions, token acquisition and notification presentation.

The source version is **1.0.6**, Android version code **7**, iOS build **2**. Previously installed apps need a new native build to register the intended native provider and open the new Phone alerts inbox. Existing Expo registration records cannot be converted into native tokens by the server.

iPhone delivery requires an Apple Developer Program account, a push-enabled App ID for `com.globalconnects.groupcompanion`, suitable signing/provisioning, and protected APNs credentials. A free Xcode Personal Team cannot provide ordinary remote push. For private development/preview builds using that team, set `GC_IOS_PUSH_NOTIFICATIONS_ENABLED=false` before normal native generation. This omits the push entitlement; it does not change an already-generated Xcode project by itself. The app explains that this build does not support phone notifications. Production builds reject this disabled-push override.

The APNs sandbox/production destination follows the **installed signed provisioning profile**, independently of which API environment the build uses. An App Store build without an embedded profile uses production after native token acquisition succeeds. The backend stores this environment beside the encrypted device token and rechecks it before delivery.

## Future APNs configuration

Keep `MOBILE_PUSH_APNS_ENABLED=false` until the paid account and device signing are ready. Android remains independent.

1. Create the App ID and APNs authentication key in the owner's Apple Developer account. Keep the private `.p8` file out of source control, chat, mobile bundles and public environment variables.
2. Place the key at `/opt/global-connect-secrets/apns/AuthKey.p8`, with directory/file permissions permitting the existing push-worker UID to read it and no public access. Preserve any previous key for the approved rotation procedure.
3. Configure the protected backend environment with `MOBILE_PUSH_APNS_ENABLED=true`, `MOBILE_PUSH_APNS_KEY_FILE=/run/gc-apns/AuthKey.p8`, and the corresponding ten-character `MOBILE_PUSH_APNS_KEY_ID` and `MOBILE_PUSH_APNS_TEAM_ID`.
4. Use the release helper below. When APNs is enabled, it includes `docker-compose.apns.yml` in both preparation and activation. That overlay mounts FCM and APNs directories read-only into the push worker. Missing host directories fail; they are not created implicitly. Backend/other workers receive settings but no APNs private-key mount.
5. Install the appropriately signed iPhone build, allow notifications, check registration in app settings, and test foreground/background/closed-app presentation and taps. Confirm Android still works separately.

An enabled setting is configuration evidence. A provider accepting a request is provider evidence. Neither proves that a phone displayed a banner. APNs does not expose a per-notification delivery receipt through this provider API.

## Persistence and retry behavior

- Explicit Send stores an immutable batch, recipient snapshots, original trip grants and queued notification rows in one transaction. HTTP 202 is returned only after commit. The periodic worker recovers queued work without relying on a task being published by the HTTP request.
- The same agency/request UUID recovers the original send. A deliberate resend creates a new request and a fresh audience review.
- Native delivery commits a submitting attempt before the provider call. If the worker disappears or the response is ambiguous after that point, the outcome stays unknown and is not automatically resent.
- Explicitly retryable failures can retry within the original 24-hour window. Accepted/read outcomes do not move backwards. A replacement registration on the same installation does not repeat an already accepted or uncertain authored alert.
- Provider batches are bounded; Android and iOS work remains independently discoverable even after another device accepts. A separate retry timestamp prevents devices without registrations from continuously blocking ready work, without hiding the alert from the app inbox.
- Current agency, role, trip availability and submitted-contact authority are rechecked before delivery and inbox access. Original grants are retained across one trip's removal; a newly granted trip cannot retroactively authorize the old send. An explicitly revoked device session still requires normal sign-in and registration.

## Migration and activation

`0097_authored_notifications` follows `0096_mobile_phone_lookup`. It adds four authored-notification tables, the scoped notification link, APNs environment, and a push-retry timestamp/index. It preserves existing announcement content and provider history. Definitely unsent announcement device attempts are cancelled; interrupted attempts with uncertain outcomes are marked unknown. Publishing an announcement no longer triggers a phone alert.

Prepare the exact main commit with:

```sh
python3 scripts/release_authored_notifications.py prepare --revision <exact-main-commit>
```

Preparation retains the previous application images and builds the backend, frontend and shared worker images. Before activation, establish the verified ingress barrier, pause Beat, drain workers and broker queues, preserve container writable files and logs, and record table counts. The helper requires and fully decodes a preserved PostgreSQL custom backup before applying the migration.

```sh
python3 scripts/release_authored_notifications.py activate --revision <same-commit> --traffic-paused
```

Verify schema 0097, every application revision, worker registration/health, Beat, frontend, Nginx configuration, public readiness, unchanged infrastructure volumes and retained data before removing the ingress barrier. Keep all backups, previous images, evidence and APKs. Do not downgrade this migration or activate old workers that can resume announcement-linked phone sends. Recover with a reviewed forward correction if necessary.

Unit/browser/provider fakes, real PostgreSQL transaction tests, native compilation and signed APK inspection cover different boundaries. Exact CI, deployed revision and physical-device evidence belong in the release handoff; passing source checks alone must not be reported as successful phone delivery.
