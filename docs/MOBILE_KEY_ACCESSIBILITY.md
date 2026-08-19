# Mobile key accessibility policy

## Scope and security objective

Group Companion stores every durable credential or encryption key through the
single policy in `mobile/src/core/storage/secure-store-policy.ts`. Call sites do
not choose Keychain accessibility, Android aliases, or biometric behavior.

The policy has two tiers:

| Tier | Values | iOS protection | Why it is available or unavailable in background |
| --- | --- | --- | --- |
| Unlocked only | AES document-vault key; signed offline-authorization lease and trusted-time anchor; App Attest key identifier/registration marker | `WHEN_UNLOCKED_THIS_DEVICE_ONLY` under the versioned `gc.v2.unlocked-only` service | Document decryption, offline shell authorization, and risk-tiered attestation issuance are foreground operations. Reads and writes also fail closed unless React Native reports the app active. Blob hydration waits for foreground; metadata synchronization remains independent. |
| Background after first unlock | Refresh token; SQLCipher database key; installation identity; active account and namespace inventory; selected trip; notification-response dedupe; push-registration digest; database-health and cleanup markers | `AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY` under the versioned `gc.v2.background-after-first-unlock` service | Native background reconciliation needs the refresh token, account identity, selected-trip priority, SQLCipher metadata database, cleanup fence, and bounded delivery/dedupe markers. These values never migrate to another device. |

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

Expo SecureStore does not apply `keychainAccessible` on Android. Versioned
`keychainService` values still isolate the two tiers under separate Android
Keystore aliases, and the application-state guard prevents normal application
code from using vault/offline-authorization material in a headless/background
window. This is defense in depth, not hardware proof that the Android device is
unlocked. Closing that residual gap requires a reviewed native Keystore module
using an unlocked-device restriction on supported Android versions, together
with the compatibility matrix below; it cannot be truthfully proven from
TypeScript tests.

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
- confirmation that Android's residual hardware lock-state gap is either
  accepted in the threat model or closed by a separately reviewed native module
  before F-19 is marked complete.

No automated result should be labeled as physical Android/iOS lock, reboot,
biometric, MDM, backup/restore, or production-signing proof.
