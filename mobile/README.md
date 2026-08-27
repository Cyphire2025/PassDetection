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

Secure storage is sensitivity-tiered and centralized. The document-vault key and signed offline-authorization lease use unlocked-only iOS Keychain storage; on Android they are AES-GCM wrapped by the generated native `GCUnlockedDeviceStore`. Android 15/API 35+ uses a Keystore `UNLOCKED_DEVICE_REQUIRED` key, while API 26-34 uses a compatibility-safe Keystore key with native lock-state checks because Android documents defects in the stricter flag before API 35. Exact background metadata requirements retain device-only after-first-unlock storage. Biometric `requireAuthentication` is not enabled because it would invalidate keys on enrollment changes and break required headless/non-biometric workflows. Physical lock/reboot/OEM proof remains a release gate, especially for the API 26-34 native-guard residual. See `docs/MOBILE_KEY_ACCESSIBILITY.md`.

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
GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS=<approved EAS upload/distribution SHA-256 fingerprint(s)>
GC_APPLE_TEAM_ID=<10-character Apple Team ID>
```

Never place API, SMS, push-service, signing, or encryption secrets in an `EXPO_PUBLIC_*` variable. Non-development builds reject cleartext API origins. Android manifest configuration also disables cleartext traffic and backups.

Every production build must provide the API URL, `EXPO_PUBLIC_APP_ENV=production`, and `EXPO_PUBLIC_DEMO_MODE=false`. A real EAS project ID may be supplied by itself to enable push-token registration while OTA updates remain disabled. To enable EAS Update, also provide the Expo owner, canonical Update URL containing the same project UUID, and a build-time verification certificate. Unsigned remote updates are rejected by configuration. The private update-signing key is used only by the protected publishing job and must never enter the repository or application build.

Production release preparation also validates the external App Link/Universal Link files before regenerating native projects. `https://tech.gctravels.com/.well-known/assetlinks.json` and `https://tech.gctravels.com/.well-known/apple-app-site-association` must return HTTP 200 JSON directly, without redirects, and must match the protected Android signing fingerprint or Apple Team ID. The deployed backend derives those public documents from the same signing identities enforced by Play Integrity and App Attest. Native generation fails closed if the deployment configuration is missing or points elsewhere.

The Expo project ID, owner, API URL, update URL, and certificate fingerprints are public identifiers, not signing credentials. Keep Android keystores, Apple certificates, service-account keys, provider tokens, and update-signing private keys out of `.env` and `EXPO_PUBLIC_*`. Store the reviewed fingerprint allowlists in the protected EAS production environment so an unreviewed workflow change cannot silently approve a different signer.

Android uses two deliberately separate trust roots. `GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS` must match the certificate that signs the installed Play-distributed app and is published in `assetlinks.json`; with Play App Signing this is normally the Play app-signing certificate. `GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS` is the fail-closed allowlist used to inspect the exact EAS-produced APK and AAB before approval; it normally contains the EAS upload/distribution certificate. Never substitute one value for the other without comparing the actual certificates in the protected release console.

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

The `e2e-test` EAS profile produces an Android APK and iOS simulator `.app` without distribution credentials. The manual workflow at `.eas/workflows/release-hermes-smoke.yml` builds both artifacts with the explicitly configured Hermes engine and runs privacy-safe Maestro journeys without uploading screen recordings:

```powershell
npx eas workflow:run .eas/workflows/release-hermes-smoke.yml
```

Run this from the linked, protected Expo project with its `preview` environment configured. The source workflow follows Expo's [EAS Maestro E2E pattern](https://docs.expo.dev/eas/workflows/examples/e2e-tests/) and [pre-packaged Maestro job contract](https://docs.expo.dev/eas/workflows/pre-packaged-jobs/). A successful cloud run is required evidence; merely parsing these YAML files locally is not a passing test. The guarded production workflow also runs a dedicated Android coordinator attendance journey against the unsigned `e2e-test` artifact: it exercises the real readiness-gated scan callback, durable offline queue across process death, reconnect/drain/server checkpoint, duplicate suppression, and Scan Issues route. The QR entry seam is compiled only into that preview artifact and production validation requires it to be explicitly disabled. Emulator evidence does not replace store-signed physical-device tests for camera optics, links, push, app attestation, storage cleanup, background execution, performance, or accessibility. See `.maestro/README.md` for the protected fixture contract and limitations.

## Native projects and Android builds

Generate native projects after changing app configuration or native dependencies:

