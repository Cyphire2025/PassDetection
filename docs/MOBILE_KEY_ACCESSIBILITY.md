# Mobile key accessibility policy

## Scope and security objective

Group Companion stores every durable credential or encryption key through the
single policy in `mobile/src/core/storage/secure-store-policy.ts`. Call sites do
not choose Keychain accessibility, Android aliases, or biometric behavior.

The policy has two tiers:

| Tier | Values | iOS protection | Android protection | Why it is available or unavailable in background |
| --- | --- | --- | --- | --- |
| Unlocked only | AES document-vault key; signed offline-authorization lease and trusted-time anchor; App Attest key identifier/registration marker | `WHEN_UNLOCKED_THIS_DEVICE_ONLY` under the versioned `gc.v2.unlocked-only` service | AES-256-GCM ciphertext in the generated `GCUnlockedDeviceStore`; API 35+ wrapping keys use Android Keystore `setUnlockedDeviceRequired(true)`; API 26-34 use a Keystore wrapping key plus native pre/post `UserManager.isUserUnlocked` and `KeyguardManager.isDeviceLocked` checks | Document decryption, offline shell authorization, and risk-tiered attestation issuance are foreground operations. Reads and writes also fail closed unless React Native reports the app active. Blob hydration waits for foreground; metadata synchronization remains independent. |
| Background after first unlock | Refresh token; SQLCipher database key; installation identity; active account and namespace inventory; selected trip; notification-response dedupe; push-registration digest; database-health and cleanup markers | `AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY` under the versioned `gc.v2.background-after-first-unlock` service | Expo SecureStore's device-bound Android Keystore storage | Native background reconciliation needs the refresh token, account identity, selected-trip priority, SQLCipher metadata database, cleanup fence, and bounded delivery/dedupe markers. These values never migrate to another device. |

The database key is a deliberate exception, not a claim that database content
is low sensitivity. The present architecture stores synchronized metadata and
the offline identity in one SQLCipher database; background reconciliation
cannot open that database without its key. Splitting foreground PII into a
second unlocked-only database is a larger schema and lifecycle project and is
not silently represented as part of this bounded change.

## Platform behavior and biometric decision

On iOS, `keychainAccessible` maps to the native Keychain data-protection class.
The unlocked-only tier therefore becomes unavailable when the device locks and
after reboot until the user unlocks. The after-first-unlock tier is the Apple
policy intended for required background access and remains unavailable before
the first unlock after reboot.

Expo SecureStore does not apply `keychainAccessible` on Android. A tracked Expo
config plugin therefore generates and registers `GCUnlockedDeviceStore` during
every Android prebuild. Unlocked-only values are stored as authenticated
AES-256-GCM ciphertext in a non-exported app-private preference file; the
wrapping key remains non-exportable in Android Keystore. The storage key name
and protection format are authenticated as additional data, values and key
names are bounded, corrupt or missing-key state fails closed, and deletion
remains available while locked for revocation and cleanup recovery. The
TypeScript backend always performs the native read first, copies an existing
Expo value into native storage before removing either old copy, and refuses to
return a value until every weaker duplicate is gone.

Android behavior is deliberately API-gated:

| Android API | Enforcement | Compatibility and evidence boundary |
| --- | --- | --- |
| 35+ (Android 15+) | The AES wrapping key is generated with `setUnlockedDeviceRequired(true)`. Keystore cryptographically rejects key use while the device is locked; native user-unlocked/device-locked checks run before and after encryption or decryption as defense in depth. | An OS upgrade from API 26-34 rewraps compatibility ciphertext under a distinct API-35 key before returning plaintext. Source tests and release Kotlin compilation prove configuration; a physical locked-device and reboot test is still required for each release/OEM matrix. |
| 28-34 (Android 9-14) | A non-exportable Keystore AES key plus native `UserManager.isUserUnlocked` and `KeyguardManager.isDeviceLocked` pre/post checks. | Android documents defects in `setUnlockedDeviceRequired` before Android 15 and recommends using the flag only on Android 15+. The compatibility path avoids those key-loss/no-secure-lock/work-profile defects, but its lock boundary is an application/native guard rather than a cryptographic key-use restriction. |
| 26-27 (Android 8-8.1) | The same Keystore AES wrapping plus native pre/post lock-state checks. | The Keystore unlocked-device-required option does not exist. This is the strongest compatibility-safe design without forcing biometric enrollment or dropping supported offline devices. |

