# Documents frontend review and improvement

Status: all46 current documents runtime source files manually read with content digests and caller tracing; focused fixes/refactor and verified removal of the retired UI subtree implemented. Repository-wide qualification is coordinated in the main tracker.

## Completed changes

- Read the complete former982-line document workspace and separated it into20-line composition, upload lifecycle250lines, review selector89lines, delivery93lines, orchestration55lines and focused UI hosts57–177lines. Lazy optional dialogs/table chunks remain lazy. All extracted runtime modules are below300lines.
- Upload checks and receipt finalization now reject a second same-turn request synchronously rather than replacing/aborting the first before React can publish pending state.
- Document delivery sends have a synchronous admission guard while retaining reviewed preview token, explicit resend selection, uncertain-outcome refresh and existing ledger/server authorization behavior.
- Recovery loading handles browsers that block both reading and removing sessionStorage; a SecurityError no longer escapes workspace initialization. No raw-file fallback or new capability persistence was added.
- Expanded existing source-contract aggregation through the extracted modules. Original guards, endpoints, upload limits, classification/matching semantics, fresh previews and immutable lane ownership remain asserted.
- Existing browser spec expected a chooser/update dialog absent from baseline source. Rebased the synthetic fixture/assertions on current direct document-delivery preview, retaining filter/manual-upload/replacement, recipient eligibility, mobile viewport and no-provider-send checks. Both1440px and390px journeys pass.
- Fixed two additional proven display bugs: successful server passenger-search results now appear even when the base group list is empty; unavailable document URLs render filenames without an anchor that opens the current page. Added targeted search/download regressions.
- Removed the closed31-module retired WhatsApp/document welcome/recipient/update UI subtree and15 implementation-only tests after verifying no current app/framework root or literal/dynamic import consumer. Preserved active shared utilities, APIs/hooks, backend endpoints and the current five-page WhatsApp workspace. Original hashes, internal caller edges and exact paths are retained in documents-retired-files.json.
- Preserved the active portions of mixed tests: SourceContactTable pagination/search, recipient-delivery welcome gates and document eligibility/explicit resends. Removed only assertions/builders for retired implementations.

## Evidence

-54documents Node contracts passed.
-12dashboard transformation contracts passed after aggregation update.
-Post-cleanup document/shared-active unit run:15files/80tests passed, including upload lifecycle, blocked storage, delivery admission, search/download and retained shared gating/table coverage.
-Current WhatsApp browser QA:9passed, covering all five pages, preview/dispatch, failed-number correction,100-entry pagination, saved-message retry identity, scoped document filters/frozen send targets, reminder audiences and mobile overflow.
-TypeScript passed after extraction and final targeted tests.
-Document-wide ESLint checked; any later diagnostics are retained by final root checks.
-Budget candidates and measured complexity are in documents-budget-candidates.json for root integration; this lane did not edit the strict release-bound budget script.

## Coverage and architectural follow-up

Actual per-file content digests/notes are in documents-reviewed-files.json:46/46 current runtime files covered, plus targeted regression/fixture records. documents-review-pending.json is empty. Ten removed document runtime files were also read completely before removal; their original content hashes and review notes are retained in documents-retired-files.json. Retirement checks on the old WhatsApp subtree establish runtime unreachability; they do not claim a line-by-line security review of those removed WhatsApp implementations.

Remaining size/architecture work is explicit: document-rename-page.tsx558lines, document-workspace-dialogs.tsx547lines and document-workspace-review.tsx476lines were fully reviewed but remain candidates for coherent decomposition. Existing large service/hook modules also retain their earlier size budgets. No claim of repository-wide enterprise certification, exhaustive deployed security, or zero lag follows from this scoped review.

Caller evidence: app/(dashboard)/whatsapp/page.tsx imports WhatsAppPage, which dynamically loads workspace/broadcast-index.tsx; [broadcastId]/page.tsx imports workspace/send-message-page.tsx. Neither app nor the new workspace references oldwhatsapp-workspace, RecipientListDialog, the document recipient panel, TravellerWelcomePanel or DocumentUpdateDialog. The old recipient dialog was the only document-recipient-panel caller; it was reachable only from the retired old workspace. API endpoint strings containing recipient-roster are preserved as endpoints rather than mistaken for imports. Backend/MCP welcome/update endpoints remain intact; obsolete UI inventory identities are reconciled by the release/inventory lane.

Browser screenshots from the isolated current-flow fixture:

- C:/Users/nipun/Desktop/PassDetection/frontend/test-results/document-delivery-preview-1440.png
- C:/Users/nipun/Desktop/PassDetection/frontend/test-results/document-delivery-preview-390.png
