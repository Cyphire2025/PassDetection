# Dependency exception revalidation and live audit result

**Follow-up status:** the five package findings below have now been remediated and the patched dependency audits pass. See `dependency-remediation-progress.md` and `dependency-patch-verification.json` for the newer lock/environment checkpoint. This page retains the original diagnosis and failing audit evidence.

The authorized PassportEye/orphan removal changed the runtime lock fingerprint. The existing dependency gate correctly required a repeat review before accepting its two existing temporary attestation exceptions.

Used the fresh hash-locked environment to run the gate's actual installed-evidence and import-closure functions. The installed versions and hashes of all Python source files in pyattest 1.0.5, python-jose 3.5.0 and ecdsa 0.19.2 match the previous reviewed values exactly. Parsed 1,176 application Python sources for imports: the same four application entry modules remain, with a 13-module verifier closure that does not reach `jose` or `ecdsa`. This is the existing conservative source/import gate, not a claim of arbitrary Python reachability proof or manual full-file audit of all 1,176 sources.

The only pre-update errors were two lock-fingerprint mismatches. Updated only the two `runtime_lock_sha256` fields from `1504909b310b33fcfbdd6a45d90f41dc6df8b743ec97f77e3ed918013fa43c75` to `fdcc91a5eb87f6f678fe03ef37c83109edb639527eba387d73d031114a4188b6`. Advisory identities and aliases, owner, October 6 review date, December 25 expiry, rationale, evidence links, package versions, source hashes and allowed entry modules are all preserved. No exception was added, extended or broadened. The underlying advisories are not represented as patched.

The real `audit_backend_dependencies.py --check-only` gate passes. All 14 existing tooling controls pass, including negative controls for unknown advisories, metadata drift, expired or changed exceptions, and forbidden direct/indirect/dynamic imports.

The actual complete hash-lock audit and SBOM generation **fail with exit code 1** on additional advisory data for five existing pinned packages. The scanner reports 54 raw matches; these represent 53 distinct advisory/package pairs because the same certifi advisory appears twice. The existing three ignored matches remain limited to the two approved exceptions.

| Existing package | Pinned version | Distinct advisory entries | Scanner-reported fix versions |
| --- | --- | ---: | --- |
| certifi | 2026.7.22 | 1 | 2026.10.18 |
| dnspython | 2.8.0 | 1 | 2.9.0 |
| opentelemetry-api | 1.45.0 | 1 | 1.45.1 |
| pillow | 12.3.0 | 39 | 13.0.0 |
| pypdf | 6.19.0 | 11 | 6.20.0 through 6.21.2, depending on advisory |

These are dependency-scanner matches and supplied fix metadata, not individual source-reachability validations or tested upgrade compatibility. The fail-closed gate remains a release blocker. No dependency pins or lock files were changed by this follow-up, and no new exclusions were introduced to hide those results. The root agent was notified for remediation planning within the overall audit.

Evidence: `dependency-exception-revalidation.json` includes versions, byte hashes, import edges, preserved fields, test results and every advisory identity; `backend-lock-audit.json` retains the machine-readable audit; `backend-lock-sbom.cdx.json` retains the SBOM; `backend-dependency-audit.txt` retains the gate output. `dependency-reviewed-files.json` records current hashes and honest file-review scope. No Codex Security scan tools were used.