The API decision follows Android's official
[`KeyGenParameterSpec.Builder`](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUnlockedDeviceRequired(boolean))
contract. Android also documents that API 31+ can cryptographically
super-encrypt unlocked-device-required keys while locked in the
[Keystore feature matrix](https://source.android.com/docs/security/features/keystore/features),
but the builder's compatibility warning remains authoritative for choosing API
35 as this application's strict cutoff. Credential-encrypted storage alone is
not an ordinary relock control: Android's
[Direct Boot guidance](https://developer.android.com/privacy-and-security/direct-boot)
defines it as unavailable only until the first unlock following reboot.

`requireAuthentication` is intentionally **not** enabled. In the installed Expo
implementation it means biometric-bound keys: Android requires authentication
for reads and writes, iOS uses the current biometric set, values can become
unreadable when enrollment changes, unsupported/non-enrolled devices cannot
store them, and the current application configuration does not request Face ID
permission. Enabling it would turn routine lease rotation or document-key use
into biometric prompts and would break headless work and legitimate offline use
on devices without biometrics. User-presence protection can be added only as an
explicit product flow with recovery, enrollment-change, accessibility, and MDM
requirements—not as a transparent storage flag.

## Native background contract

Native background bootstrap passes `execution: 'native-background'`. It does
not read the unlocked-only offline lease. It performs the online refresh using
the after-first-unlock refresh token and database key, then synchronizes
metadata. A lease returned by a refresh while the app is not active is verified
but not persisted; the prior lease remains bounded by its signed expiry, and a
later foreground refresh stores the current lease under the unlocked-only tier.
This avoids weakening lease storage merely to satisfy an opportunistic
background task.

Background execution remains best effort. A task before the first unlock after
reboot, a native Keychain/Keystore rejection, expiry, cancellation, or OS
termination fails cleanly and retries through foreground/cursor reconciliation.

## Compatibility migration

Existing `gc.v1` values were written under Expo's default service. Changing an
iOS item's accessibility option during an update does not reliably change the
existing item's data-protection class, so the application uses new versioned
services and migrates every value as follows:

1. Read the versioned policy service and the legacy default service.
2. If only the legacy value exists, copy it to the correct versioned service.
3. Delete the legacy value only after the versioned write succeeds.
4. If both exist after a crash, remove the legacy duplicate before returning
   the hardened value.
5. If the weaker duplicate cannot be removed, fail closed and retry later.
6. Logout, namespace purge, fresh-install reset, and authentication cleanup
   independently attempt both services so one native failure cannot skip the
   other keys.

On Android, steps 1-5 target the native store for unlocked-only material. A
native lock check succeeds before either Expo copy is inspected, the native
write completes before the old policy/default services are deleted, and a
failed duplicate deletion rejects the operation so a later call retries. API
35+ also recognizes the distinct API 26-34 ciphertext format and atomically
rewraps it under the strict key. Missing Keystore aliases with surviving
ciphertext and AES-GCM authentication failures never trigger silent key
replacement.

The ordering prevents process death from deleting the only usable key. App
downgrades across this security migration are not supported because an older
binary does not know the versioned services.

## Required physical-device and release gates

Automated TypeScript tests prove the exhaustive mapping, options, migration
ordering, duplicate cleanup, failure behavior, and native-background routing.
They do not prove native lock-state enforcement. Release evidence must include:

- iOS foreground vault/document open and offline shell while unlocked, followed
  by locked-device denial without a prompt or plaintext output;
- iOS background metadata refresh while locked after a normal first unlock;
- iOS reboot-before-first-unlock denial, then recovery after unlock;
- Android locked-device/headless denial for vault and offline shell, plus
  successful metadata reconciliation where the OS schedules it;
- Android/iOS process kill during each migration phase and successful retry with
  no surviving legacy duplicate;
- device passcode removal/change, biometric enrollment addition/removal, and
  app upgrade/reinstall/backup-restore behavior;
- devices with no passcode, no biometrics, accessibility services, work
  profiles, and supported Android API levels/OEMs;
- logout, account switch, explicit cleanup, and fresh-install reset while
  locked, including retry after a simulated native storage outage;
- API 35+ proof that vault/offline-authorization reads fail after ordinary
  relock and before first unlock after reboot, then recover after unlock;
- API 26-34 proof that the native compatibility guard denies the same relock
  and reboot cases on each supported OEM/work-profile matrix, with its
  non-cryptographic time-of-check/time-of-use residual explicitly accepted.

No automated result should be labeled as physical Android/iOS lock, reboot,
biometric, MDM, backup/restore, or production-signing proof.
