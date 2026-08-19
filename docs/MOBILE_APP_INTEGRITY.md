# Mobile app integrity and high-risk action attestation

## Status and security boundary

The repository now contains a feature-flagged, server-verified integrity boundary for
mobile document-download authorization. It is disabled by default and does not change
the existing workflow until an operator deliberately selects `monitor` or `enforce`.

This implementation does **not** accept a boolean, decoded payload, device verdict, or
other trust decision from the mobile client. The client can only return an opaque
platform proof. The backend owns the one-time challenge, request binding, replay
consumption, provider call, verdict policy, and final allow/deny decision.

Current provider readiness differs only in the external release evidence that remains:

- Android has a real server adapter for Google Play Integrity standard requests. It
  obtains an Application Default Credentials access token and sends the opaque token to
  Google's `decodeIntegrityToken` endpoint before evaluating the verdict.
- iOS has the native App Attest key and assertion flow, server key/counter storage, and a
  strict default backend verifier. The verifier delegates Apple's core attestation and
  assertion cryptography to the maintained `pyattest` package, then independently adds
  the bounded wire contract, receipt validation, replay enforcement, and Apple's current
  validation-category/bundle-version policy. Production enforcement still requires a
  signed physical-device exercise in the exact development/distribution environments.

The implementation follows the platform flows described by the
[Expo AppIntegrity API](https://docs.expo.dev/versions/latest/sdk/app-integrity/),
[Google Play Integrity standard requests](https://developer.android.com/google/play/integrity/standard),
Apple's
[server validation overview](https://developer.apple.com/documentation/devicecheck/validating-apps-that-connect-to-your-server)
and
[current attestation-object validation guide](https://developer.apple.com/documentation/devicecheck/attestation-object-validation-guide),
and the maintained
[`pyattest` release](https://pypi.org/project/pyattest/).

## Implemented request flow

### Shared server-owned challenge

1. The already authenticated mobile session requests a challenge and supplies the
   installation identifier, provider, action, and a SHA-256 resource request hash.
2. The backend verifies that the installation belongs to the live account/session and
   that the provider matches the registered platform.
3. The backend creates a fresh random challenge ID and binds it to the agency, account,
   session, installation hash, provider, action, resource request hash, and—on iOS—the
   App Attest key. Raw identifiers are not written to the challenge payload.
4. The complete binding object is SHA-256 hashed into the provider request hash. The
   challenge record is stored with a 30–300 second TTL.
5. Redis consumes the challenge atomically with `GET` plus `DEL`. A replay, an expired
   challenge, a different session/account/install/key, a changed action, or a changed
   resource hash fails before provider verification.

Redis is mandatory in enforcement mode. The bounded in-memory implementation exists
only for tests and explicit single-process development. Redis failure is an availability
failure, never a reason to accept a proof in enforcement mode.

### Android / Play Integrity

1. The app computes the canonical resource hash. For document authorization the exact
   input is:

   ```text
   gc-mobile-integrity-v1\0document_download_authorize\0{group UUID}\0{document UUID}\0{version}
   ```

2. The server returns its derived 43-character provider request hash.
3. `@expo/app-integrity` prepares Google's standard token provider using the public
   Google Cloud project number and requests a token for only that server hash. An
   invalidated provider is prepared and retried once.
4. The protected request returns the opaque token and challenge ID.
5. The backend atomically consumes and validates the challenge, obtains a server access
   token via ADC, and sends `{ "integrityToken": "..." }` to Google's decode endpoint.
6. The backend checks request details before other verdicts: request hash, package name,
   and a bounded timestamp. It then requires:

   - `PLAY_RECOGNIZED`;
   - the configured package name;
   - an intersection with the configured Play signing-certificate SHA-256 digests;
   - the configured device-recognition label, defaulting to
     `MEETS_DEVICE_INTEGRITY`; and
   - `LICENSED` by default.

Google client failures and malformed/unavailable authoritative responses become
provider outages. Token and negative verdicts become rejections. Proofs and access
tokens are never logged.

### iOS / App Attest

1. On a supported iOS device, the app generates a per-account-namespace Secure Enclave
   key. Only its key identifier and local registration state are stored under the
   unlocked-only SecureStore policy.
2. Key registration uses its own server-bound, one-time challenge. The backend
   recomputes the key-registration request hash rather than trusting the submitted hash.
3. The app submits the opaque attestation object. Before any cryptographic verification,
   the backend requires canonical standard Base64, bounded input sizes, exact CBOR
   consumption with no trailing data, the exact App Attest object shape, two bounded DER
   certificates, a bounded receipt, and a P-256 leaf key.
4. `pyattest` verifies the Apple App Attestation trust path, nonce/client-data binding,
   key identifier, App ID/RP ID, initial counter, environment AAGUID, credential ID, and
   attestation public key. The adapter additionally pins the resolved path to the
   package's Apple App Attestation root and independently checks the complete
   authenticator-data and COSE-key shapes.
5. The backend validates the initial Apple fraud receipt as CMS signed data: exactly one
   expected Apple receipt signer, pinned Apple Root CA - G3 trust, certificate-path and
   ECDSA signature verification, and exact receipt bindings for App ID, attestation leaf
   certificate, server challenge, `ATTEST`, environment, creation time, and expiry.
6. Both registration and every assertion require exactly Apple's
   `apple_validation_category_01` and `apple_bundle_version_01` authenticator extensions.
   Their values must match operator allowlists; unexpected, missing, malformed, or
   additional extensions fail closed.
7. The database stores only an HMAC lookup hash for the key identifier, the existing
   installation lookup hash, and a bounded/versioned verification envelope containing
   the ES256/P-256 public key, environment, attested category and bundle version, hashed
   key binding, and receipt digest. It also stores status and the assertion counter. It
   stores no private key, raw key identifier, attestation object, bearer token, phone
   number, passenger data, or document metadata.
8. Each protected action generates an App Attest assertion over the fresh server hash.
   The verifier requires the exact assertion shape, App ID/RP ID, allowed extensions,
   ES256 signature, and a counter strictly greater than the persisted counter. The
   backend locks the key row while verification and counter advancement occur, so two
   concurrent/replayed assertions cannot both succeed.

Apple allows retrying an unavailable attestation service with the same key. The client
therefore preserves an unregistered key for server/provider 5xx failures, while a
non-retryable attestation rejection clears the local key state so a new key can be
generated.

Only the verified receipt digest is retained by the current schema. Persisting the raw
receipt in separately encrypted, access-controlled storage and using Apple's fraud-risk
metric service can add account-abuse signal, but it is an optional risk-engine control;
it is not used as a substitute for local receipt, attestation, assertion, authorization,
or replay verification.

## Rollout modes and user-visible failure policy

| Mode | Challenge/proof work | Unsupported device or provider outage | Invalid/replayed proof |
|---|---|---|---|
| `disabled` | None | Existing workflow continues | Existing workflow continues |
| `monitor` | Attempted | Existing workflow continues; fixed reason code is logged | Existing workflow continues; fixed reason code is logged |
| `enforce` | Required for the protected action | HTTP 503 with bounded `Retry-After` | HTTP 403 with a generic response |

Only document-download authorization is protected in this slice. Authentication,
synchronization, attendance, and read-only metadata APIs are not silently put behind a
new attestation requirement. Additional high-risk operations must be added one at a time
with an explicit canonical request-hash contract and route tests.

The generic 403/503 responses intentionally do not disclose the internal reason code.
Server logs contain only the action, rollout mode, outcome, and a bounded fixed reason;
they contain no account, installation, challenge, key, proof, token, or document value.

## Configuration contract

### Backend

```text
MOBILE_APP_INTEGRITY_MODE=disabled|monitor|enforce
MOBILE_APP_INTEGRITY_CHALLENGE_TTL_SECONDS=120
MOBILE_APP_INTEGRITY_REQUIRE_REDIS=true
MOBILE_APP_INTEGRITY_PROOF_MAX_BYTES=32768

MOBILE_PLAY_INTEGRITY_PACKAGE_NAME=com.globalconnects.groupcompanion
MOBILE_PLAY_INTEGRITY_ALLOWED_CERTIFICATE_DIGESTS_JSON=["base64url-sha256"]
MOBILE_PLAY_INTEGRITY_REQUIRE_LICENSED=true
MOBILE_PLAY_INTEGRITY_REQUIRED_DEVICE_VERDICT=MEETS_DEVICE_INTEGRITY
MOBILE_PLAY_INTEGRITY_TIMEOUT_SECONDS=8

MOBILE_APP_ATTEST_TEAM_ID=ABCDEFGHIJ
MOBILE_APP_ATTEST_BUNDLE_ID=com.globalconnects.groupcompanion
MOBILE_APP_ATTEST_ENVIRONMENT=development|production
MOBILE_APP_ATTEST_ALLOWED_VALIDATION_CATEGORIES_JSON=[4]
MOBILE_APP_ATTEST_ALLOWED_BUNDLE_VERSIONS_JSON=["1"]
MOBILE_APP_ATTEST_IOS27_EXTENSION_ROLLOUT_CONFIRMED=false
```

Production enforcement refuses configuration without Redis, Play certificate digests,
the Apple team ID, the production App Attest environment, and non-empty Apple extension
allowlists. Production validation categories are restricted to Apple's distribution
categories `2`, `4`, and `5`. Category `3` is Apple's development-signing category;
category `1` is an operating-system executable. Both are rejected in production.
Bundle-version entries are exact canonical `CFBundleVersion` values, not
ranges, so an approved release overlap must be listed explicitly and removed after the
rollout. The verifier requires these same allowlists in `monitor` as well as `enforce`;
missing policy is an availability failure, never an implicit allow.

The iOS 27 rollout acknowledgement defaults to `false`. A production backend refuses
to start in `enforce` until an operator explicitly changes it to `true`. Do that only
after an enforced minimum-iOS/minimum-app-version policy or measured adoption window has
made iOS 16.4-26 clients ineligible for the protected action. `monitor` is the safe
migration state: missing extensions produce a fixed rejected outcome for telemetry but
preserve the existing document workflow. `enforce` fails closed and will return the
generic 403 for those older clients; it never silently downgrades the extension check.

The Google credential library is pinned as `google-auth==2.56.3` and loaded only when
Play verification is invoked. The Apple verifier and its security-sensitive direct
dependency set are also pinned
(`pyattest`, `cbor2`, `asn1crypto`, `pyhanko-certvalidator`, `oscrypto`, `uritools`,
`python-jose[cryptography]`, `ecdsa`, and `cryptography`) so a release does not silently
change verification behavior after dependency resolution.

### Mobile/build

```text
EXPO_PUBLIC_APP_INTEGRITY_MODE=disabled|monitor|enforce
EXPO_PUBLIC_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER=123456789012
GC_APP_ATTEST_ENVIRONMENT=development|production
```

The Cloud project number is public provider identity, not a credential. The build-only
App Attest variable selects the signed iOS entitlement and is not exported in the JS
runtime contract. Enabled production builds require the production entitlement. A mode
other than `disabled` without both provider build identities fails configuration
validation.

Backend and mobile modes must be changed together. A mobile `enforce` build cannot make
the server enforce, and a server enforcement rollout will reject an older/disabled
client at the protected action. Use minimum-version controls or a completed adoption
window before server enforcement.

## Required external setup and release gates

### Android gates

- Link the exact Play Console app/package to the intended Google Cloud project.
- Enable Play Integrity and grant the backend service identity only the permission needed
  to decode this app's integrity tokens.
- Provide credentials through the deployment platform's workload identity or protected
  service-account injection so Application Default Credentials succeeds. Never put a
  credential in Expo public environment variables, source control, or the app binary.
- Derive the configured certificate digest from the Play App Signing certificate, encode
  the SHA-256 digest as base64url, and support an overlap list during an approved signing
  rotation.
- Verify a Play-distributed, release-signed AAB on representative physical devices. A
  locally sideloaded/debug build does not prove the production recognition/licensing
  path.
- Confirm server clock synchronization. Timestamp validation deliberately fails closed
  when clocks exceed the challenge window.

### iOS gates

- Confirm the Team ID, exact bundle ID, App Attest capability, provisioning profile, and
  `production` entitlement on the archived binary.
- The reviewed `PyAttestAppleAppAttestVerifier` is the default registry implementation;
  do not replace it with `UnavailableAppleAppAttestVerifier` outside deliberate
  fail-closed tests or incident isolation. Re-review Apple's validation contract and the
  pinned verifier dependency before any protocol/dependency upgrade.
- The receipt path pins Apple's public
  [Apple Root CA - G3](https://www.apple.com/certificateauthority/) trust anchor by its
  SHA-256 fingerprint as well as its certificate bytes. Treat any root rotation as a
  reviewed source/configuration change with old/new overlap evidence; never download a
  trust root dynamically during request verification.
- Confirm the exact validation-category values emitted by development, TestFlight, App
  Store, enterprise, and ad hoc builds that the business intends to permit. Configure
  the smallest corresponding production allowlist and the exact signed
  `CFBundleVersion` values. Never include category `1` in a production allowlist.
- Apple's current extensions are only available on the corresponding newer iOS runtime.
  Before enforcement, adopt an explicit minimum-supported-iOS policy (or complete an
  evidence-based migration window). Otherwise, older but legitimate devices will be
  rejected because the verifier intentionally fails closed when the extensions are
  absent. Keep `MOBILE_APP_ATTEST_IOS27_EXTENSION_ROLLOUT_CONFIRMED=false` until that
  gate is complete; production enforcement cannot start with the default value.
- Exercise key registration, assertion counter advancement, reinstall/key loss, Apple
  outage retry, rejected-key replacement, and concurrent assertion behavior on a
  release-signed physical device. App Attest is not proven by simulator tests.
- Confirm the verifier handles Apple root/intermediate trust updates and environment
  separation without accepting development attestations in production.

### Shared infrastructure and operations gates

- Apply Alembic revision `0081_mobile_app_attest_keys` before enabling iOS monitoring.
- Use highly available Redis shared by every API worker. Alert on challenge-store errors,
  capacity, latency, and eviction; do not use the local fallback in staging/production.
- Add dashboards for fixed outcomes by action/platform/app version: verified, rejected by
  reason, unavailable, and proof missing. No raw proof or identifier may become a metric
  label.
- Establish a baseline in `monitor` for at least one representative release/adoption
  window. Investigate unsupported-device and provider-outage rates before enforcement.
- Load-test challenge issuance, Redis atomic consumption, Google decode latency, database
  key-row contention, and the protected route at the expected concurrency. Unit tests do
  not establish 10,000-user capacity.
- Confirm provider quotas and alert thresholds with headroom for retry/reconnect storms.
- Maintain an emergency rollback to `monitor`/`disabled` through protected deployment
  configuration. A rollback changes availability policy; it must not accept previously
  consumed challenges or weaken ordinary session/document authorization.

## Recommended rollout sequence

1. Deploy the migration and code with both mobile and backend modes `disabled`.
2. Complete Android Cloud/Play credentials and Apple extension allowlists. Prove both
   providers on signed physical devices in every permitted distribution environment.
3. Release a mobile version in `monitor`, then change the backend to `monitor`. Observe a
   full adoption window, outages, unsupported devices, and verdict distribution.
4. Decide the supported device/OS policy and support path from evidence. Do not weaken
   certificate, request-hash, replay, licensing, or session/install checks to improve a
   metric.
5. Ensure the enforcing client has reached the required adoption threshold, then enable
   backend `enforce` for document authorization during a staffed change window.
6. Add other high-risk actions only through separate request-hash versions, threat review,
   monitor evidence, and fail-open/fail-closed availability decisions.

## What this control does not claim

- It raises confidence that a protected request came from a recognized app/device
  instance bound to the current server session. It is not a replacement for account
  authentication, authorization, secure storage, document grants, rate limiting, or
  audit trails.
- It cannot make an already-authorized, fully compromised device harmless. Server-side
  least privilege, short-lived grants, revocation, and anomaly detection still apply.
- It does not prove real provider behavior without credentials, signed binaries, physical
  devices, and provider-console configuration.
- It does not prove throughput, quota, or provider availability at 1,000–10,000 concurrent
  users; that requires a production-like load program and provider quota validation.

## Automated evidence included in the repository

The focused tests cover canonical request hashing, bounded/PII-free challenge records,
account/session/install/key/provider/action/hash substitution, expiry, atomic replay,
rollout modes, outages, official Google request shape, every required Google verdict,
hash-only Apple key persistence, migration/ORM parity, generic API errors, no-store
responses, Android provider refresh, iOS key registration/assertion, unsupported
platforms, cancellation, and build entitlement/configuration gates.

The Apple verifier suite additionally uses Apple's current published attestation sample
fields to validate RP ID, AAGUID, credential/key/COSE binding, and exact extension
decoding. Deterministically generated P-256 assertions cover signature verification,
strictly increasing counters, RP-ID mismatch, policy mismatch, malformed/trailing CBOR,
canonical Base64, tampering, and verification-envelope/key-binding corruption. The
published Apple receipt fixture is also checked against its historical signing time,
because that public sample's leaf certificate has since expired.

They intentionally do not claim the external Android/iOS gates above.
