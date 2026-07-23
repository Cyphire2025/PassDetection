# Global Connects Coordinators App

This folder is a self-contained Android project for the existing coordinator
PWA. The app deliberately does not duplicate the Next.js interface. It uses a
small native Android shell around the deployed coordinator route, so Android
and iPhone PWA users receive the same screens, validation, API behavior, and
server-side updates.

## Architecture

- Java 17, Android Gradle Plugin 8.13.1, Gradle 8.14.5.
- Minimum Android 8.0 (API 26); target Android 16 (API 36).
- One hardware-accelerated WebView with no native JavaScript bridge.
- Production starts at `https://tech.gctravels.com/coordinator`.
- Authentication remains in the existing same-origin, httpOnly cookies.
- Camera permission is granted only to the configured origin and only for
  video capture. Microphone and geolocation are never granted.
- DOM storage and IndexedDB stay enabled because the PWA uses them for
  user-scoped offline snapshots and pending attendance scans.
- Android handles file selection, image capture, downloads, external links,
  renderer recovery, lifecycle, and predictive-back-compatible navigation.

## Build variants

| Variant | Purpose | Network policy | Application ID |
| --- | --- | --- | --- |
| `productionDebug` | Installable QA build using the production origin | HTTPS only | `com.globalconnects.coordinator.debug` |
| `productionRelease` | Distribution build signed with the owner key | HTTPS only | `com.globalconnects.coordinator` |
| `localDebug` | Emulator testing against local Next.js | Cleartext only for loopback/emulator hosts | `com.globalconnects.coordinator.local.debug` |

The local exception is isolated under `app/src/local`. The main/production
manifest always has `android:usesCleartextTraffic="false"`.

## Build an installable production QA APK

```powershell
Set-Location 'C:\Users\nipun\Desktop\PassDetection\Coordinators app'
.\build-production-debug.ps1
```

The result is `artifacts\CoordinatorApp-production-debug.apk`. It is signed by
the standard Android debug key and is suitable for testing, not long-term
customer distribution.

The production origin is deliberately locked to
`https://tech.gctravels.com/coordinator`. Passing a different `-PappUrl`
fails the Gradle configuration; neither build scripts nor environment
variables can redirect the customer app to another host.

## Build the customer release APK

Create and retain one organization-owned Android signing key. Never commit the
keystore or its passwords. Set these variables in the build environment:

```powershell
$env:COORDINATOR_KEYSTORE_FILE = 'D:\secure\coordinator-release.jks'
$env:COORDINATOR_KEYSTORE_PASSWORD = '<from-secret-manager>'
$env:COORDINATOR_KEY_ALIAS = 'coordinator'
$env:COORDINATOR_KEY_PASSWORD = '<from-secret-manager>'
.\build-signed-release.ps1
```

The result is `artifacts\CoordinatorApp-release.apk`. Keep the same key for
every update or Android will not allow an in-place upgrade.

## Local emulator verification

Start the repository’s local Docker stack. The production-shaped compose file
does not publish the frontend container directly, so start the included
temporary, loopback-only QA proxy. It joins the existing Docker network and
routes pages to the frontend and `/api/` to the backend:

```powershell
Set-Location 'C:\Users\nipun\Desktop\PassDetection\Coordinators app'
.\start-local-test-proxy.ps1
.\build-local-debug.ps1
adb reverse tcp:3100 tcp:3100
adb install -r '.\artifacts\CoordinatorApp-local-debug.apk'
adb shell am start -n 'com.globalconnects.coordinator.local.debug/com.globalconnects.coordinator.MainActivity'
```

`adb reverse tcp:3100 tcp:3100` makes that local Docker proxy available at
`http://localhost:3100` inside the emulator. Chromium/WebView treats loopback
localhost as a potentially trustworthy origin, so `window.isSecureContext`,
camera APIs, and service workers remain available without any SSL bypass.
Clean up only the temporary test mapping/container after testing:

```powershell
adb reverse --remove tcp:3100
.\stop-local-test-proxy.ps1
```

The local flavor is also locked to
`http://localhost:3100/coordinator`; the documented localhost-plus-reverse
topology is required for scanner and service-worker acceptance.

## Required server readiness

The APK is a shell for the live PWA. The production server must deploy the
coordinator routes and their matching `_next/static` assets before distributing
the customer APK. The app intentionally refuses invalid TLS certificates and
does not contain an SSL bypass.

## Release acceptance

Before customer distribution, verify at least:

1. Login, refresh-token recovery, logout, and account switching.
2. Group list, group activity, passenger details, and hotel check-in.
3. QR scanning on representative low-, mid-, and high-end physical phones.
4. Camera denial, later enablement from Android settings, and torch behavior.
5. Offline scan queueing, reconnect sync, and account-change cleanup.
6. File picker/camera upload inputs used by the deployed PWA.
7. Back gesture, rotation, keyboard resize, small screen, notched screen, and
   large-font accessibility.
8. Server 5xx, no-network, invalid-certificate, and WebView renderer recovery.
9. Upgrade from the previous APK using the same release signing key.

An emulator build proves packaging and WebView integration, but it does not
replace real-camera, OEM WebView, mobile-network, or physical-device testing.
