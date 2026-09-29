# MCP dependency increment — 2026-09-29

The runtime lock adds the official `mcp==2.2.0` SDK. Its declared requirements
need `pydantic>=2.12.0` and `uvicorn>=0.31.1`. This candidate pins Pydantic2.12.5,
pydantic-settings2.14.2 and Uvicorn0.38.0. Existing HTTPX0.27.0 is retained for
the application; the SDK uses its separately declared HTTPX2 dependency.

Both runtime and development locks were regenerated using the repository's
UV0.12.0, universal Python3.11, hash-generating commands, then installed only in
the managed worktree's independent `.venv311`. The primary checkout environment
and frontend dependency junction were not modified.

The existing temporary ECDSA signing exception is unchanged in scope, owner,
original review date and expiry. The changed runtime lock required its existing
source-reachability check to be repeated. `audit_backend_dependencies.installed_evidence`
confirmed all three covered versions and source digests are unchanged:
pyattest1.0.5, python-jose3.5.0 and ecdsa0.19.2. `review_errors` with the candidate
lock found no source, entry-module, closure, owner or expiry violations. A direct
import search in installed MCP, MCP types and HTTPX2 found no `jose` or `ecdsa`
imports. Only the policy's runtime-lock digest was updated to the reviewed lock:
`12b8af84c5b7ffe4d3e624b2d2ebf96079b8ce464ce74f80800dd7ea4bbc68d9`.

The first advisory scan identified CVE-2026-58203 in pydantic-settings2.12.0.
Updating to2.14.2, regenerating both hash locks, syncing the isolated environment,
and repeating exception revalidation resolved that finding. The runtime scan
then exited0: no known vulnerabilities found, with2 advisory identifiers ignored
under the existing scoped ECDSA exception. Its CycloneDX output is
`outputs/mcp-runtime-sbom.json` (local generated evidence). This does not claim
ECDSA itself was patched. Full image and final release security gates remain open.

Local regression evidence at this increment: 59 combined MCP/identity tests;
the expanded MCP HTTP suite subsequently29 passed; full application mypy734
modules and Ruff application/tests pass; core/domain194 passed,2 skipped and27
subtests; existing rate-limit26 passed and18 subtests. The skipped core/domain
tests are not claimed as passing platform evidence.

Regenerated OpenAPI diffs include Pydantic's additional property/UUID-key schema
metadata and removal of redundant single-literal `enum` next to `const`. They
also include two existing source operations absent from the previous snapshot
(bulk document follow-up and WhatsApp recipient detail editing), alongside the
new MCP management API. Mobile's contract projection was regenerated from the
same canonical application schema; no mobile runtime code was changed.
