# Windows connector qualification and distribution

Owner: repository maintainers. Reviewed 2026-09-29. This is local component
evidence and an implemented CI release contract; the full Codex/production
acceptance gate remains open.

The unpublished connector version is `0.2.0`. It exposes eight local tools:
selected-file inventory; PDF upload; contact-workbook upload; WhatsApp header
image upload, inspection and ready-image recovery; verified export download;
and delivery acknowledgement recovery. Paths must be selected when starting
the connector. There is no automatic discovery of Codex attachments.

## Native vault correction

An actual Windows Credential Manager test found that the pinned pywin32 wrapper
rejects a byte string passed to `CredWrite.CredentialBlob`. The corrected adapter
passes Unicode JSON and decodes the UTF-16LE byte string returned by `CredRead`.
The earlier mocked vault test did not reproduce that native API contract.

The new native tests create only a uniquely named synthetic qualification
credential, confirm it was absent first, verify its recovery in a separate
Python process, then remove that exact synthetic entry. A separate process must
wait while the owner holds the native credential-rotation mutex. The tests do
not inspect or alter a real user authorization entry.

The complete connector suite passed **91 tests**, including the native vault
and process-lock checks and official SDK transport cases. Scoped Ruff passes.
The wheel was rebuilt with hash-locked build tools, installed into the isolated
connector environment, and its installed `gc-mcp --version` returned `0.2.0`.
Local wheel SHA-256:

`e955d9b09326090cd0526a3d690c40283556697ef56553ca5ddf926ee1e009d3`

This local wheel is unsigned. Its hash is a checkpoint for these exact local
bytes, not a published-release identity. Later builds must record their own
hash, and real browser MFA/OAuth consent in Codex remains unqualified.

## Required CI distribution path

The Windows connector job in `.github/workflows/ci.yml` installs the hash-locked
runtime, test and build dependencies, checks runtime-lock drift, runs the full
connector suite, builds without dependency resolution/build isolation, and
smoke-checks the installed wheel entrypoint. Image qualification now requires
that job, and the protected dispatcher's named-gate set includes it.

`scripts/release_connector.py` packages exactly the wheel, runtime lock and
instructions in a bounded checksummed inventory tied to the full source commit.
Only main-push CI attests that inventory. Promotion verifies the expected
repository, workflow, source digest, main ref and hosted-runner provenance
before interpreting the inventory, then verifies every asset byte and the
source instructions/runtime lock. It publishes those retained assets alongside
the image inventory. Changed hashes, widened filenames, source substitutions
and false interactive-sign-in claims fail closed.

The focused release tests passed **41 tests with one platform-specific skip**
across connector packaging, additive migration metadata, image artifacts,
same-schema updating, CI dispatch and release defaults. CI YAML parsing and the
existing immutable-action/supply-chain policy pass. The new remote CI job,
attestation and release publication have not been executed from this worktree.

The additive release contract still requires a separately qualified migration
orchestrator. Adding a connector CI gate does not enable a same-schema updater
to migrate production.
