# Mobile offline authorization leases

## Purpose and boundary

The encrypted account database is a cache, not proof that a person is still
authorized. Group Companion therefore requires a short-lived, backend-signed
authorization lease before it renders a cached non-demo account offline. This
is separate from online access and refresh tokens: online API authorization is
still controlled by the existing bearer-token and device-session checks.

The design keeps cache-first startup. The app reads SecureStore and the local
SQLCipher account database before attempting the network, but it releases the
offline shell only after independently verifying the cached lease.

## Signed profile

The lease is a compact three-segment JWS-style value:

```
base64url(canonical header).base64url(canonical claims).base64url(signature)
```

Only unpadded, canonical base64url and canonical ASCII JSON are accepted. The
format is deliberately narrower than a general JWT implementation.

The only accepted header is:

| Field | Required value |
| --- | --- |
| `alg` | `EdDSA` |
| `typ` | `GC-OFFLINE-AUTH` |
| `v` | `1` |
| `kid` | A bounded key identifier in the pinned verification set |

The claims bind the grant to all of the following:

- installation ID;
- device-session ID and session generation;
- agency, stable account, principal ID, and principal role;
- passenger record ID for passenger sessions;
- server-side principal/claim generation when that model exposes one;
- selected group-access generation when applicable;
- issuer, audience, unique lease ID, format version, server time, strict
  not-before time, issue time, and expiry.

The payload intentionally contains no display name, email address, telephone
number, online access token, refresh token, device name, or signing secret.
Those values are neither necessary for authorization nor appropriate for a
portable signed object.

The backend signs with Ed25519. The app contains public verification keys only
and verifies with strict RFC 8032 point decoding (`zip215: false`). A symmetric
offline secret is not shipped to clients because any extracted client secret
would let an attacker forge authorization grants.

## Configuration

Backend secrets and policy:

| Variable | Purpose |
| --- | --- |
| `MOBILE_OFFLINE_LEASE_ACTIVE_KID` | Key ID used for new signatures |
| `MOBILE_OFFLINE_LEASE_PRIVATE_KEY_B64` | Unpadded base64url PKCS8 Ed25519 private key |
| `MOBILE_OFFLINE_LEASE_PUBLIC_KEYS_JSON` | Bounded key-ID-to-raw-public-key map used to validate rotation configuration |
| `MOBILE_OFFLINE_LEASE_ISSUER` | Exact issuer pinned by the app |
| `MOBILE_OFFLINE_LEASE_AUDIENCE` | Exact audience pinned by the app |
| `MOBILE_OFFLINE_LEASE_TTL_MINUTES` | Lease lifetime, 5 to 1,440 minutes |

The backend refuses to start in staging or production when mobile support is
enabled and the key set is absent, malformed, oversized, does not contain the
active key, or does not match the configured private key. Store the private key
in the deployment secret manager. Never print it, return it from an endpoint,
put it in an Expo variable, or commit it.

Mobile public configuration:

| Variable | Purpose |
| --- | --- |
| `EXPO_PUBLIC_OFFLINE_LEASE_ISSUER` | Exact expected issuer |
| `EXPO_PUBLIC_OFFLINE_LEASE_AUDIENCE` | Exact expected audience |
| `EXPO_PUBLIC_OFFLINE_LEASE_PUBLIC_KEYS_JSON` | Public Ed25519 verification keys |

The mobile key JSON must be canonical: key IDs sorted lexicographically, no
whitespace, one to five entries, and every value an unpadded base64url encoding
of exactly 32 raw Ed25519 public-key bytes. Production release validation fails
closed when this contract is not met.

Generate production keys only in the controlled deployment environment or key
management workflow. Repository tests use deterministic test-only key material;
it must never be promoted to a deployed environment.

## Rotation runbook

Rotation is an overlap operation, not an instantaneous replacement:

1. Generate the next Ed25519 key pair in the protected key-management
   environment. Keep the private key out of source control and build logs.
2. Add the next public key to the mobile verification set while retaining the
   current public key. Release both Android and iOS builds and enforce the
   required minimum app version/adoption policy before changing the signer.
3. Configure the backend verification set with both public keys. Keep signing
   with the current key and confirm staging issuance and physical-device
   verification.
4. Change the backend active key ID and private key together. New leases use the
   next key; already-issued leases remain valid under the retained old public
   key.
