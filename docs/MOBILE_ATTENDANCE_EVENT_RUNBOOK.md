# Mobile attendance event SLO and incident runbook

Scope: one 700-800-person attendance activity operated by 20-25 coordinators. This is the minimum production gate for a real event; a larger population or different network/proxy topology requires a new measured gate.

## Release authority and hard stop

The release owner, event manager, backend on-call, and mobile on-call must be named before distribution. The event manager is the only operational role allowed to globally close an attendance activity. Coordinators leave the activity locally.

Do not start the event unless every item below is recorded in the change ticket:

- backend and mobile Git revisions, deployment/image revision, app version/build number, Expo runtime fingerprint, artifact SHA-256, Android/iOS signing identity, and the immutable CI verification receipt for the exact submitted build ID;
- successful `/api/v1/health/live` and `/api/v1/health/ready` responses from the production edge;
- 800/800 fresh synthetic actions plus 100/100 deliberate same-passenger duplicates passing the staging attendance load gate below, with authoritative final server count exactly 800;
- signed release E2E on each approved device class, including offline scan, reconnect, refresh recovery, Scan Issues review, and manager closeout;
- production dashboards and alerts receiving the fixed-schema metrics in this document;
- one tested last-known-good binary/update and an assigned rollback owner;
- at least three event-ready spare devices (10% of a 25-device fleet) and one charger or power bank per five coordinators.

Any missing gate is a release block, not a warning.

For Android, run the manual `mobile/.eas/workflows/production-release.yml` path rather than invoking a production profile directly. Its fail-closed graph first runs locked source/audit/type/lint/test/coverage/maintainability/preflight gates, then release-Hermes journeys, then verifies the exact signed production APK, tests that same build ID, verifies the exact production AAB, requires human approval, and submits only that AAB build ID. Preserve both `android-production-apk-verification.json` and `android-production-aab-verification.json` with the change ticket. Each receipt must match the reviewed source revision, package, build ID, SHA-256, byte size, and approved distribution certificate. The distribution-certificate allowlist is separate from the Play App Signing certificate used by Android App Links. A local `assembleRelease` file, a running Gradle process, or a debug-signed APK is verification evidence only and is never a production release artifact.

## Approved device fleet

Repository minimums are Android API 26 (Android 8.0) and iOS 16.4. OS support alone does not approve a device. Each model/OS combination must pass the signed release test on physical hardware. Keep an inventory row for every primary and spare device:

| Evidence | Required value |
| --- | --- |
| Inventory ID and owner | Non-passenger operational identifier |
| Model and OS | Approved physical-device matrix; no emulator |
| Package | `com.globalconnects.groupcompanion` |
| App build | Approved version name plus Android version code or iOS build number |
| Runtime | Approved Expo runtime fingerprint/update ID |
| Artifact | SHA-256 equals the release ticket |
| Signing | Certificate/team fingerprint equals the release ticket |
| Capacity | Battery at least 80%; at least 2 GiB free storage |
| Device state | Automatic date/time on; camera permission granted; screen/camera/power saving tested |

Android evidence commands (use the exact approved artifact and connected inventory device):

```powershell
Get-FileHash -Algorithm SHA256 C:\approved\group-companion-release.apk
apksigner verify --verbose --print-certs C:\approved\group-companion-release.apk
adb shell dumpsys package com.globalconnects.groupcompanion | Select-String "versionName|versionCode"
adb shell getprop ro.build.version.release
adb shell df /data
adb shell dumpsys battery | Select-String "level|status|AC powered|USB powered"
```

For iOS, export the equivalent SHA-256, build number, signing Team ID/certificate, runtime/update ID, OS, capacity, and battery evidence from the protected build and managed-device inventory. Do not use a screenshot as the only source of truth.

At T-24 hours and again at T-60 minutes on every device:

1. Install only through the approved internal/managed distribution channel. Disable ad-hoc side-loading.
2. Confirm the build, runtime fingerprint/update, artifact hash, signing identity, device model, and OS against the ticket.
3. Open the camera, scan three authorized non-production rehearsal QRs, and prove immediate distinct success/duplicate/failure feedback, no duplicate count, queue drain, and server reconciliation. Confirm sound/haptics follow the event accessibility and noise policy.
4. Load the assigned trip, complete the in-app event-readiness checks, and confirm the roster, QR evidence, signed offline authorization, selected activity, camera, and last sync are valid through the event window.
5. Confirm active attendance queue `0`, Scan Issues/needs-review `0`, and realtime connected. A deliberately tested degraded/manual-sync path is required even when realtime is healthy.
6. Confirm battery at least 80%, at least 2 GiB free, automatic clock enabled, camera lens clean, notification volume policy set, charger/power bank labelled, and the coordinator knows the spare-device location.
7. Put the prior approved binary/update and rollback instructions in the protected distribution console. Test rollback on one spare before the event.

