import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync(
  new URL("./group-whatsapp-broadcast-panel.tsx", import.meta.url),
  "utf8",
);
const selector = readFileSync(
  new URL("./whatsapp-broadcast-selector.tsx", import.meta.url),
  "utf8",
);
const api = readFileSync(
  new URL("../api/upload-links.api.ts", import.meta.url),
  "utf8",
);
const hooks = readFileSync(
  new URL("../hooks/use-upload-links.ts", import.meta.url),
  "utf8",
);
const passportApi = readFileSync(
  new URL("../api/passports.api.ts", import.meta.url),
  "utf8",
);
const passportHooks = readFileSync(
  new URL("../hooks/use-passports.ts", import.meta.url),
  "utf8",
);
const endpoints = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);
const routes = readFileSync(
  new URL("../../../constants/routes.ts", import.meta.url),
  "utf8",
);
const trackingPage = readFileSync(
  new URL(
    "../../../app/(dashboard)/passports/groups/[groupId]/whatsapp/page.tsx",
    import.meta.url,
  ),
  "utf8",
);

test("broadcast choices come only from agency-scoped group-link endpoints", () => {
  assert.match(
    endpoints,
    /whatsappBroadcastOptions: "\/api\/v1\/upload-links\/whatsapp-broadcast-options"/,
  );
  assert.match(
    endpoints,
    /groupWhatsAppBroadcastOptions:[\s\S]*?whatsapp-broadcast-options/,
  );
  assert.match(
    api,
    /getWhatsAppBroadcastOptions:[\s\S]*?groupWhatsAppBroadcastOptions\(id\)[\s\S]*?whatsappBroadcastOptions/,
  );
  assert.match(selector, /useWhatsAppBroadcastOptions\(groupId\)/);
  assert.doesNotMatch(selector, /useWhatsAppGroups/);
});

test("existing groups replace linked broadcasts through an explicit PUT", () => {
  assert.match(
    api,
    /apiClient\.put<GroupWhatsAppLinksResponse>[\s\S]*?whatsapp_broadcast_group_ids/,
  );
  assert.match(panel, /Save linked broadcasts/);
  assert.match(panel, /Unlink every WhatsApp broadcast\?/);
  assert.match(panel, /Unlink all broadcasts/);
  assert.match(hooks, /useUpdateGroupWhatsAppLinks/);
});

test("comparison exposes multi-field identity evidence and review outcomes", () => {
  assert.match(api, /total_recipients: number/);
  assert.match(api, /submitted_count: number/);
  assert.match(api, /not_submitted_count: number/);
  assert.match(api, /multiple_submission_count: number/);
  assert.match(api, /matched_submission_count: number/);
  assert.match(api, /needs_review_count: number/);
  assert.match(api, /unmatched_submission_count: number/);
  assert.match(api, /match_evidence: GroupWhatsAppMatchEvidence\[\]/);
  assert.match(api, /recipient_fields: GroupWhatsAppRecipientFields\[\]/);
  assert.match(
    panel,
    /phone numbers, emails, passport numbers, staff codes/,
  );
  assert.match(panel, /broadcast_names\.map/);
  assert.match(panel, /submission_names\.join/);
  assert.match(panel, /Name entered in form/);
  assert.match(panel, /Name read from passport/);
  assert.match(panel, /Unidentified uploads/);
  assert.match(panel, /Needs review/);
  assert.doesNotMatch(panel, /Matched by exact phone number/);
});

test("comparison rows are paginated while aggregate counts remain visible", () => {
  assert.match(api, /page\?: number/);
  assert.match(api, /page_size\?: number/);
  assert.match(api, /total_pages: number/);
  assert.match(panel, /page: matchPage/);
  assert.match(panel, /page_size: matchPageSize/);
  assert.match(panel, /matchesQuery\.data\.total/);
  assert.match(panel, /matchesQuery\.data\.total_pages/);
  assert.match(panel, /submissionRate/);
  assert.match(panel, /submitted_count \?\? null/);
  assert.match(panel, /not_submitted_count \?\? null/);
  assert.match(panel, /multiple_submission_count \?\? null/);
  assert.match(panel, /value === null \? "—"/);
  assert.match(
    hooks,
    /useGroupWhatsAppMatches[\s\S]*?refetchInterval: 30_000/,
  );
});