5. Wait longer than the maximum configured lease TTL, plus deployment and clock
   safety margin, after the last old-key signature. Confirm that supported app
   builds all contain the new public key.
6. Remove the retired public key from mobile and backend configurations in a
   coordinated release. Keep the total set at five keys or fewer.

If an active private key is suspected to be compromised, revoke server device
sessions, stop signing with that key, shorten the transition according to the
incident policy, and force affected clients online/update. Removing a public
key immediately also invalidates still-unexpired leases and intentionally
removes offline access.

## Endpoint and rollout contract

Every shared mobile session issuance path returns
`offline_authorization_lease`, including credential login, OTP/claim
authentication, activation, forced-password change, refresh, and passenger
trip switch. Refresh and passenger trip switch also require the raw
`installation_id`; the backend compares its protected lookup hash to the device
session before rotating credentials or signing a lease.

This is a lockstep protocol change. Deploy the signing configuration and
backend contract, then release clients that send installation identity and
require the signed response. Do not silently make the lease optional for older
clients. Use the normal minimum-version rollout control if backward
compatibility is temporarily required.

## Trusted-time behavior

On an online response, the app verifies the signature and every identity field,
then anchors the signed server time in account-scoped SecureStore. It persists:

- the compact signed lease;
- the highest trusted server time observed; and
- the device wall-clock reading at that anchor.

Within one running process, elapsed time comes from the monotonic performance
clock. Across a process restart, the app advances the persisted server-time
high-water mark by the wall-clock delta. It rejects malformed records, unknown
keys or algorithms, signature failures, swapped identities/sessions/
installations, not-yet-valid records, expiration, wall-clock rollback, and
monotonic-clock rollback. The updated high-water anchor is persisted before the
offline shell is published. A runtime timer removes an active offline shell at
the signed expiry boundary.

Logout, account purge, fresh-install reset, and authentication cleanup remove
the account-scoped lease. Lease verification never queries the network and does
not add a network round trip to cache-first startup.

## Fundamental limitations

These constraints cannot be eliminated by application code alone:

- Disconnected revocation is bounded by lease expiry. A server-side account,
  group, claim, or session revocation cannot reach a device with no network.
  Choose the TTL according to the business risk; shorter TTLs reduce the
  revocation window but require more frequent online renewal.
- A phone does not expose a universally trusted secure clock to a normal Expo
  application. The monotonic clock protects elapsed time only while the
  process/boot context remains available. After reboot or powered-off time, the
  app must derive elapsed time from the mutable wall clock. The persisted
  high-water mark detects rollback relative to its last anchor, but a powerful
  device attacker can freeze or manipulate time across repeated reboots. Strong
  assurance requires online time, platform hardware attestation, or a dedicated
  trusted-time service and a product policy that denies offline access when it
  is unavailable.
- JavaScript timers may be delayed while iOS or Android suspends the process.
  The timer closes the shell when JavaScript resumes; every cold/resume
  authorization path must still re-run the signed-time check.
- Rooted/jailbroken devices, runtime instrumentation, compromised OS keychains,
  and modified application binaries are outside the protection boundary of a
  public-key verifier. Device-integrity attestation and managed-device policy
  are separate hardening layers, not replacements for lease verification.
- Restoring an encrypted database without its installation-bound SecureStore
  identity and lease cannot restore authorization. This is intentional.

## Release evidence required

Before production rollout, retain evidence for:

- backend unit/integration tests covering issuance, refresh binding, switch
  binding, key mismatch, rotation bounds, claim privacy, and staging/production
  startup failure;
- mobile tests covering canonical parsing, strict Ed25519 verification,
  tampering, unknown keys/algorithms, every identity swap, future/expired
  grants, time rollback, high-water persistence, and cleanup;
- TypeScript, ESLint, Python formatting/lint/type checks, and release-environment
  validation;
- physical Android Hermes and iOS tests for cold start, process death, reboot,
  clock rollback, long suspension, offline expiry, logout, account switch, and
  key rotation;
- a staged rollout confirming that backend and both native client contracts are
  compatible before the minimum supported version is raised.

Automated tests cannot establish secure key custody, real device clock
behavior, platform suspension timing, production secret injection, or
disconnected revocation latency. Record those as explicit operational and
physical-device gates rather than claiming them from unit-test results.
