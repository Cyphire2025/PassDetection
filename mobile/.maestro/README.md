# Release-Hermes acceptance journeys

These flows run only against an isolated preview build and a synthetic staging
tenant. They must never use a real passenger, real trip, production OTP, or the
production API.

## Required EAS preview variables

Store the following in the protected EAS `preview` environment. Do not place
their values in Git, workflow YAML, screenshots, issue comments, or build logs.

- `EXPO_PUBLIC_APP_ENV=preview`
- `EXPO_PUBLIC_API_URL=https://<isolated-staging-host>/api/v1`
- `MAESTRO_EXPECTED_API_ORIGIN=https://<isolated-staging-host>`
- `MAESTRO_FIXTURE_SCOPE=synthetic-staging-v1`
- `MAESTRO_PASSENGER_PHONE` — digits only, owned synthetic number
- `MAESTRO_PASSENGER_OTP` — six-digit staging-only fixed fixture code
- `MAESTRO_STAFF_EMAIL` — synthetic client-manager account
- `MAESTRO_STAFF_PASSWORD` — protected synthetic password

- `MAESTRO_COORDINATOR_EMAIL` - synthetic coordinator account
- `MAESTRO_COORDINATOR_PASSWORD` - protected synthetic coordinator password
- `MAESTRO_ATTENDANCE_GROUP_NAME` - stable synthetic assigned-trip label
- `MAESTRO_ATTENDANCE_ACTIVITY_NAME` - stable manager-prepared activity label
- `MAESTRO_ATTENDANCE_QR` - canonical `pdatt:` token for a synthetic passenger
- `MAESTRO_MANAGER_GROUP_NAME` - group assigned only to the synthetic manager
- `MAESTRO_MANAGER_ITINERARY_ITEM` - one published itinerary item in that group
- `MAESTRO_MANAGER_UPDATE_TITLE` - stable manager notification title
- `MAESTRO_MANAGER_PASSENGER_SEARCH` - employee-code/name query for one seeded passenger
- `MAESTRO_MANAGER_PASSENGER_NAME` - exact passenger display name; both visa and flight ticket must be available
- `MAESTRO_PASSENGER_PRIMARY_TRIP_NAME` - first trip used to restore fixture selection
- `MAESTRO_PASSENGER_SECONDARY_TRIP_NAME` - distinct second assigned trip
- `MAESTRO_PASSENGER_ITINERARY_DOCUMENT` - policy-eligible itinerary document on the second trip
- `MAESTRO_PASSENGER_UPDATE_TITLE` - stable passenger notification title

The `e2e-test` profile is the only build profile that sets
`EXPO_PUBLIC_MAESTRO_ATTENDANCE_FIXTURE=true`. Production profiles explicitly
set it to `false`, and production public-configuration validation rejects a
missing, enabled, or malformed value. QR and credential values exist only as
protected `MAESTRO_` preview variables; they are not placed in `eas.json` or
workflow YAML.

The pre-test hook compares the API origin embedded in the binary with the
expected staging origin and rejects production, loopback, malformed variables,
or an implicit fixture scope. It never prints the values. Credentialed flows
also disable screen-recording uploads.

## Fixture contract

The passenger owns exactly one selected trip with at least one policy-eligible
passport document. For the expanded passenger journey the same identity owns
two explicitly assigned trips; the named secondary trip has the named published
itinerary document and a QR payload, while the named primary trip remains
available to restore the selection at the end. The first open may materialize
pending metadata; subsequent
opens must use the authenticated encrypted cache. The staff account belongs to
the same synthetic tenant but must not gain the passenger document route or
storage namespace. It is a client-manager principal assigned to the named
manager group. That group contains the named itinerary item and named passenger;
the passenger detail is available and both the visa and flight-ticket preview
endpoints return small policy-allowed synthetic files.

The fixture starts each named manager/passenger update unread. The flows are
retry-safe: the first attempt proves the unread-to-read transition; a retry
accepts and verifies the already-durable read state. Retain the first-attempt
JUnit result when claiming transition evidence, and reset notification read
state before a new release run.