Use staged internal distribution: release owner -> two canary devices -> five coordinators -> full fleet. Hold each stage long enough to complete login, readiness, offline scan, reconnect, and sync reconciliation. Freeze updates during the live activity. If rollback is required, stop rollout, return the managed channel to the last compatible signed update or reinstall the last-known-good signed binary, then re-run readiness. Never change signing identity, runtime compatibility, or local app data as part of an emergency rollback.

## Production SLOs and alerts

All mobile metric names and attributes are compile-time allowlisted and scrubbed again before send. They contain no account, passenger, coordinator, trip, activity, device identifier, QR, token, URL, SQL, or error text.

| Signal | Target | Warning / critical action |
| --- | --- | --- |
| `gc.mobile.attendance.acknowledgement_latency` | Successful acknowledgements p95 <= 2 s; p99 <= 5 s | Filter latency SLO by `outcome=success`; alert separately on every failure/offline/timeout |
| `gc.mobile.attendance.scan.local_result` | Every camera decision produces exactly one fixed local outcome | `capacity_reached`, `needs_review`, or `previously_rejected` is immediately actionable; alert on sustained non-`queued` growth |
| `gc.mobile.attendance.scan.confirmed` | Accepted plus `already_applied` rows reconcile with backend aggregate outcomes | Any gap between delivered rows and confirmed outcomes is critical; `already_applied` must never increment the attendance total |
| Fresh action acceptance | 100%; no lost or duplicate scan | Any unexpected rejection, missing result, or duplicate fresh fixture is critical |
| Deliberate duplicate suppression | 100/100 return `already_applied`; final count remains 800 | Any accepted recount, rejection, missing result, or final count other than 800 is critical |
| `gc.mobile.queue.depth{queue=attendance}` | Each sample returns toward zero while online; operator inventory is locally clear and assigned coordinator-account checkpoints are recent and clear at closeout | Warn on sample max > 25 for 2 min; critical > 100 for 5 min or nonzero 10 min after scanning stops |
| `gc.mobile.attendance.queue.oldest_pending_age` | Zero when clear; under 60 s during healthy online delivery | Warn above 60 s while online; critical above 120 s for 2 min or on any nonzero age at closeout |
| `gc.mobile.attendance.needs_review.depth` | Zero | Warn on any value for 2 min; critical above 5 or any unresolved item at closeout |
| `gc.mobile.attendance.delivery.batch_size` | Every real POST contains 1-100 rows | A value outside the source-enforced bound is an instrumentation/release failure; trend p95 to detect unhealthy backlog bursts |
| `gc.mobile.attendance.delivery.failure` | Zero request failures; fixed class only | Alert on any `rate_limited` or `server_error` burst, any sustained `timeout`/`network` class, and never add raw status, URL, or error text |
| `gc.mobile.attendance.scan.terminal_rejection` | Zero during the live event | Any `authorization`, `assignment`, `idempotency`, `qr_evidence`, or `activity_state` category is critical; investigate fixed categories only, never raw errors |
| `gc.mobile.attendance.camera_to_local_queue` | p95 < 300 ms; p99 <= 1 s | Warn at 300 ms p95 for 2 min; critical above the p99 target for 5 min or on any failure outcome |
| `gc.mobile.attendance.queue_to_confirmation` | During connected operation p95 <= 2 s; p99 <= 5 s | Use queue age to distinguish offline backlog; critical if p99 remains above 5 s for 5 min while backend/realtime are healthy |
| `gc.mobile.attendance.reconciliation` | `reconciliation=ready` after queue drain and authoritative refresh | Any `count_mismatch`, `needs_review`, or `unverifiable` at closeout is critical; `pending_queue` blocks close until drained |
| `gc.mobile.attendance.retry` | Retried rows <= 1% of acknowledged rows over 5 min | Warn above 1%; critical above 5%. A `success` means a valid response contract was received |
| `gc.mobile.attendance.refresh_recovery` | >= 99% success excluding explicitly offline attempts; one automatic refresh only | Any loop, second automatic refresh, or unresolved recovery is critical; offline is degraded and must later converge |
| `gc.mobile.attendance.discarded` | Zero during event operations | Any nonzero value is critical and requires the protected destructive-confirmation audit to reconcile; this metric is aggregate count only |
| `gc.mobile.authentication.lock` | Zero failures | Any `outcome=failure` is critical because protected local state may require operator recovery |
| `gc.mobile.authentication.quarantine.depth` | Zero at event readiness and after same-account recovery | Warn on any nonzero startup sample; critical if it persists through one approved same-account recovery attempt |
| `gc.mobile.realtime.connection` | Success ratio >= 99% over 5 min | Warn below 99%; critical below 95%. Switch UI/operator expectation to degraded/manual sync |
| `gc.mobile.realtime.connection.duration` | p95 <= 2 s; p99 <= 5 s | Same latency alert windows as acknowledgement |
| `gc.mobile.realtime.reconnect` | No sustained storm | Critical when reconnects exceed 5 per active device in 5 min or backend lease/readiness alarms fire |
| Synthetic dashboard commit -> mobile visible | p95 <= 2 s; p99 <= 5 s while realtime is healthy | Critical above p95 for 5 min or on any cursor mismatch; use non-production synthetic correlation only |
| Synthetic mobile scan -> dashboard visible | p95 <= 2 s; p99 <= 5 s while realtime/polling are healthy | Critical above p95 for 5 min or if the authoritative dashboard count diverges; never tag real passenger identity |
| `gc.mobile.storage.maintenance.run` | Zero failures | Any failure is warning; repeated failure on one release is critical before the next event |
| `gc.mobile.storage.maintenance.duration` | p95 <= 5 s while idle | Critical above 10 s or if user-visible work is blocked |
| `gc.mobile.storage.maintenance.changed_rows` | Trend only; bounded count-only evidence | Investigate a sudden release-to-release increase above 5,000 rows per run; never infer passenger identity |
| Backend live/ready | 100% success from the public edge | Critical after two failed 15-second checks; freeze close/signout/discard operations |
| Backend app-integrity verification | No unexpected production enforcement failures | Alert on any sustained failure increase; distinguish provider outage/configuration from invalid proof without recording proof material |
| Crash/ANR | Crash-free sessions >= 99.95%; Android ANR < 0.1% | Existing release alert thresholds remain hard gates |

