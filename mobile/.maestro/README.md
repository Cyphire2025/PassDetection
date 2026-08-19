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

The pre-test hook compares the API origin embedded in the binary with the
expected staging origin and rejects production, loopback, malformed variables,
or an implicit fixture scope. It never prints the values. Credentialed flows
also disable screen-recording uploads.

## Fixture contract

The passenger owns exactly one selected trip with at least one policy-eligible
passport document. The first open may materialize pending metadata; subsequent
opens must use the authenticated encrypted cache. The staff account belongs to
the same synthetic tenant but must not gain the passenger document route or
storage namespace.

Run the repository contract first:

```sh
npm run e2e:contracts
```

After authenticating the EAS CLI, validate and manually dispatch the protected
workflow:

```sh
eas workflow:validate .eas/workflows/release-hermes-smoke.yml --non-interactive
eas workflow:run .eas/workflows/release-hermes-smoke.yml
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
