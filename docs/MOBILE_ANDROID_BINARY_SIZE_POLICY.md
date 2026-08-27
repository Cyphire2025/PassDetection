# Mobile Android binary-size policy

## Release gate

The Android release compile lane must produce both artifacts and pass the
repository-owned size verifier before it can be considered a successful CI
build:

- ARM64 installable verification APK: at most 120 MiB.
- Android App Bundle: at most 150 MiB.

The AAB is the intended store input because the store can deliver ABI and
resource splits. An ARM64 APK is controlled sideload and physical-device
verification evidence only; it is not the preferred distribution artifact. Store-reported
download size, installed size, cold start, and peak RSS remain separate release
measurements because an AAB file size does not prove what a device receives.

The gate is implemented by
`mobile/scripts/verify-android-binary-size.mjs` and runs immediately after the
clean ARM64 `assembleRelease` lane has copied and verified a lane-specific APK,
and after the all-ABI `bundleRelease` lane re-verifies that staged APK. Missing
artifacts, changed staging hashes, ABI drift, invalid sizes, or a single artifact
above its reviewed ceiling fail the Android release job.

The guarded cloud release must be started as
`eas workflow:run .eas/workflows/production-release.yml --ref <full-commit-sha>`.
An implicit local project upload is not release provenance. `cli.requireCommit=true`
rejects uncommitted source, and the downloaded APK/AAB verifiers additionally
require checked-out `HEAD` to equal the build job's Git hash and bind the EAS
`fingerprint_hash` into each receipt. The AAB gate derives package and version
from the binary with the exact checksum-pinned bundletool 1.18.3 JAR; absence or
substitution of that parser fails release-eligible verification.

## Current local evidence boundary

The locally observed four-ABI release APK is 180,750,134 bytes (172.38 MiB).
That exceeds the 120 MiB budget by 54,921,014 bytes and is explicitly not an
acceptable baseline. The exact machine-readable verifier reports the precise
overage; this document intentionally avoids treating a local artifact as a
source-to-build attestation.

No local AAB was present during the 2026-08-25 review. A later debug assemble
attempt exceeded its bounded ten-minute command timeout. Even though a debug
APK appeared on disk, that timeout is neither a successful build result nor
release evidence. Only a command that returns success and then passes the size,
signature, package, provenance, and device gates may be cited as verified.

## Required remediation

1. Keep production distribution on an AAB so Play can deliver ABI/resource
   splits.
2. For controlled sideloading, build and review the ARM64 release APK rather than
   distributing the four-ABI artifact. The release profile and artifact receipt
   validators reject architecture drift.
3. Use a separately named x86_64 APK only for emulator QA. Its receipt must bind
   the x86_64 target explicitly; it is not the physical-device sideload or Play
   Store artifact.
4. Inspect native-library contribution by ABI and remove unused native modules
   only after route and workflow parity tests.
5. Resize or replace oversized decorative raster assets while retaining visual
   fidelity and accessibility.
6. Record binary-size diffs on every release change; do not raise the ceilings
   merely to make a failing artifact pass.
