# MCP hotel rooming and check-in workbook snapshots

This slice implements the website's hotel rooming-list XLSX and hotel check-in-control XLSX exports. The request requires exact `agency_id`, `group_id`, `hotel_id` and `kind` (`rooming_list` or `checkins`). Current superadmin MCP export authority and the exact hotel/group association are checked for inspection, generation and cached-result recovery. There is no all-hotels selection or user-supplied storage path.

The shared `application/use_cases/rooming/prepare_excel.py` helper detaches the same canonical workbook inputs previously assembled inside the two web routes. It uses the existing `RoomingExcelExporter`, current-allocation eligibility checks, saved membership/assignment checks, automatic allocation fingerprint validation, VIP rules, priority-field resolution and website check-in dashboard projection. Application-owned failures use `RoomingPreparationError`; transport boundaries translate them. Existing web routes still release their read transaction before off-thread rendering, reauthorize/revalidate afterward, and preserve their filenames and audit behavior.

## Effects and durable lifecycle

`inspect_rooming_export` returns a complete source/render revision, passenger count, priority field keys and bounds. It writes no workbook. `prepare_rooming_export` accepts that revision and a stable caller retry key; the operation callback commits only a queued immutable receipt. A separate generation transaction renders and stores one immutable private artifact. `resume_rooming_export` explicitly resumes that operation or recovers its existing unexpired result. Same-actor recovery under a new authorized grant creates its own protected locator to the original workbook. Missing or expired successful artifacts never regenerate from the same operation.

The code-owned purposes are `rooming_list_excel` and `rooming_checkins_excel`, both XLSX MIME type and `.xlsx`. Metadata/content/delivery requests use the existing protected artifact transport and require current authorization for the originating agency/group. Current hotel association is also required to resume the operation. A retained workbook is a historical group-authorized snapshot, so later business edits do not overwrite its bytes.

Generation creates only the durable operation, private artifact metadata/copy and audit. These website export families have no passport-history checkpoint; delivery acknowledgement does not advance passport history. No room is allocated, passenger selected, check-in performed, QR event fabricated, key or welcome letter issued, message sent, source document overwritten, or business data removed. Workbook check-in flags and remarks reflect existing persisted evidence. Local delivery verifies the complete size and SHA-256 before acknowledging the copy.

## Scope, revision and resource boundaries

The source admission layer verifies every retained membership, assignment, preference and check-in passenger belongs to the exact group, and every room association belongs to the exact hotel. Foreign or incomplete associations fail rather than being silently filtered. Canonical stale/missing allocation checks remain active; generation never repairs an allocation.

The source revision covers group and hotel properties, allocation revision/fingerprint, every retained membership/VIP, room, assignment, passport, preference and check-in record, plus every detached render argument. When the saved allocation uses WhatsApp priority fields, it also covers the linked broadcast/link records and recipient imported fields, including contact, zone and transport metadata. Changes to source fields cannot escape the revision merely because they do not appear in the visible workbook columns. Revision checks run before rendering, after rendering and after private storage, before the artifact/operation commit.

Current runtime limits are:

- At most 1,500 rows in each source category: group passports and this hotel's memberships, rooms, assignments, preferences and check-ins.
- When WhatsApp priority fields are used, at most 100 exact linked broadcasts and 1,500 current linked recipients. At most six saved priority fields, matching the canonical allocator.
- At most 16 MiB of canonical source/render snapshot before rendering, and 32 MiB of resulting XLSX bytes.
- One rendering operation per backend process and a 120-second render deadline. Native work drains before cancellation releases the admission slot; cleanup can therefore extend beyond the deadline. The canonical XLSX generator remains in memory; no measured peak-memory claim is made.
- Existing protected transfer controls: 64 KiB chunks, a separate 120-second transfer deadline, current authorization/expiry/checksum checks and private conditional object writes.

Lock order starts with current control/grant/identity and operation, then exact group and hotel, optional linked broadcast inputs, passports, and hotel child records. Parent UPDATE locks fence inserts; bounded child reads use SHARE/NOWAIT. PostgreSQL uses a local 250ms lock timeout around legacy writer orders. SQL rollback retains the earlier queued receipt. A private object written before a failed final revision/commit can remain orphaned; deployment lifecycle cleanup must target only expiring `mcp-transfers/v1/` copies. No MCP deletion endpoint exists.

## Qualification evidence and limits

- `backend/tests/integration/test_mcp_rooming_exports.py`: 19 cases exercise actual canonical saved allocations and XLSX reopening, parity with both web exports, complete business-row snapshots unchanged by export/delivery, retry/new-grant recovery/expiry, all scope identifiers, stale source and allocation rejection, bounds, DB-only receipt preparation, storage failure, post-storage revision fencing and native cancellation drainage. A linked WhatsApp-priority case confirms transport-field changes invalidate an inspected revision.
- The combined rooming integration, existing rooming runtime/revision/allocation/generator/priority tests, tracking and protected-artifact suite passed 83 tests.
- `backend/tests/service_integration/test_mcp_rooming_exports_postgresql.py`: three cases pass against the disposable loopback PostgreSQL database. Independent worker bodies converge on one artifact across two grants, an older check-in writer returns busy then invalidates the prior revision, and a revoked connection cannot start generation.
- `mcp-connector/tests/test_rooming_exports_tcp.py`: both workbook kinds pass through the official SDK client, local connector proxy and real loopback HTTP backend, including inspect/prepare/retry, verified local download, acknowledgement and delivered-artifact recovery. Six existing connector artifact tests pass alongside them.

These tests use synthetic credentials and fixture storage/vault adapters. They do not qualify production object storage/lifecycle configuration, browser/MFA/vault behavior, real Codex file handoff, measured load/memory or VPS rollout. The separate broadcast-filter and agency/platform meal-plan exports remain outside this slice. No schema migration was needed.