```powershell
npm run native:sync
```

For a local Android release verification build, first export the real public production configuration:

```powershell
$env:JAVA_HOME='C:\Program Files\Java\jdk-17'
$env:NODE_ENV='production'
$env:EXPO_PUBLIC_API_URL='https://tech.gctravels.com/api/v1'
$env:EXPO_PUBLIC_APP_ENV='production'
$env:EXPO_PUBLIC_DEMO_MODE='false'
$env:EXPO_PUBLIC_EAS_PROJECT_ID='<real Expo project UUID>'
$env:EXPO_PUBLIC_EXPO_OWNER='<real Expo account>'
$env:EXPO_PUBLIC_UPDATES_URL="https://u.expo.dev/$env:EXPO_PUBLIC_EAS_PROJECT_ID"
$env:EXPO_UPDATES_CODE_SIGNING_CERTIFICATE='C:\protected\updates\certificate.pem'
$env:GOOGLE_SERVICES_JSON='C:\protected\firebase\google-services.json'
$env:GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS='<production SHA-256 fingerprint>'
$env:GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS='<approved EAS upload/distribution SHA-256 fingerprint>'
npm run release:validate-env
npm run android:release-artifacts
```

The release scripts validate the supported Expo dependency set, production public environment, Firebase package identity, update-signing certificate, and live App Link association before cleanly regenerating the Android project. They serialize Gradle work and reserve up to 4 GB heap/1 GB metaspace. Every local generation, Gradle, staging, staging-verification, and packaging command inherits `NODE_ENV=production`; each evidence CLI also fails closed if invoked directly without it. Every lane passes `-PreactNativeArchitectures=...` directly to Gradle, which has higher precedence than the all-ABI default in generated `gradle.properties`: ARM64 for the physical APK, x86_64 for emulator QA, and all four reviewed ABIs for the store AAB. The EAS APK/AAB profiles use the same explicit project-property form in `android.gradleCommand`; lower-precedence `ORG_GRADLE_PROJECT_reactNativeArchitectures` values are forbidden by the contract tests.

The source-controlled Expo config plugin stamps every cleanly generated Gradle wrapper with Gradle 9.3.1's official binary-distribution SHA-256 and fails if the generated wrapper version or an existing checksum drifts. The staging and packaging verifiers validate the generated wrapper again, so a substituted download fails before release evidence is accepted. Android artifact inspection is pinned to the reviewed Android Build Tools 37.0.0 directory and refuses to fall forward to a newer installed version or combine tools from different directories.

Unverified Gradle outputs are normally:

- `android/app/build/outputs/apk/release/app-release.apk`
- `android/app/build/outputs/bundle/release/app-release.aab`

`android:release-artifacts` performs one clean native generation, then builds the
ARM64 APK, immediately copies it to
`outputs/android-staging/app-release-arm64-v8a.apk`, and
records its hash, package, source version, approved signer, and ABI in an adjacent staging manifest. It
then builds the all-ABI AAB, re-verifies that preserved APK against the staging
manifest, and runs the combined size gate. The ignored `outputs/android-staging`
directory is deliberately outside `android/app/build`, because a later Gradle
APK or AAB build may replace the entire generated output tree. `android:apk` is
the standalone ARM64 physical-device lane.
`android:apk:emulator` is a
separate x86_64 lane for emulator QA and is never the physical sideload or store
artifact. It similarly preserves
`outputs/android-staging/app-release-x86_64.apk` immediately
after assembly. Both APK lanes remain single-ABI. The AAB retains all reviewed ABIs.

Both distribution outputs must pass `npm run release:verify-android-size`; the current
four-ABI APK observation is explicitly over budget and is not an acceptable
release baseline. The signed-artifact verifiers repeat the size gate, require
exactly ARM64 in the APK and all four reviewed ABIs in the AAB, and record those
ABIs in the exclusive-created receipt. See `../docs/MOBILE_ANDROID_BINARY_SIZE_POLICY.md`
for the machine-enforced ceilings and evidence boundary.

