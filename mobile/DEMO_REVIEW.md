# Standalone Google Play review demo

The explicit standalone-demo build embeds sample trip information and documents, uses fixed local sign-in checks, and cannot connect to the live dashboard. Android Internet permission is removed. OTA updates, live synchronization, crash reporting transport, push registration, real OTP delivery, and face-liveness services are disabled in this build.

Package: `com.globalconnects.groupcompanion`. Version: `1.0.10`, Android version code `11`.

## Review access

| Role | Identifier | Password or code |
| --- | --- | --- |
| Coordinator | `coordinator@gmail.com` | `Test@12345` |
| Client Manager | `clientmanager@gmail.com` | `Test@12345` |
| Passenger | `+919876543219` | OTP `123456` |

These values were recovered from the **Explain Google Play app setup** chat. That chat could not verify that every field was saved in Play Console. They are public sample accounts and have no authority on the live dashboard.

Passenger access uses the passenger button, the fixed mobile number, and the reusable six-digit code. Staff access uses the staff button and the matching email/password. No SMS, WhatsApp message, or network connection is needed. Incorrect values are rejected.

The passenger can inspect a sample trip, itinerary, announcements, personal/common PDF documents, room and meal information, and a sample QR. The manager can inspect two sample groups, readiness, the 14-person roster, passenger details and sample document previews, and create/close local attendance activities. The coordinator can inspect a sample roster and activity, try QR attendance with the camera or the **Sample scan** buttons, and submit a sample incident. Repeat attendance scans do not count a passenger twice.

The passenger QR represents **Demo Passenger** in the coordinator sample roster. All changes stay within the current device and role. Manager and coordinator accounts have separate sample workspaces; their changes do not synchronize between accounts or devices. Signing in again resets that role's sample data. An ordinary app restart retains the current local workspace.

## Build

Run from `mobile` in PowerShell:

```powershell
./scripts/build-standalone-demo.ps1 -QaOnly
```

This creates a release-mode APK with embedded JavaScript for the x86_64 emulator, signed with the Android development key. The output is clearly named `GC-Demo-1.0.10-code11-Emulator-QA.apk`. It does not need Metro. This key cannot update the existing Play app.

When the upload key is unavailable, the complete bundle can be prepared for later signing:

```powershell
./scripts/build-standalone-demo.ps1 -PrepareUnsignedBundle
```

This builds all four Android ABIs and outputs `GC-Demo-1.0.10-code11-UNSIGNED.aab` plus `GC-Demo-1.0.10-code11-Universal-QA.apk`. The temporary QA signature is removed from the copied AAB. **The unsigned AAB cannot be uploaded until it is signed with the existing Play upload key.** The universal APK is for local testing and uses the development key.

Once the original key is available, the prepared AAB can be signed without rebuilding:

```powershell
./scripts/sign-standalone-demo-bundle.ps1 -KeystorePath 'C:/protected/existing-upload-key.jks' -CredentialsPath 'C:/protected/signing-credentials.txt'
```

This checks the key against the previously recorded upload-certificate SHA-256, signs a copy, and verifies the JAR signature. Passwords pass through process environment variables and are never printed or placed in command arguments. The unsigned original is preserved. Confirm that Play Console still lists that upload certificate if the account's key has been reset since the earlier release.

For the Play update, supply the existing upload/release keystore and its protected credentials file:

```powershell
./scripts/build-standalone-demo.ps1 -KeystorePath 'C:/protected/existing-upload-key.jks' -CredentialsPath 'C:/protected/signing-credentials.txt'
```

The credentials file must contain `Keystore password:`, `Key alias:`, and `Key password:` fields. Values are read only into the build process and are never printed or stored in source. The signed APK and AAB are written to `mobile/outputs/standalone-demo/`. Build variables are restored after completion, and `.env.local` is ignored for this build.

The recorded previous credentials location is `C:/Users/nipun/Documents/GroupCompanion-Release-Credentials`; the files were absent on this PC during this task. Do not replace the existing Play upload key with a newly generated key without following the required Play upload-key recovery process.

## Pixel 10 Pro emulator

The official Android SDK device profile `pixel_10_pro` is configured as `GC_Pixel_10_Pro`, running the Android 16 / API 36 Google APIs x86_64 system image with a 1280 × 2856 display. The x86_64 virtual device models the Pixel display/profile; it does not emulate the physical Pixel Tensor processor. A **Google Pixel 10 Pro Emulator** desktop shortcut launches it.

The SDK is installed at `C:/Users/nipun/AppData/Local/Android/Sdk`. Java 17 is under `C:/Users/nipun/AppData/Local/GlobalConnect-Android/jdk/`. Android Studio is optional for launching this emulator; the installed SDK command-line tools and shortcut are sufficient.

## Play Console app-access instructions

Use the same three access records above. Explain that the release is an offline demo with bundled sample data, the OTP is reusable, and no external verification or dashboard setup is required. Reviewers can switch roles by signing out and entering the other account. Google Play production access/release approval remains a separate Console decision; this build does not bypass closed-testing requirements.

No Play Console submission is performed by the build script.
