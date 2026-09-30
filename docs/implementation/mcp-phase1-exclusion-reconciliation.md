# Five reviewed no-removal corrections — 30 September 2026

Phase 1 remains **open**. This correction integrates exactly five previously
planned frontend rows into the existing no-removal boundary. It does not add a
new exclusion policy or enable a runtime tool. The broader semantic contract map
remains an isolated, partially reviewed draft in the OPTIONS checkout.

The canonical handlers and their frontend endpoint chains prove these effects:

| Frontend action | Existing canonical effect |
| --- | --- |
| `passportsApi.bulkDelete` | Permanently removes selected passport records. |
| `uploadLinksApi.delete` | Archives the client group. |
| `uploadLinksApi.permanentDelete` | Permanently deletes the client group, including its `retain_records` variant. |
| `uploadLinksApi.revoke` | Closes the group and can schedule retention. |
| `gcAppAdminApi.softDeleteClientManager` | Deactivates assignments, revokes mobile sessions, marks profile/user deleted, clears invitation material and replaces credentials. |

The manager facade calls `DELETE /api/v1/gc-app/admin/client-managers/{profile_id}`.
Its name does not make these effects safe for an MCP adapter. Root inspected the
actual handler in `backend/app/presentation/api/v1/routes/gc_app.py` and the
frontend callable in `frontend/features/gc-app/api/gc-app-admin.api.ts` before
integrating the independently reviewed correction.

Each row changes from `implement` / `planned` to `manual_removal`, null phase,
`not_applicable` implementation status and the existing `no_removal` boundary.
The four passport/upload-link rows previously belonged to Phase 5; the manager
row belonged to Phase 7. No row becomes `verified` or gains runtime authority.

The root exact-change check compares against revision
`2352fa8ca2647f91a27176027d2dc4a27f110e1d`. It proves unchanged membership and order
of all 1,510 ledger rows, unchanged registration metadata and unchanged parsed
content outside these five rows. Current MAIN fingerprints for MCP transport,
saved support-contact discovery and contact upload remain preserved; the three
older registration differences in the OPTIONS draft are not copied over.

Root evidence is retained in
`outputs/phase1-exclusion-root-integration-20260930.json`. The draft's selected
23-endpoint contract tranche passed its independent source checker and 33
adversarial tests, but that is bounded contract evidence only. The draft still
has 974 pending aliases. Remaining mobile and email semantics, retained adapter
designs and production/capacity acceptance remain separate Phase 1 gates.

The existing inventory check passes for all 1,510 surfaces and 85 tools. All
12 existing drift/truthfulness tests pass, and `git diff --check` passes. These
checks qualify the ledger correction; no runtime regression is implied by this
metadata-only change.

This ledger correction changes no backend/frontend runtime source, business data,
grant, provider or production resource. It does not satisfy broad-map acceptance,
push/deployment approval or any whole-phase completion gate.
