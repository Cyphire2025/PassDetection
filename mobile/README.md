# Group Companion Mobile

Production React Native companion for PassDetection passengers, client managers, and coordinators. It is an Expo Prebuild application—not a WebView—and produces native Android and iOS projects from one strict TypeScript codebase.

## Architecture

- Expo SDK 57, React Native 0.86, React 19, Expo Router, and role-gated native stacks.
- TanStack Query for bounded server state and request deduplication; Zustand only for small ephemeral selections.
- Dedicated `/api/v1/mobile` contracts validated at runtime with strict Zod schemas.
- Per-account SQLCipher databases, incremental cursors, resource fingerprints, full-page aggregation before authoritative pruning, and idempotent mutation queues.
- SecureStore/Android Keystore/iOS Keychain for refresh tokens, database keys, and AES vault keys. Access tokens remain in memory.
- AES-GCM application-private document vault with authenticated metadata, SHA-256 verification, exact `Content-Length`, a 25 MB/document limit, two-download concurrency, free-space headroom, and short-lived passenger/group-bound download grants.
- Expo Notifications provider abstraction, private Android notification visibility, durable read state, strict deep-link routing, and push-triggered refresh.
- Expo Background Task for opportunistic synchronization; foreground and reconnect synchronization remain authoritative because operating systems do not guarantee background execution.

The encrypted local namespace includes agency, principal, trip, and—where applicable—passenger ownership. Account switching, logout, access-generation changes, trip removal, access denial, and expiry purge the affected database rows, vault files, secrets, and temporary viewer files.

## Configuration

Copy `.env.example` to an ignored `.env.local` and set:

```text
EXPO_PUBLIC_API_URL=https://api.example.com/api/v1
EXPO_PUBLIC_APP_ENV=development|preview|production
EXPO_PUBLIC_DEMO_MODE=false
EXPO_PUBLIC_EAS_PROJECT_ID=<Expo project UUID>
EXPO_PUBLIC_EXPO_OWNER=<Expo account>
EXPO_PUBLIC_UPDATES_URL=<optional EAS Update URL>
```

Never place API, SMS, push-service, signing, or encryption secrets in an `EXPO_PUBLIC_*` variable. Non-development builds reject cleartext API origins. Android manifest configuration also disables cleartext traffic and backups.

`EXPO_PUBLIC_DEMO_MODE` is a local emulator-preview switch, not an authentication setting. It only activates when the app uses the separate `com.globalconnects.groupcompanion.demo` package, the app environment is `development`, the API host is loopback, and Expo identifies the runtime as an emulator/simulator. The demo network layer is blocked before `fetch`; normal APK/AAB builds remain on real backend authentication.

## Local validation

Use Node.js 20 LTS, JDK 17, Android SDK 35 or newer, and an Android device/emulator:

```powershell
npm ci
npm run typecheck
npm run lint
npm test
npm run doctor
```

This app uses SQLCipher, native PDF rendering, camera, notifications, secure storage, and biometrics. Expo Go is not a valid runtime; use a development build.

## Native projects and Android builds

Generate native projects after changing app configuration or native dependencies:

```powershell
npm run native:sync
```

For a local Android release build:

```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
npm run android:apk
npm run android:aab
```

The release scripts serialize Gradle work and reserve up to 4 GB heap/1 GB metaspace because SQLCipher, Expo Updates, Hermes, and four native ABIs can exceed Gradle's small default metaspace during KSP/lint analysis.

Outputs are normally:

- `android/app/build/outputs/apk/release/app-release.apk`
- `android/app/build/outputs/bundle/release/app-release.aab`

Configure a protected production upload keystore or EAS credentials before distribution. Do not ship a locally debug-signed artifact as production.

For the isolated Android emulator demo, preserve any normal release artifact first, then build only the x86_64 preview:

```powershell
$env:NODE_ENV='production'
$env:EXPO_PUBLIC_APP_ENV='development'
$env:EXPO_PUBLIC_API_URL='http://10.0.2.2:8000/api/v1'
$env:EXPO_PUBLIC_DEMO_MODE='true'
.\android\gradlew.bat -p android --no-parallel '-Dorg.gradle.jvmargs=-Xmx4096m -XX:MaxMetaspaceSize=1024m' -PgcDemoMode=true -PreactNativeArchitectures=x86_64 assembleRelease
```

The demo must never be shared as the production application: it is a separately packaged, emulator-only, local-data preview.

EAS alternatives:

```powershell
npx eas build --platform android --profile preview
npx eas build --platform android --profile production
```

## iOS build and signing

Generate `ios/` with `npm run native:sync`. Final compilation and signing require macOS, Xcode, an Apple Developer team, a matching provisioning profile, push-notification entitlement, and the associated-domain file for `app.globalconnecttravels.com`.

On macOS:

```bash
npm ci
npx expo prebuild --platform ios
cd ios
pod install
open GroupCompanion.xcworkspace
```

Select the production team/bundle identifier, validate push and associated-domain entitlements, archive with the Release configuration, then distribute through TestFlight/App Store Connect.

## Security and offline behavior

- Sensitive screens prevent capture where the OS supports it; notification bodies contain no document details.
- A positive root/jailbreak signal disables offline document download and viewing while itinerary/emergency features remain usable. Detection is cached, experimental, and defense-in-depth—not proof a device is trustworthy. Detection errors produce an `unknown` result and do not crash the app.
- Document bytes require a fresh authorization grant and `X-GC-Download-Token`; raw storage URLs are never stored.
- Pending legacy document metadata is visible but cannot be downloaded until the server has verified its size and SHA-256.
- Interrupted metadata pagination never replaces the last complete local snapshot.
- Attendance scans and incident reports are committed to SQLCipher with UUID idempotency keys before network submission.
- Range-resume for encrypted document downloads is intentionally deferred: buffering an unverified partial response would weaken the current integrity boundary. Failed downloads retry from the verified beginning.

Before production, verify backup/restore behavior, rooted-device policy wording, lock-screen redaction, universal/app links, notification credentials, retention windows, and device/session revocation on physical Android and iOS devices.
