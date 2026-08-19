# Global Connect Travels Mobile

Production React Native companion for PassDetection passengers, client managers, and coordinators. It is an Expo Prebuild application—not a WebView—and produces native Android and iOS projects from one strict TypeScript codebase.

## Architecture

- Expo SDK 57, React Native 0.86, React 19, Expo Router, and role-gated native stacks.
- TanStack Query for bounded server state and request deduplication; Zustand only for small ephemeral selections.
- Dedicated `/api/v1/mobile` contracts validated at runtime with strict Zod schemas.
- Per-account SQLCipher databases, incremental cursors, resource fingerprints, full-page aggregation before authoritative pruning, and idempotent mutation queues.
- SecureStore/Android Keystore/iOS Keychain for refresh tokens, database keys, and AES vault keys. Access tokens remain in memory.
- AES-GCM application-private document vault with authenticated 256 KiB frames, SHA-256 verification, signed exact byte limits, restart-resumable unknown-length/chunked transfers, a 25 MB/document limit, bounded concurrency, free-space headroom, and short-lived passenger/group-bound download grants.
- Expo Notifications provider abstraction, private Android notification visibility, durable read state, strict deep-link routing, and push-triggered refresh.
- Expo Background Task for opportunistic synchronization; foreground and reconnect synchronization remain authoritative because operating systems do not guarantee background execution.

SecureStore access is sensitivity-tiered and centralized. The document-vault key and signed offline-authorization lease are unlocked-only on iOS and blocked by the application outside an active foreground; exact background metadata requirements use device-only after-first-unlock storage. Android receives separate Keystore aliases per tier, but Expo does not expose native unlocked-device-required keys, so physical lock/reboot testing and the residual native-hardening decision remain release gates. Biometric `requireAuthentication` is not enabled because it would invalidate keys on enrollment changes and break required headless/non-biometric workflows. See `docs/MOBILE_KEY_ACCESSIBILITY.md`.

The encrypted local namespace includes agency, principal, trip, and—where applicable—passenger ownership. Ordinary sign-out, account switching, access-generation changes, trip removal, access denial, expiry, and installation reset purge the affected database rows, encrypted vault files, account-scoped keys, and temporary viewer files. Sign-out clears in-memory authentication immediately, attempts server-session and push-registration revocation without making local sign-out depend on the network, and records a durable cleanup marker before destructive local work. An interrupted deletion stays fenced and is retried before that namespace can be reopened. The next login therefore performs a fresh synchronization; there is no retained-on-sign-out reactivation mode. See `docs/MOBILE_LOCAL_DATA_RETENTION.md`.

Production release additionally requires signed-device storage inspection after sign-out, force-stop during cleanup, reboot, restore, and reinstall, as well as offline shell restoration tests proving that cached access is granted only by a valid signed offline-authorization lease or a successful online session check.

## Configuration

Copy `.env.example` to an ignored `.env.local` and set:

```text
EXPO_PUBLIC_API_URL=https://api.example.com/api/v1
EXPO_PUBLIC_APP_ENV=development|preview|production
EXPO_PUBLIC_DEMO_MODE=false
EXPO_PUBLIC_EAS_PROJECT_ID=<Expo project UUID>
EXPO_PUBLIC_EXPO_OWNER=<Expo account>
EXPO_PUBLIC_UPDATES_URL=https://u.expo.dev/<Expo project UUID>
EXPO_UPDATES_CODE_SIGNING_CERTIFICATE=<path to protected build input certificate.pem>
GOOGLE_SERVICES_JSON=<path to protected Firebase google-services.json>
GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS=<production SHA-256 fingerprint(s)>
GC_APPLE_TEAM_ID=<10-character Apple Team ID>
```

Never place API, SMS, push-service, signing, or encryption secrets in an `EXPO_PUBLIC_*` variable. Non-development builds reject cleartext API origins. Android manifest configuration also disables cleartext traffic and backups.

Every production build must provide the API URL, `EXPO_PUBLIC_APP_ENV=production`, and `EXPO_PUBLIC_DEMO_MODE=false`. A real EAS project ID may be supplied by itself to enable push-token registration while OTA updates remain disabled. To enable EAS Update, also provide the Expo owner, canonical Update URL containing the same project UUID, and a build-time verification certificate. Unsigned remote updates are rejected by configuration. The private update-signing key is used only by the protected publishing job and must never enter the repository or application build.

Production release preparation also validates the external App Link/Universal Link files before regenerating native projects. `https://tech.gctravels.com/.well-known/assetlinks.json` and `https://tech.gctravels.com/.well-known/apple-app-site-association` must return HTTP 200 JSON directly, without redirects, and must match the protected Android signing fingerprint or Apple Team ID. The deployed backend derives those public documents from the same signing identities enforced by Play Integrity and App Attest. Native generation fails closed if the deployment configuration is missing or points elsewhere.

The Expo project ID, owner, API URL, and update URL are public application configuration, not signing credentials. Keep Android keystores, Apple certificates, service-account keys, provider tokens, and update-signing private keys out of `.env` and `EXPO_PUBLIC_*`.