Configure a protected production upload keystore or EAS credentials before distribution. Do not ship a locally debug-signed artifact as production. `npm run release:verify-android-apk -- <apk> <new-receipt.json> <EAS-build-UUID> <40-or-64-character-Git-hash> <40-or-64-character-EAS-fingerprint-hash> <arm64-v8a|x86_64> <EAS-app-version> <EAS-build-version>` fails closed on debug, unsigned, v1-only, multi-signer, wrong-package, wrong-version-name, EAS build-version mismatch, wrong-ABI, oversized, unapproved-signer, malformed provenance, or a checked-out `HEAD` that differs from EAS build metadata. `npm run release:verify-android-aab -- <aab> <new-receipt.json> <EAS-build-UUID> <Git-hash> <EAS-fingerprint-hash> com.globalconnects.groupcompanion <EAS-app-version> <EAS-build-version>` applies corresponding full-entry archive-signature, per-module ABI, size, signer, and provenance gates. It accepts Android's normal self-signed upload certificate only when its exact SHA-256 fingerprint is approved, while still rejecting unsigned entries, invalid signatures, multiple signer blocks, and unapproved certificates. It additionally re-hashes an independently pinned bundletool 1.18.3 JAR and derives the application ID, version name, and version code from the AAB binary manifest; missing, substituted, or differently versioned bundletool evidence fails release-eligible verification. Both verifiers work only on private exclusive-created snapshots, re-check those snapshots after every external tool completes, and bind the EAS `fingerprint_hash` into schema-v3 receipts. Receipts are created with exclusive-create semantics and contain bounded, evidence-qualified package, version, signer, ABI, size, checksum, build, fingerprint, and source-revision fields. Preserve each binary under the receipt's `canonical_artifact_file` name; that name includes the exact EAS build ID and Git revision rather than a hand-written date or an ambiguous `app-release` label.

For a signed local build from a dirty worktree, create explicitly local-only
evidence instead of fabricating an EAS or release claim. Set
`GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS` to the reviewed distribution
certificate allowlist, keep `NODE_ENV=production` exported for the whole session,
capture the build start instant before Gradle, then
package the finished artifact into an existing ignored evidence directory:

```powershell
$buildStartedAt = (Get-Date).ToUniversalTime().ToString('o')
npm run android:apk:emulator
New-Item -ItemType Directory -Force -Path outputs/apk | Out-Null
npm run release:package-local-android-sideload -- outputs/android-staging/app-release-x86_64.apk outputs/apk x86_64 $buildStartedAt
```

Use `android:apk`, the staged `app-release-arm64-v8a.apk`, and `arm64-v8a` for
the physical-device lane. For the all-ABI local bundle, run `npm run android:aab`,
then explicitly create its ignored evidence directory before packaging:

```powershell
New-Item -ItemType Directory -Force -Path outputs/aab | Out-Null
npm run release:package-local-android-bundle -- android/app/build/outputs/bundle/release/app-release.aab outputs/aab $buildStartedAt
```

The APK packager requires and re-verifies the adjacent lane staging manifest, compares the staged, temporary, and final hashes, and creates a canonical copy with an adjacent `.receipt.json` containing
`evidence_level=local_signed_sideload`, exact package/version/ABI/hash/size/signer,
Git HEAD and dirty state, a deterministic manifest of Git-visible mobile source,
explicit secret/output exclusions, a separate complete secret-safe hash manifest of Android native build inputs, build timestamp, and tool versions. It
sets `release_eligible=false`, never emits an EAS build ID, requires the observed
signer to be in the approved distribution fingerprint set, and refuses to overwrite prior evidence.
It verifies the final canonical copy itself and rejects an APK whose modification
time predates the caller-captured build start.

The local AAB packager likewise uses exclusive temporary and final copies and final
re-verification, requires cryptographic coverage of every archive entry, exactly
one JAR signer block from an approved
distribution certificate, enforces all four reviewed ABIs independently for
every bundle module containing native code, and records the source, temporary,
and final checksum. If the exact pinned bundletool is available, it records
binary-derived package and version fields alongside the checked-out-source
expectations. Otherwise it retains only `expected_*` package/version fields,
labels the parser limitation, and remains `release_eligible=false`.

