# Additive application group access

This locally qualified Phase 7 slice exposes `inspect_group_access`, `add_staff_group_access`, and `add_manager_group_access`. It does not complete the remaining-domain or rollout gate.

Inspection requires exact agency/account IDs, the staff or manager account type, and 1–100 distinct group IDs. It separates owned, assigned and unassigned groups. `access_revision` binds the current target, selected group identity/status/name/roster revision, and every retained assignment (maximum 5000). The transport's separate `revision` identifies the running build.

Mutation adds only missing explicit access rows. Groups already owned by the target do not receive redundant rows. Existing assignments, including unrelated groups, retain their identifiers and timestamps. The proposed final assignment count must remain within the recoverable 5000-row bound. There is no role, credential, MFA configuration, connection capability, removal or replacement operation.

Current superadmin and active agency/account rules apply. Exact staff/manager role, current tenant, and nonarchived/nondeleted groups are required. Mutation and receipt replay additionally require the current connection's browser MFA to be between 60 seconds in the future and 600 seconds in the past, matching website `require_recent_mfa`. A fresh connection owned by the same user can recover the original immutable receipt using the unchanged request/key. Replay verifies exact assignment-to-group bindings and retained owned-group claims; removed or changed access makes the receipt unavailable.

The shared flush-only helper preserves website assignable-group predicates and owned-group exclusions. Both existing website replacement routes now lock their target user before replacement. MCP takes that same lock before inspecting all retained assignments, then locks selected groups in stable order. Website replacement semantics remain intact. Shared helpers do not commit or dispatch external work.

Local qualification on 2026-09-29: 34 SQLite/SDK/website tests, six real PostgreSQL 16.15 cases on the isolated loopback database, four production sources passing mypy, scoped Ruff, and all 87 backend quality budgets. PostgreSQL covers six concurrent cross-connection retries producing one assignment and audit for each account type, competing distinct intents with one revision winner, and both actual website replacement handlers blocking the MCP addition until commit, followed by revision rejection. SDK tests exercise inspection, both typed changes, immutable receipts, per-call audits and transaction commit.

Retained tests: `backend/tests/integration/test_mcp_access_changes.py`, `backend/tests/service_integration/test_mcp_access_postgresql.py`, and `backend/tests/unit/presentation/test_admin_group_access.py`. Production deployment, real Codex, capacity and complete application permissions coverage remain separate gates.
