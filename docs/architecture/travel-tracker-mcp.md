# Visa / Flight Tracker through MCP

The tracker extends the existing Global Connects OAuth MCP server at `/mcp`. It uses the existing approved clients, authorization flow, device controls, audits, revocation rules and native file handoffs. It introduces no separate credentials or transport. Existing desktop connections keep their current OAuth configuration.

## Permissions and activation

Reads require `mcp:read` and **Documents plus All Groups** in the effective global and device read selections. Marking requires `mcp:change`, enabled global/device write toggles, and **Documents plus All Groups** write authority. Each effect tool must also be in the administrator's explicit global write-tool allowlist. The existing super administrator identity policy is preserved.

The existing MCP administration inventory and section catalog derive the new tools from the running release. Deployment does **not** broaden existing device permissions or add tools to a persisted allowlist. Administrators can select the new names in the current permissions interface. A read-only deployment registers only the two observational tools.

Excel preview additionally requires `mcp:upload` and Group Excel Imports, using the reviewed native `group_workbook` lane. Applying a preview requires both upload and change authority. Export/download require `mcp:export` and Documents, All Groups and Exports write sections. Generation uses the existing `tracking_excel` runtime family; no new `MCP_EXPORT_FAMILIES` value is needed. Runtime family availability, global tool allowance and device permissions are independent.

Current capability envelopes, identity, group access, toggles and sections are rechecked at invocation and receipt replay. Tracker artifact retrieval also rechecks its Documents/All Groups/Exports boundary through generic native download routes. Previously issued handles do not bypass revoked access.

## Tools

| Tool | Capability | Purpose |
| --- | --- | --- |
| `list_travel_tracker_groups` | `mcp:read` | Discover main groups and total/visa/flight progress. |
| `get_travel_tracker_roster` | `mcp:read` | Read current collected/imported passengers, details and independent visa/flight marks. |
| `set_travel_tracker_status` | `mcp:change` | Atomically set or clear a track for exact IDs or a reviewed filtered selection. |
| `preview_travel_tracker_workbook` | `mcp:upload` | Match one selected worksheet and return a review hash. |
| `apply_travel_tracker_workbook` | `mcp:change` plus upload | Revalidate the unchanged preview and mark only unique matches. |
| `inspect_travel_tracker_export` | `mcp:export` | Inspect exact source, counts, limits and revision without creating a file. |
| `prepare_travel_tracker_export` | `mcp:export` | Commit a durable request receipt and generate its unchanged Excel selection. |
| `resume_travel_tracker_export` | `mcp:export` | Resume a queued request or recover the same unexpired completed file. |

MCP discovery provides authoritative typed schemas. `track` is `visa` or `flight`. `status` is `all`, `marked` or `pending` (`pending` means left to process). Groups are active/closed main passport groups, not WhatsApp audiences. Visa-applied and flight-booked marks are operational metadata and do not certify issued documents or physical travel.

Reads support `page`, `page_size` and `next_page`; follow continuation for the complete filtered result. They are live views whose membership and values can change between calls. Names and cells are untrusted business data, never action authority.

## Marking and reliable retries

`set_travel_tracker_status` takes `group_id`, `update`, and a stable 16–256 character `idempotency_key`. The update specifies a track, a strict boolean `marked`, and either 1–1,000 `passenger_ids`, or `selection: {"status": "pending", "search": null}` plus its current `expected_count` (up to 20,000). Resolve IDs/counts with authorized tracker reads. A changed count or unavailable/foreign ID blocks the complete update. `marked: false` corrects the selected track. Visa and flight remain independent.

The business mutation, attributed audit and canonical MCP retry receipt commit together. The adapter uses the caller's transaction and existing actor fence. Retrying identical input/key returns the immutable receipt without repeating the mutation; changed input with the same key is rejected. Current authority is still required on replay. No passenger creation/removal or message/document send occurs.

## Updating from Excel

