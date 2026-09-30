# Browser transport dependency review

Source review on 2026-09-30 corrected six frontend helper rows in the workflow
inventory from planned administrator reads to internal dependencies. These
helpers belong to the already accepted public-upload and device/browser protocol
boundaries. This correction adds no tool, changes no application behavior, and
does not qualify a business workflow or close a phase gate.

| Source helper | Observed responsibility |
| --- | --- |
| `public-upload-session.ts:getOrCreatePublicUploadSessionId` | Reuses or creates a public-upload bootstrap identifier in token-keyed browser sessionStorage, with module-memory fallback. The identifier preserves the public client protocol and is not MCP authority. |
| `attendance-scan-queue.ts:listPendingAttendanceScans` | Reads the current signed-in owner's local IndexedDB pending scan queue. |
| `attendance-scan-queue.ts:getNextPendingAttendanceAttemptAt` | Computes client retry timing from that owner's pending scans and discard tombstones. |
| `attendance-scan-queue.ts:listRejectedAttendanceScans` | Filters and orders the owner's local rejected scans for the selected group/session. |
| `attendance-scan-queue.ts:getBrowserAttendanceQueueSafetySnapshot` | Requires the current browser owner and reads the local queue's safety state. |
| `browser-offline-authorization.ts:getBrowserAttendanceRuntimeHint` | Reads an unexpired owner/agency-scoped runtime UUID hint from local offline authorization records. The paired HttpOnly cookie remains authoritative. |

The reviewed source is
[public upload bootstrap](../../frontend/features/passports/api/public-upload-session.ts),
[browser attendance queue](../../frontend/features/tour-operations/services/attendance-scan-queue.ts)
and [offline authorization](../../frontend/features/tour-operations/services/browser-offline-authorization.ts).
Server-retained scans, checkpoint counts and attendance summaries remain separate
business read obligations. The correction does not authorize MCP to inspect an
arbitrary browser's local storage, fabricate scans, create runtime credentials,
publish checkpoints or acknowledge/discard queued evidence.

The inventory still discovers these helper declarations. An exact parsed
comparison confirmed the same surface IDs and recorded source contracts, with only these
six classifications, rationales, phase assignments and implementation records
changed. Their status is `not_applicable`, with no adapter or executable proof
claimed. All other rows retain their prior classifications and evidence.
The inventory checker, all 12 drift tests and `git diff --check` pass.

On the integration base `ee648457`, the counts change from 831 planned / 203
implemented-unverified / 467 not-applicable to 825 / 203 / 473 respectively;
the total remains 1,501 surfaces and 76 tools. These are overlapping source/API/UI
representations, not unique business operations or an implementation percentage.