This receipt is deliberately a post-build local source association, not a
source-to-build attestation. The source manifest is captured after Gradle and
excludes secret-bearing environment files. Generated Android inputs are bound
separately: every file under `android/` that can affect a build is hashed, including
app sources, Gradle files and wrapper inputs, ProGuard rules, generated Google
services selection, and secret-checked `gradle.properties` and `sentry.properties`.
Generated outputs and caches, local SDK paths, keystores, and other signing
credentials are excluded. The generated `android/app/google-services.json` project selector is also
represented only by path, byte count, and SHA-256; its contents are never written
to evidence. `local.properties`, `.gradle`, build outputs, and keystores remain
excluded. The staging manifest and final APK/AAB receipts carry that native
snapshot plus a secret-safe build-configuration fingerprint. That fingerprint
stores only allowlisted input names, availability/state, and hashes for every
reviewed embedded or build-affecting input: app/runtime modes, API and offline-lease
identity, integrity and realtime switches, Expo project identity, Updates,
Google services, Sentry provider identity, Face Liveness selection, Node, and EAS
profile. The Sentry auth token is reduced to a fixed presence marker; its value is
never stored or hashed into evidence. The fingerprint deliberately records configuration observed at evidence time and does
not claim that deferred values are correct or that they were attested from the
binary. The receipt must not be used to claim that the APK was reproducibly built from that snapshot;
production release provenance remains tied to the exact EAS build ID and Git
revision verified by the protected workflow.

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

The guarded production workflow must be started from an immutable remote revision,
never from an implicit local upload. Resolve and review the full 40- or 64-character
commit hash, then pass it explicitly:

```powershell
$fullCommit = (git rev-parse HEAD).Trim()
npx eas workflow:run .eas/workflows/production-release.yml --ref $fullCommit
```

`cli.requireCommit=true` rejects an uncommitted local source state. The custom
verification jobs deliberately use the `preview` EAS environment and then launch
the checked-out Node verifier with an empty environment plus only the public
distribution-certificate fingerprint and required toolchain paths. Configure
`GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS` in preview as the same reviewed,
non-secret fingerprint allowlist used for verification; do not copy production
credentials, provider tokens, signing material, or submission secrets into preview.

Run the matching `release:preflight-ios` gate before a production iOS EAS build. Protected CI/CD should make these preflight commands mandatory rather than invoking a production EAS profile directly.

`production-apk` is the ARM64-only physical-device internal-testing variant. `production-emulator-apk` is the separately bound x86_64 signed emulator variant used by the guarded public-shell Maestro job. All production profiles use `cli.appVersionSource=local`, require committed source with `cli.requireCommit=true`, inherit the explicitly checked-in version, keep `autoIncrement=false`, and use protected EAS Android credentials; a remote counter must never silently diverge from `app.config.ts`. `production` produces the four-ABI Play Store AAB. The repository contract tests reject any profile if its architecture, committed-source, or version-source policy drifts, and the receipt verifiers independently read package/ABI/version metadata from private snapshots of the exact downloaded binaries. A profile definition does not prove that credentials exist or that a build is distribution-signed. The manual `.eas/workflows/production-release.yml` workflow pins the reviewed EAS SDK 57 image and Node 20.19.4, requires `--ref <full-commit-sha>`, and binds functional tests, checked-out `HEAD`, EAS source fingerprint, signer/ABI/size/binary-version verification, checksum receipts, approval, and submission to the exact upstream EAS build IDs; the final submission cannot run before the exact AAB receipt and human approval. A successful cloud run and preserved receipts are required release evidence. The `fingerprint` OTA runtime policy prevents updates built against a different native dependency/configuration fingerprint from reaching an incompatible binary.

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

- Passport, visa, ticket, and other document-preview routes acquire a shared native screen-capture protection lease and render an opaque privacy cover whenever the app is inactive or backgrounded. Ordinary itinerary, profile, and operational screens remain capturable. Telemetry rejects screenshot attachments, app logs remain metadata-only, and notification bodies contain no document details.
- A positive root/jailbreak signal disables offline document download and viewing while itinerary/emergency features remain usable. Detection is cached, experimental, and defense-in-depth—not proof a device is trustworthy. Detection errors produce an `unknown` result and do not crash the app.
- Document bytes require a fresh authorization grant and `X-GC-Download-Token`; raw storage URLs are never stored.
- Pending legacy document metadata is visible but cannot be downloaded until the server has verified its size and SHA-256.
- Interrupted metadata pagination never replaces the last complete local snapshot.
- Attendance scans and incident reports are committed to SQLCipher with UUID idempotency keys before network submission.
- Interrupted responses retain only independently authenticated encrypted frames in app-private storage and resume from the exact verified byte with one open-ended HTTP range. Every segment must match the signed total size and exact `Content-Range`; final plaintext size and SHA-256 are verified before the immutable ciphertext is registered. No plaintext download staging is persisted. A process kill inside one partially written filesystem frame discards that staging file and restarts safely; completed frames resume normally.

Before production, verify backup/restore behavior, rooted-device policy wording, lock-screen redaction, universal/app links, notification credentials, retention windows, and device/session revocation on physical Android and iOS devices.