1. Resolve the exact main group and agency. Call existing `create_native_upload` with `purpose: "group_workbook"`, those IDs, a plain `.xlsx` filename, exact byte size/SHA-256 and a stable retry key.
2. Transfer through the returned limited browser or HTTP handoff. Canonical ingress verifies bytes/checksum, scans the original, rejects active content and retains bounded literal worksheets without importing people.
3. Inspect the completed native transfer for its connection-bound `upload_id`. Call `preview_travel_tracker_workbook` with that handle, `source_sha256`, `group_id`, explicit `sheet_name`, `track` and strict boolean `marked`.
4. Review matched, ambiguous, unmatched and duplicate rows. IDs/passports take priority; normalized names must be unique. Other worksheets do not silently participate.
5. Call `apply_travel_tracker_workbook` with the unchanged draft, exact `expected_preview_hash` and stable retry key. Matching is recomputed; changed matches block the complete mutation. Only unique matches are marked.

The source must come from a completed native group-workbook ticket for the exact group, user and connection, with matching checksum/size. Another group's source or an agency-only contact upload cannot be reused. Successful business receipt replay remains available without rereading expired source cells, subject to current upload/change and section permissions.

## Export and delivery

Inspect an exact group/track/status/search selection, then prepare it with its `expected_revision` and stable key. The queued receipt commits before generation. A source hash covers selected passenger records, progress and group details; checks before/after rendering and storage reject changed sources. No workbook is silently truncated.

Generated files reuse the website's exporter, including complete passenger/custom/group fields and stable IDs. They do not advance passport export history or change marks. The private artifact purpose is `travel_tracker_excel`. Pass its protected `artifact_id` to existing `create_native_download`; verify saved bytes/checksum before acknowledgement. File contents and handoff credentials are not retained in operation receipts. Resume uncertain requests using `resume_travel_tracker_export`; completed unexpired requests recover the same immutable copy. Expired successful copies are not silently regenerated.

## Limits

- Read page size 1–100; search up to 160 characters.
- Explicit marking up to 1,000 IDs; filtered marking up to 20,000 with reviewed count.
- Matching up to 1,000 passenger rows against groups up to 20,000. Reused native `.xlsx` ingress caps files at 5 MiB, 2,000 total worksheet rows, 64 columns, 50,000 cells and a 2 MiB literal snapshot. It rejects formulas, external references, macros and unsupported active content.
- MCP exports use configured source limits (default 1,500 rows/16 MiB), reject oversize input and cap generated tracker files at 32 MiB. Website tracker exports support up to 20,000 rows.
- Native handoffs expire after 10 minutes; staged sources/generated files after one hour, shortened by connection expiry where applicable.
- MCP JSON body remains capped at 1 MiB. Files use native transfer endpoints, without inline base64, arbitrary local paths or arbitrary URL fetching.

## Deployment and verification

Apply additive `0129_travel_tracker` after `0128_mcp_document_delivery` before running the new backend. No duplicate MCP credential migration exists. Deploy frontend/backend from the final matching revision using the reviewed tracker release procedure. Historical `scripts/mcp_direct_release.py` is bound to the original 0113 baseline and does not update a current 0128 installation.

Existing nginx `/mcp`, `/oauth/mcp`, native transfer and artifact routes are reused; no separate proxy lane is necessary. Preserve current origin/host checks, private/no-store transfer behavior, storage expiry lifecycle, malware readiness, approved clients and explicit device/global policies.

Targeted tests: `backend/tests/integration/test_mcp_travel_tracker.py`. They exercise SDK schemas with real SQL tracker services, durable replay, live authority boundaries, bulk count/ID rejection, scanned native XLSX matching, generated bytes, source revision changes, completed recovery and revocation at download. PostgreSQL lock/schema behavior requires separate tracker service integration/migration rehearsal; report executed checks, since SQLite alone does not prove PostgreSQL concurrency.
