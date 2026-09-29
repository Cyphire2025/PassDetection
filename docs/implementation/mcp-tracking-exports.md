# MCP group WhatsApp tracking workbooks

This adapter implements the existing client-group WhatsApp submission-tracking XLSX surface. It uses one explicit agency/group, the website's eight status filters (`all`, `submitted`, `not_submitted`, `multiple_submissions`, `needs_review`, `unmatched_submission`, `replacement`, `rejected_upload`), and an optional exact currently linked broadcast. Omitting that broadcast selects the linked comparison source for this group; it never widens to all agency records. The separate broadcast roster/filter export, rooming/check-in workbooks and agency/platform meal plans remain different adapters.

`prepare_tracking_excel.py` now prepares the canonical filters, default supplemental fields, pending recipient rows, zones, contacts, ECR fields and detached render inputs for both the website route and MCP. The existing `PassportExcelExporter` renders the workbook. The website's permissions, source limit, response filename and audit behavior remain in its route. MCP adds its narrower source bounds without changing the website defaults.

## Durable request and retained delivery

- `inspect_tracking_export` returns current counts, fields, runtime limits and the complete source/render revision. It creates no workbook or history.
- `prepare_tracking_export` accepts the inspected selection/revision and a stable idempotency key. Its operation callback stores a DB-only immutable queued receipt. Native rendering and private object storage run only after this receipt commits.
- `resume_tracking_export` explicitly resumes that operation or recovers the same unexpired artifact. Current actor, capability, exact group and selected link are rechecked before returning a cached result. A newly authorized connection for the same actor receives its own protected artifact locator. Expired or missing completed artifacts never regenerate from the same operation.

The protected artifact purpose is `whatsapp_tracking_excel`, with XLSX MIME type and `.xlsx` filename. Downloads use the existing authenticated chunked transport; a local file must pass byte-count and SHA-256 verification before delivery acknowledgement. There is no passport export-history checkpoint for tracking, matching the website. Generation or delivery never sends a message, changes a roster resolution or advances passport history.

Each metadata/content/ack request revalidates the live actor/grant/export capability and the original agency/group association. A retained workbook is a historical group-authorized snapshot: it can still be downloaded after linked comparison data changes. Current link checks on inspect/prepare/generate/resume do not widen that transfer scope or introduce authority over another group. This uses the approved existing artifact schema; no migration was required.

## Runtime and concurrency limits

The MCP path admits at most 100 linked broadcasts and 1,500 rows in each source category: all group passport rows, all linked recipients (including removed recipients retained for replacement evidence), and active group roster resolutions. Excess input is rejected, never truncated. The exact current website-eligible passport list is then read using the existing repository ordering and visibility policy.

At most 256 catalog fields and a 16 MiB canonical source/render snapshot are admitted before rendering. One generation per backend process renders at a time, with a 120-second deadline and a 32 MiB workbook output ceiling. The canonical XLSX generator is in memory; these admission limits are not a claim of measured peak native memory. Cancellation/deadline completion drains the native worker before releasing generation capacity. The shared transport uses 64 KiB chunks, a separate 120-second transfer deadline and the existing private conditional storage adapter.

The generation transaction locks current control/grant/identity, the operation, client group, linked broadcasts, links, recipients, resolutions and passports. Parent locks fence child insertion. Source locks use `NOWAIT`; PostgreSQL also uses a local 250ms lock timeout to reject older writer orders without waiting through a deadlock. The complete revision is checked before rendering, after rendering, and after private storage before committing the artifact and operation result.

Rollback leaves the earlier queued receipt available. A private transfer copy written before a final revision/commit failure can remain orphaned and must expire under the deployment lifecycle limited to `mcp-transfers/v1/`. Source documents and business records are never cleanup targets, and no removal tool is exposed.

## Local qualification

- `backend/tests/integration/test_mcp_tracking_exports.py`: 21 tests passed, exercising actual workbook generation and reopening for all eight website filters, pending rows and retained replacement evidence; response-loss retry and new-grant recovery; expiry; current link/agency/group/grant checks; recipient revision changes; storage rollback and post-storage fencing; DB-only receipt preparation; source/field/snapshot/output bounds; native cancellation drainage and capacity recovery. Website and MCP sheet values match; tracking creates zero passport-history or message rows.
- `backend/tests/service_integration/test_mcp_tracking_exports_postgresql.py`: three tests passed on the disposable loopback PostgreSQL database. Independent worker bodies serialize to one workbook across two grants, recipient-first writers return busy and then invalidate the saved revision, and revoked grants prevent generation.
- `mcp-connector/tests/test_tracking_exports_tcp.py`: one test passed through the official MCP SDK client, connector proxy and real loopback HTTP backend. It inspects, prepares, retries, downloads/reopens the verified local XLSX, acknowledges it and resumes the delivered artifact. Six existing connector artifact tests also passed.
- The combined tracking, existing filter helpers, route decomposition, passport Excel and artifact suite passed all 102 tests after the shared preparation change. Scoped Ruff, formatting and mypy pass for the new production modules; the backend quality budget check passed all 87 modules.

The TCP and storage tests use synthetic credentials, fixture object storage and a fixture credential vault. Production S3/lifecycle configuration, measured load/memory behavior, browser/MFA sign-in, real Codex attachment handoff and production rollout remain separate gates. This slice does not qualify the separate broadcast export, rooming, meal-plan or full Phase 4 surface.
