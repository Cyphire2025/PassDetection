# Background release integration

Status: implementation and local focused verification complete; final reviewed frontend budget source hash refreshed after both UI agents confirmed stable edits. Real PostgreSQL and exact-image Linux qualification remain pending.

## Implemented

- Target manifest is `0142_group_background`, previous schema remains `0140_document_update_context`, and deployment kind, workers, service identities, volumes and Compose topology remain unchanged. Published migration 0141 is unmodified.
- Exact AST/hash-bound contracts support the full 0140 -> 0141 -> 0142 chain, plus a separate background-only contract for the exact reviewed 0141 source commit `875d17b25da2687b5673148fabe9d10346ae0e4a`. The older 0140 Git baseline remains `98f4fb4f7ba982fc46f917d24db63d59993a74a8`. Unknown revisions/schemas remain rejected.
- Preservation is source-aware: a 0140 baseline normalizes only the three newly introduced private key columns; a 0141 baseline includes existing logos, banners and their grants in the original catalog/row/ACL digest and normalizes only the new background column. Every newly introduced value must remain null before activation, and new column grants are rejected.
- The migration helper captures the original selected baseline before DDL and reuses its digest for resumes. A partially committed 0140 attempt at 0141 executes only 0142 and only recovers forward. Original source-schema writers never resume against a newer schema. Fresh CLI recovery restores the original selected source from the bound rehearsal receipt.
- Rehearsal and host proofs bind the selected source schema, contract digest, exact backend image, helper sources and existing backup. Rehearsal code now checks background runtime grants, early writes, explicit column-grant expansion, and partial-checkpoint resume in an isolated synthetic database.
- Retained image builder admits only the newly reviewed 0142 schema in addition to its existing exact allowlist. Historical company rehearsal tests follow the actual current head. Topology verification checks the new exact 0142 -> 0141 parent edge.
- Reviewed source bindings include the intentional public-draft Nginx log redaction and tightened frontend module budgets. The final budget hash includes the settings/passport decomposition and camera guide ratchets, and its strict source-binding test passed.
- `docs/deployment-modes.md` documents both selected source paths and the unchanged existing installation approach. No production action, provider send, environment mutation, data copy, automatic downgrade, push or deployment was performed.

## Checks

- Backend helper, source-aware schema preservation and historical rehearsal tests: 35 passed.
- Host branding release tests: 13 passed.
- Rehearsal receipt source-binding tests: 2 passed.
- Retained builder tests: 18 passed.
- MCP release-contract tests: 5 passed.
- Targeted Ruff, Python compilation and Git whitespace checks passed.
- Matching `.venv` final combined extraction/release regression rerun: 259 passed, 11 subtests passed in72.73 seconds. The host suites also passed in `.venv`. Initial isolated passes used `.venv311` before its stale pypdf version was discovered; neither environment was modified.
- Exact-image real-PostgreSQL rehearsal requires a clean committed candidate and supported local Linux Docker environment. It has not run here; local test success does not establish production locking or VPS readiness.

## Inspected / changed release sources

- `backend/scripts/workspace_branding_release.py`
- `backend/scripts/workspace_branding_release_schema.py`
- `backend/scripts/release_workspace_branding_upgrade.py`
- `backend/scripts/qualify_workspace_branding.py`
- `backend/scripts/verify_migration_topology.py`
- `backend/app/core/config/release_manifest.json`
- `backend/alembic/versions/0141_workspace_branding.py`
- `backend/alembic/versions/0142_group_background.py`
- `scripts/release_workspace_branding_contract.py`
- `scripts/release_workspace_branding_policy.py`
- `scripts/release_workspace_branding.py`
- `scripts/qa/qualify_branding_migration.py`
- `scripts/mcp_direct_build.py`
- `scripts/test_mcp_direct_build.py`
- `scripts/test_release_workspace_branding.py`
- `scripts/test_branding_migration_qualification.py`
- `backend/tests/unit/scripts/test_release_workspace_branding_upgrade.py`
- `backend/tests/unit/scripts/test_workspace_branding_release_schema.py`
- `backend/tests/unit/infrastructure/test_companies_rehearsal_roles.py`
- `docs/deployment-modes.md`

## MCP coverage ledger reconciliation

- `scripts/mcp_inventory.py --check` passed for 1,953 surfaces after direct review of 5 changed surface identities, 16 previously unclassified branding/editor/voice-preview surfaces, and retirement of the old combined platform-settings UI surface.
- All existing reviewed dispositions, phases and adapter evidence were preserved for identity-only updates. Browser image processing remains an internal dependency; image deletion and the extracted data-purge hook retain explicit manual-removal exclusions. Local voice preview requires browser microphone permission. No runtime tool, scope, grant or business adapter was enabled.
- Exact changed IDs and manual exclusions are recorded in `mcp-classification-review.json`. The existing inventory regression suite passed 12 tests.

## Final dependency, storage and metadata integration

- Exact before/after source bindings were added for `backend/requirements.txt`, both reviewed Python locks, `backend/app/infrastructure/storage/minio_repository.py`, and `backend/backend_quality_budgets.json`. The final frontend budget source hash was refreshed after the document-workspace ratchets were added. Both original reviewed Git baseline identities remain unchanged. No wildcard source admission was expanded.
- Independent lock parsing confirmed19runtime and18development package removals, zero additions, and zero retained package version/hash changes. The bounded object-stream change adds only an optional exact end byte and rejects inconsistent start/length/end triples; the reviewed worker/task and deployment identities remain unchanged.
- Backend quality budgets are now explicitly source-bound even though their path was not previously selected by the persistent-source glob. Unknown source paths still fail closed. Details are retained in `final-release-bindings.json`.
- FastAPI's stale local-MRZ description now identifies Global Connects Dashboard and AI passport extraction. Full API snapshot regeneration was structurally compared with the preceding snapshot: only `/info/description` changed. App title/version and request, response and security definitions remained identical. Evidence is `api-description-update.json`.
- In the fresh hash-checked `.tmp/dashboard-audit-venv`,13branding release tests,2rehearsal proof-binding tests and5MCP release-contract tests passed. TargetedRuff and the1953-surface MCP inventory check passed. The full API snapshot check and separately reviewed mobile OpenAPI snapshot check also passed. Per-file current hashes and focused-diff coverage are in `final-integration-reviewed-files.json`.