Dashboard panels must show the release/build, environment, count/rate, p50/p95/p99, and alert state without adding custom high-cardinality tags. Mobile gauges are anonymous operational samples, so use max and p95 rather than summing them or treating them as a physical-device inventory. The server close guard uses the latest report from each assigned coordinator account; it does not prove that every physical installation for that account is clear. Correlate it with the protected operational device inventory and the backend's aggregate attendance accepted/rejected/idempotent counts, API latency/errors, PostgreSQL pool/query latency, Redis/realtime health, Nginx/CDN errors, and deployment revision.

The repository emits the mobile measurements, but creation of Sentry/monitoring dashboards, alert routes, retention policy, and on-call paging is an external control. The release owner must attach a screenshot/export of a test alert and acknowledgement; code presence alone is not monitoring proof.

## Live incident procedure

When any critical threshold fires:

1. Event manager announces degraded mode and records the incident start, affected build, backend revision, queue max, needs-review count, and last healthy acknowledgement time. Do not record names, QRs, tokens, or passenger IDs in telemetry/chat.
2. Coordinators keep the app installed and preserve local encrypted data. Do not sign out, switch account, clear storage, reinstall, or choose **Discard changes**. Continue local scanning if readiness/offline authorization remains valid; otherwise stop that device and use an approved spare.
3. Each coordinator opens Scan Issues, records count-only `pending/retryable/needs review`, tries **Sync now** once on a known-good network, and reports only the inventory ID and aggregate counts to the manager.
4. Backend on-call checks public live/ready, deployment revision, attendance POST p95/p99 and errors, database pool/locks, Redis/realtime lease health, proxy/CDN errors, clock skew, and rate limits. Realtime failure is freshness degradation; durable cursor sync and idempotent attendance remain authoritative.
5. If a device has hard authentication loss, retain it powered and locked. Reauthenticate the same account to unlock its encrypted queue. Do not replace/delete that device's data until its queue is zero or formally recovered.
6. Manager assigns an approved spare only after preserving the original device. A replacement may scan new passengers, but it must not be used to conceal an unresolved old-device queue.
7. Mobile/backend release owners decide fix-forward or rollback. Roll back only through the approved managed channel and compatible signed runtime. Re-run login, readiness, one fresh scan, queue drain, and realtime/manual sync on canaries before widening.
8. Manager does not globally close the activity until the protected operational inventory confirms every scanning device has active queue `0` and needs-review `0`, every assigned coordinator account has a recent clear server checkpoint, server accepted/idempotent/rejected totals reconcile with the assigned roster and count-only summaries, and all explicit exceptions have an owner. The server checkpoint is account-level latest-report evidence, not proof of every installation. Use a second manager confirmation for global close.