`EXPO_PUBLIC_DEMO_MODE` is a local emulator-preview switch, not an authentication setting. It only activates when the app uses the separate `com.globalconnects.groupcompanion.demo` package, the app environment is `development`, the API host is loopback, and Expo identifies the runtime as an emulator/simulator. The demo network layer is blocked before `fetch`; normal APK/AAB builds remain on real backend authentication.

## Local validation

Use Node.js 20.19.4 LTS (the repository `.nvmrc` default), JDK 17, Android SDK 35 or newer, and an Android device/emulator. The package accepts the React Native-supported Node 20.19.4, 22.13+, and 24.3+ lines with npm 10 or 11:

```powershell
npm ci
npm run typecheck
npm run lint
npm test
npm run doctor
npm run dependencies:check
npm run audit:runtime
```

This app uses SQLCipher, native PDF rendering, camera, notifications, and secure storage. Expo Go is not a valid runtime; use a native development build.

### Release-Hermes emulator/simulator smoke

The `e2e-test` EAS profile produces an Android APK and iOS simulator `.app` without distribution credentials. The manual workflow at `.eas/workflows/release-hermes-smoke.yml` builds both artifacts with the explicitly configured Hermes engine, runs `.maestro/release-hermes-auth-smoke.yml`, and records the emulator/simulator screens:

```powershell
npx eas workflow:run .eas/workflows/release-hermes-smoke.yml
```

Run this from the linked, protected Expo project with its `preview` environment configured. The source workflow follows Expo's [EAS Maestro E2E pattern](https://docs.expo.dev/eas/workflows/examples/e2e-tests/) and [pre-packaged Maestro job contract](https://docs.expo.dev/eas/workflows/pre-packaged-jobs/). A successful cloud run is required evidence; merely parsing these YAML files locally is not a passing test. This smoke proves only release-engine startup and the anonymous passenger/staff authentication shells. It does not replace store-signed physical-device tests for secure documents, camera scanning, links, push, app attestation, storage cleanup, screenshots, background execution, performance, or accessibility.

## Native projects and Android builds

Generate native projects after changing app configuration or native dependencies:

```powershell
npm run native:sync
```

For a local Android release verification build, first export the real public production configuration:

```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
$env:EXPO_PUBLIC_API_URL='https://tech.gctravels.com/api/v1'
$env:EXPO_PUBLIC_APP_ENV='production'
$env:EXPO_PUBLIC_DEMO_MODE='false'
$env:EXPO_PUBLIC_EAS_PROJECT_ID='<real Expo project UUID>'
$env:EXPO_PUBLIC_EXPO_OWNER='<real Expo account>'
$env:EXPO_PUBLIC_UPDATES_URL="https://u.expo.dev/$env:EXPO_PUBLIC_EAS_PROJECT_ID"
$env:EXPO_UPDATES_CODE_SIGNING_CERTIFICATE='C:\protected\updates\certificate.pem'
$env:GOOGLE_SERVICES_JSON='C:\protected\firebase\google-services.json'
$env:GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS='<production SHA-256 fingerprint>'
npm run release:validate-env
npm run android:apk
npm run android:aab
```

The release scripts validate the supported Expo dependency set, production public environment, Firebase package identity, update-signing certificate, and live App Link association before cleanly regenerating the Android project. They serialize Gradle work and reserve up to 4 GB heap/1 GB metaspace because SQLCipher, Expo Updates, Hermes, and four native ABIs can exceed Gradle's small default metaspace during KSP/lint analysis.

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
npm run release:preflight-android
npx eas build --platform android --profile production-apk
npx eas build --platform android --profile production
```

Run the matching `release:preflight-ios` gate before a production iOS EAS build. Protected CI/CD should make these preflight commands mandatory rather than invoking a production EAS profile directly.

`production-apk` is the installable internal-testing variant and inherits the production environment, channel, version increment, and protected EAS Android credentials. `production` produces the Play Store AAB. A profile definition does not prove that credentials exist or that a build is distribution-signed; confirm the EAS project and credential assignment before distributing either artifact. The `fingerprint` OTA runtime policy prevents updates built against a different native dependency/configuration fingerprint from reaching an incompatible binary.

## iOS build and signing

Generate `ios/` with `npm run native:sync`. Final compilation and signing require macOS, Xcode, an Apple Developer team, a matching provisioning profile, push-notification entitlement, and the associated-domain file for `tech.gctravels.com`.

On macOS, also set `GC_APPLE_TEAM_ID` to the production team identifier. The Universal Link association gate runs before native generation against `tech.gctravels.com`:

```bash
npm ci
npm run release:prepare-ios
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
- Interrupted responses retain only independently authenticated encrypted frames in app-private storage and resume from the exact verified byte with one open-ended HTTP range. Every segment must match the signed total size and exact `Content-Range`; final plaintext size and SHA-256 are verified before the immutable ciphertext is registered. No plaintext download staging is persisted. A process kill inside one partially written filesystem frame discards that staging file and restarts safely; completed frames resume normally.

Before production, verify backup/restore behavior, rooted-device policy wording, lock-screen redaction, universal/app links, notification credentials, retention windows, and device/session revocation on physical Android and iOS devices.