The coordinator account is assigned to the named group, and that group contains
exactly one active activity with the named label. The QR belongs to a synthetic
passenger assigned to that activity. Keep at least one other synthetic passenger
unconfirmed so `Sync and recheck` remains an available recovery action after the
queued scan is restored. The account must receive a valid signed offline
authorization lease, complete roster/evidence preload, and satisfy every
blocking Event Ready check before airplane mode is enabled.

The Android attendance journey selects those stable labels, grants camera
permission, waits for Event Ready, and uses a secure preview-only input to invoke
the exact callback used by `CameraView`. It proves durable offline enqueue,
process-death restoration, reconnect/drain and a zero-unresolved coordinator
checkpoint, confirmed-scan deduplication, and the empty Scan Issues recovery
route. Fixture setup may reset the activity or tolerate an already-confirmed
passenger; the device-side confirmed receipt still has to suppress the second
submission. The journey never injects directly into SQLite or calls the API in
place of the application handler.

Run the repository contract first:

```sh
npm run e2e:contracts
```

After authenticating the EAS CLI, validate and manually dispatch the protected
workflow:

```sh
eas workflow:validate .eas/workflows/release-hermes-smoke.yml --non-interactive
eas workflow:run .eas/workflows/release-hermes-smoke.yml
eas workflow:validate .eas/workflows/production-release.yml --non-interactive
eas workflow:run .eas/workflows/production-release.yml
```

The workflow uses Android release-Hermes and iOS release-Hermes simulator
artifacts. Android also gets a separate airplane-mode/process-death cache gate
so an offline failure cannot poison the other emulator journeys. Rotate or
disable fixture credentials after the run and retain the JUnit evidence with
the release record.

Physical camera scanning, provider push delivery, store attestation, low-disk
behavior, screenshot protection, VoiceOver/TalkBack, and signed-device
performance remain separate release gates because simulators cannot prove
those platform contracts.

Passenger authentication is OTP-only; there is no passenger password to
change. The repository's forced-password route is restricted to staff
principals whose server-issued session has `force_password_change=true` and
rotates server credentials, so it needs a separately resettable temporary
account and is not placed in a retrying release workflow. Likewise, notification
routing requires a genuine Expo/FCM/APNs response and assignment refresh. Route
allowlisting, response dedupe, account isolation, and destination selection are
covered by source contracts, while a real provider tap and a resettable staff
password-rotation fixture remain external release gates. The Maestro suite does
not simulate either contract with a deep link or a production-only bypass.

External acceptance must record these exact provider/account checks without
capturing secrets or personal data:

1. Reset a synthetic passenger notification to unread, sign in, wait for the
   staging backend to acknowledge that exact preview installation's push token,
   then terminate the app.
2. Send a provider notification for the named secondary trip and the `updates`
   allowlisted route. Tap the OS notification, verify the assignment-refresh
   trip chooser selects only that trip, and verify the Updates screen opens.
3. Relaunch and tap the same provider response again; verify response dedupe
   prevents a second navigation. Revoke the trip assignment and resend; verify
   navigation fails closed to the trip chooser without protected content.
4. Reset a synthetic **staff** account to a temporary password and
   `force_password_change=true`, sign in, verify no trip tabs are reachable,
   rotate to a unique protected password, and verify the replacement session
   reaches only its assigned role. Reset the account after the run. This is not
   labeled a passenger-password test.

Until the staging provider and resettable staff-account controller exist, those
four steps remain `external/not-run`; YAML parsing or source tests cannot promote
them to device E2E evidence.

The synthetic QR seam proves the scanner handler and queue on a release-Hermes
emulator; it does not prove camera optics, focus, glare, damaged-code handling,
or scan speed on a physical device. Screen recording remains disabled. Preserve
only privacy-reviewed JUnit output, and never echo protected values in hooks or
support artifacts. A deterministic terminal backend rejection is not mutated by
this journey: rejection retry/discard remains covered by source tests, while the
journey opens Scan Issues and verifies successful recovery leaves no unresolved
record.