test("manage actions follow backend authorization instead of inferred roles", () => {
  assert.match(api, /can_manage: boolean/);
  assert.match(panel, /const canManage = Boolean\(links\?\.can_manage\)/);
  assert.match(panel, /\{canManage && \(/);
  assert.match(
    hooks,
    /useGroupWhatsAppLinks[\s\S]*?refetchInterval: 30_000/,
  );
});

test("the group page stays compact and opens full tracking on a dedicated route", () => {
  assert.match(panel, /mode="summary"/);
  assert.match(panel, /WhatsApp broadcasts/);
  assert.match(panel, /links\?\.broadcasts\.map/);
  assert.match(panel, /\{broadcast\.name\}/);
  assert.match(panel, /View tracking/);
  assert.match(
    routes,
    /passportGroupWhatsAppTracking:[\s\S]*?\/whatsapp/,
  );
  assert.match(
    trackingPage,
    /GroupWhatsAppBroadcastTrackingPage groupId=\{groupId\}/,
  );
  assert.match(panel, /mode="tracking"/);
});

test("full tracking can filter unique recipients by a linked broadcast", () => {
  assert.match(api, /broadcast_id\?: string/);
  assert.match(api, /selected_broadcast_id: string \| null/);
  assert.match(panel, /broadcast_id: broadcastFilter/);
  assert.match(panel, /All linked broadcasts/);
  assert.match(panel, /whatsapp-broadcast-filter/);
  assert.match(panel, /links\?\.broadcasts\.length \?\? 0\) > 1/);
});

test("unidentified uploads can be resolved as replacements or removed safely", () => {
  assert.match(
    endpoints,
    /replacementCandidates:[\s\S]*?\/replacement-candidates/,
  );
  assert.match(
    endpoints,
    /resolveUnidentifiedReplacement:[\s\S]*?\/unidentified\/\$\{submissionId\}\/replacement/,
  );
  assert.match(
    endpoints,
    /rejectUnidentifiedUpload:[\s\S]*?\/unidentified\/\$\{submissionId\}\/reject/,
  );
  assert.match(api, /recipient_id: recipientId, request_id: requestId/);
  assert.match(api, /\{ request_id: requestId \}/);
  assert.match(hooks, /useResolveUnidentifiedReplacement/);
  assert.match(hooks, /useRejectUnidentifiedUpload/);
  assert.match(panel, /Mark as replacement/);
  assert.match(panel, /Reject\/remove/);
  assert.match(panel, /Find the original recipient/);
  assert.match(panel, /Confirm replacement/);
});

test("replacement decisions remain visible, detailed, and reversible", () => {
  assert.match(api, /\| "replacement"/);
  assert.match(api, /\| "rejected_upload"/);
  assert.match(api, /replacement_count: number/);
  assert.match(api, /rejected_upload_count: number/);
  assert.match(api, /submission_details: GroupWhatsAppSubmissionDetail\[\]/);
  assert.match(api, /resolution_id: string \| null/);
  assert.match(
    endpoints,
    /restoreRosterResolution:[\s\S]*?\/roster-resolutions\/\$\{resolutionId\}\/restore/,
  );
  assert.match(hooks, /useRestoreRosterResolution/);
  assert.match(panel, /label: "Replaced"/);
  assert.match(panel, /label: "Removed uploads"/);
  assert.match(panel, /View submitted details/);
  assert.match(panel, /Restore original person/);
  assert.match(panel, /Add upload back/);
});

test("unidentified filter explains who appears there", () => {
  assert.match(
    panel,
    /People who uploaded their details but are not in the linked WhatsApp broadcast lists\./,
  );
  assert.match(panel, /role="tooltip"/);
  assert.match(panel, /group-hover\/filter:block/);
  assert.match(panel, /group-focus-within\/filter:block/);
});

test("every tracking filter can export its complete Excel view", () => {
  assert.match(
    endpoints,
    /groupWhatsAppTrackingExport:[\s\S]*?whatsapp-tracking\/export\.xlsx/,
  );
  assert.match(
    passportApi,
    /exportWhatsAppTracking:[\s\S]*?status,[\s\S]*?broadcast_id: broadcastId/,
  );
  assert.match(passportHooks, /useExportWhatsAppTracking/);
  assert.match(panel, /status: matchFilter/);
  assert.match(
    panel,
    /broadcastId: broadcastFilter === "all"[\s\S]*?broadcastFilter/,
  );
  assert.match(panel, /Export Excel/);
  assert.match(panel, /Exporting/);
});
