# Patched dependency checkpoint

Remediated the five packages reported by the live Python lock audit. Selected releases were checked against primary PyPI metadata for version, supported Python range, yanked status, dependency requirements and artifact hashes. All new hashes in the runtime lock match that metadata. Pillow 13 includes Windows and Linux x86_64 CPython 3.11 wheels. The repository's reviewed Python 3.11.15 runtime is supported by all selected versions.

| Package | Previous version | Patched version | Primary release metadata |
| --- | --- | --- | --- |
| certifi | 2026.7.22 | 2026.10.18 | [PyPI](https://pypi.org/pypi/certifi/2026.10.18/json) |
| dnspython | 2.8.0 | 2.9.1 | [PyPI](https://pypi.org/pypi/dnspython/2.9.1/json) |
| opentelemetry-api | 1.45.0 | 1.45.1 | [PyPI](https://pypi.org/pypi/opentelemetry-api/1.45.1/json) |
| Pillow | 12.3.0 | 13.0.0 | [PyPI](https://pypi.org/pypi/Pillow/13.0.0/json) |
| pypdf | 6.19.0 | 6.21.2 | [PyPI](https://pypi.org/pypi/pypdf/6.21.2/json) |

Pillow 13 supports Python 3.11. Reviewed its removals against application usage: the application uses supported RGB/RGBA conversion, EXIF transpose, resizing, sharpening and encoding APIs; no removed methods or dtype-changing `fromarray(mode=...)` calls were found. The [Pillow release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html) document the support/removal boundary. The [pypdf changelog](https://pypdf.readthedocs.io/en/6.21.2/meta/CHANGELOG.html) confirms parser work-limit and repeated-read security changes across the selected update.

The original DNS advisory reported 2.9.0 as a fix. Upstream's newly published 2.9.1 patch also corrects resolver query identifiers, negative caching and security validation behavior, so 2.9.1 was chosen to include those known fixes. Its Python range and runtime dependency graph remain compatible. See the [upstream DNS release notes](https://dnspython.readthedocs.io/en/stable/whatsnew.html).

Regenerated both backend locks using reviewed **uv 0.12.0** and their existing universal/hash-generating commands. Added exact certifi, dnspython and OpenTelemetry API transitive pins to the reviewed requirements input so their security fixes survive ordinary regeneration. Package/hash comparisons prove exactly five backend package changes, no additions or removals, and unchanged versions and hashes for all other packages: 104 runtime and 141 development entries. The connector's existing backend-constrained command changes only OpenTelemetry API; all other 30 packages, including MCP, httpx2 and pywin32, retain exact versions and hashes. It does not contain certifi. No SDK upgrade or protocol configuration change occurred.

Provisioned a separate ignored environment with `scripts/bootstrap_backend.py`. The first attempt failed after a pip staging file disappeared from the system temporary directory. That incomplete target was retained. A second fresh target, `.tmp/dashboard-security-patch-venv-2`, bootstrapped using task-local temporary directories. Before tests began, a final hash-checked provision applied the just-reviewed DNS 2.9.1 patch. Existing developer environments and the root agent's already-running `.tmp/dashboard-audit-venv` were never changed.

Revalidated the two existing attestation exceptions inside the fresh environment: verifier versions and all reviewed source bytes remain exact, and the same application/import closure does not reach the forbidden signing dependencies. Updated only their lock fingerprint. Their advisory identities, owners, review date, expiry, rationale, versions, source hashes and restrictions were not added to or extended. The exceptions remain temporary acceptance of unpatched, unreachable signing paths.

Results on the patched environment:

- Backend live hash-lock audit/SBOM: **passed**, no known vulnerabilities outside the three existing ignored matches.
- Connector full hash-lock audit: **passed**, no known vulnerabilities and no ignores.
- Affected backend image/PDF/security/provider/attestation/branding/export fixtures: **850 passed, 21 subtests passed**, 51.19 seconds.
- Connector transport/callback/CLI/refresh/file fixtures: **163 passed**, 6.90 seconds. Native-vault and backend TCP fixtures excluded.
- Strict release/tooling/inventory regressions: **39 passed, 29 subtests passed**.
- Mypy: **passed, 1,176 source files**.
- Backend and mobile API snapshots: **unchanged, both checks passed**.
- Hash-verified development toolchain check and `pip check`: **passed**.
- TLS CA-context construction with hostname/certificate verification, synthetic DNS-wire parsing, email validation without DNS delivery queries, and tracestate parsing: **passed**. No actual provider, sign-in or stored-vault activity.
- Source manifest and MCP inventory: **passed, 1,950 surfaces**.
- Strict release policy: current requirement AFTER hashes refreshed; **all 20 file bindings and both exact reviewed baseline commits independently verified**. Admission/proof requirements remain unchanged.

The earlier 870-test operator result and the root agent's complete application-suite checkpoint use the preceding lock and must be reported separately. This record does not claim a complete application-suite rerun on the patched lock or real Docker/PostgreSQL/native Linux image/full-image vulnerability qualification.

Final evidence is in `dependency-patch-verification.json`, `dependency-patch-lock-diff.json`, `connector-dependency-patch-lock-diff.json`, `dependency-patch-upstream-metadata.json`, `dependency-patch-exception-review.json`, `dependency-patch-final-release-bindings.json` and `dependency-patch-reviewed-files.json`. Original failing audit output/SBOM is retained; patched audit/SBOM and test logs have separate filenames. No Codex Security tools were used.
