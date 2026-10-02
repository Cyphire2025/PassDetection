# Removing an obsolete MCP device from the dashboard

The Devices list omits a grant only when it is already revoked and its `revocation_reason` is exactly `administrator_removed`. This explicitly archived state preserves the grant, credentials, historical operations, artifacts and audit references. Credential validation continues to reject the revoked grant.

Other revoked connections remain visible as Disconnected. Active or disabled connections remain visible even if they accidentally carry the removal marker. Filtering happens before pagination so hidden entries do not occupy rows or create a false next page.

The initial maintenance action is authorized by the user's request to remove **Nipun’s Codex desktop** from the live main site. Its verified live ID is `27ab38f4-e13b-4289-bbe8-a1fd9658a97a`, and it was already revoked with `administrator_revoked`. It has historical operation and artifact references, so deleting its grant would damage provenance.

The live maintenance procedure must retain a private before snapshot, lock and recheck the exact ID/name/client/revoked state, change only its removal reason, and append `mcp.connection_removed` through `AuditLogRepository.record` in the same transaction. The maintenance audit actor is anonymous/system (`user_id=None`); an administrator session is not fabricated. Other grants, access permissions, credential rows and existing audit entries must remain unchanged.

This change requires no schema migration or frontend change. A narrow retained backend deployment can keep the current frontend, workers and infrastructure. Application revisions for those unchanged services remain their earlier deployed revision; the backend image and proxy cutover must be recorded separately.

## Live completion — 2 October 2026

The obsolete entry is removed from the live Devices response at `https://tech.gctravels.com/admin/mcp`. **Yogesh Macbook** and **My Codex connection** remain active, and global MCP access remains enabled.

| Evidence | Verified value |
| --- | --- |
| Backend source revision | `29bf6f18c17a638e050e5a6564edc0fb4b8ccfd8` |
| Backend image | `sha256:5b52d179b404ba6b9c7a3cc0fa115f1c42fea58ea65790a0f818740ba7f0e926` |
| Retained frontend/worker revision | `12d11fbf8178e1e5424a5de0ce3f0bb91bd16080` |
| Database schema | `0125_mcp_connection_requests` — unchanged |
| Final operator SHA-256 | `2dbf1c0e90e3c7b443f675bb6d41b5bcbe2eee2a3f6599012f400791cf34225b` |
| Completion journal | `journal/0028-removed-device-complete.json` |
| Completion journal SHA-256 | `83f433a9a05f39d5b56e20c09b75ba343945f76f80ee7ee6ac4d6595eceb3d08` |
| Maintenance audit entry | `8a2a975f-15ae-4080-af7d-64e7f9eba245` |
| Backup | `removed-device-v1-before-removal.pgdump`, 15,034,963 bytes |
| Backup SHA-256 | `5d859c458db5eae4f741f86bebca043da79824a0a2e1ea17e7c6360d7ff4e18c` |

All 20 running services pass their applicable health checks. The two changed containers are the backend and proxy. The same frontend, worker, scheduler and infrastructure identities remain live. All 397 preexisting containers and 199 images are retained; the final inventory contains 402 containers and 201 images, including retained builders, intermediate images and stopped earlier candidates.

The final maintenance transaction rechecked the exact target tuple, changed only `revocation_reason`, verified the prospective full grants hash and unchanged control/token/authorization-code hashes, and retained every foreign-key dependency row hash. The old grant, its 64 token records, authorization code, operation, artifact and artifact-access record remain present. It remains revoked. One maintenance audit event was appended; the global audit chain verifies successfully.

The fresh database dump passed complete archive decoding, and the independent final probe checked its bytes and hash again. No schema migration or restore was performed. Evidence is retained under `/opt/GlobalConnectsDashboard/tmp/mcp-direct-29bf6f18c17a638e050e5a6564edc0fb4b8ccfd8`, including the private before snapshot and public change/verification receipts.

Before activation, all 16 device access tests and 15 focused final operator regressions passed. Ruff, diff checks and the unchanged canonical OpenAPI contract check passed. The final runtime probe verified committed backend source bytes, schema125 shape, non-superuser role, request-table privileges and readiness before exposing the new backend. The independent live probe checked public health/revision, twenty live services, retained resources and the actual Devices response containing only the two active entries.

The first build admission stopped before changing services because each individual worker limit was below the builder budget. A separately frozen operator combined the required worker limits and resumed the same drained IDs. The initial cutover restored the old services after an erroneous `/health` probe returned 404; the separately frozen final operator used the correct `/nginx-health` endpoint and fresh clones. Earlier operators, receipts and candidates are retained. The first maintenance snapshot made no change when the application engine's initial role query prevented a later isolation change; the final scoped maintenance engine started with repeatable-read isolation and enforced the same runtime role policy before executing the transaction.

Local independent result: `outputs/old-device-live-verification.json`. This later documentation update records the deployed backend revision above; it does not represent another application release.