Coordinator recovery checklist: preserve app/data -> check readiness -> scan locally only if authorized -> Sync now -> resolve Scan Issues -> same-account reauth if locked -> report count-only status -> return original device only after queue zero.

Manager recovery checklist: declare degraded mode -> inventory primary/spares -> collect count-only device state -> verify backend health -> coordinate same-account recovery -> reconcile server/device totals -> resolve every Scan Issue -> second-manager close confirmation -> retain evidence and incident timeline.

## Canonical 25-coordinator / 800-scan staging gate

Run only against the separately identified, approved staging environment. The executable harness is `load-tests/k6/mobile-attendance.js`. It uses 25 unique short-lived coordinator access sessions and 32 unique fresh synthetic QR actions per coordinator, paced at roughly 3.75 seconds per coordinator (800 actions in about two minutes). The first four fresh actions on every coordinator are then repeated with different event IDs (100 deliberate duplicates). It requires all fresh results to be `accepted`, every deliberate duplicate to be `already_applied`, fresh and duplicate p95 below 2 seconds and p99 below 5 seconds, no malformed/authentication/rate/proxy result, and authoritative final count exactly 800.

The protected fixture is an array of exactly 25 entries. Each has `access_token`, `trip_id`, `session_id`, and exactly 32 unique `actions`; each action has a fresh UUID `client_event_id`, a valid synthetic `signed_qr`, and `duplicate_client_event_id`. That second ID is a different globally unique UUID on the first four actions and `null` on the remaining 28. Never commit, print, tag, or retain the fixture after the run. Revoke all access sessions and QR evidence afterward. Reusing a fixture is a failed test because the preflight requires authoritative server count zero.

```powershell
$env:BASE_URL = "https://mobile-staging.example.com/api/v1"
$env:LOAD_TEST_EXPECTED_ORIGIN = "https://mobile-staging.example.com"
$env:LOAD_TEST_PRODUCTION_ORIGIN = "https://mobile.example.com"
$env:LOAD_TEST_TARGET_ENVIRONMENT = "staging"
$env:LOAD_TEST_APPROVAL_REFERENCE = "change-12345"
$env:LOAD_TEST_ID = "attendance-event-2026-08-22"
$env:LOAD_TEST_APPROVED = "true"
$env:MOBILE_LOAD_PROFILE = "smoke"
$env:MOBILE_ATTENDANCE_LOAD_DATA = "C:\secure\mobile-attendance-load-data.json"
$env:MOBILE_ATTENDANCE_COORDINATORS = "25"
$env:MOBILE_ATTENDANCE_SCANS_PER_COORDINATOR = "32"
$env:MOBILE_ATTENDANCE_DUPLICATES_PER_COORDINATOR = "4"
$env:MOBILE_ATTENDANCE_SCAN_INTERVAL_MS = "3750"

node --test .\load-tests\k6\mobile-attendance-load-contract.test.mjs
k6 run --summary-export ".\evidence\$($env:LOAD_TEST_ID)-attendance.json" .\load-tests\k6\mobile-attendance.js
```

The harness itself proves an active 800-person roster and server count zero before writes, then requires exactly 800 after 800 accepted fresh actions and 100 `already_applied` duplicates. After k6 passes, additionally require active queue zero on all test devices, needs-review zero, dashboard/mobile convergence evidence, and matching backend aggregate audit totals. Retain the immutable k6 summary, dashboard export, server aggregate reconciliation, revisions/configuration, generator telemetry, test device matrix, and alert/rollback drill timeline. The repository cannot execute or certify this external staging, device-fleet, monitoring, distribution, or on-call gate by itself.
