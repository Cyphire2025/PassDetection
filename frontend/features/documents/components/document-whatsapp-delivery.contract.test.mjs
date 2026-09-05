import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { readDocumentWorkspaceSource } from "./document-workspace-source.contract-helper.mjs";

const workspace = readDocumentWorkspaceSource();
const workspaceDialogs = readFileSync(
  new URL("./document-workspace-dialogs.tsx", import.meta.url),
  "utf8",
);
const workspaceReview = readFileSync(
  new URL("./document-workspace-review.tsx", import.meta.url),
  "utf8",
);
const hooks = readFileSync(new URL("../hooks/use-document-distribution.ts", import.meta.url), "utf8");
const api = readFileSync(new URL("../api/document-distribution.api.ts", import.meta.url), "utf8");
const panel = readFileSync(new URL("../../passports/components/group-document-delivery-panel.tsx", import.meta.url), "utf8");
import { passportGroupDetailSource as groupPage } from "../../passports/components/passport-group-detail-source.contract-helper.mjs";
const endpoints = readFileSync(new URL("../../../lib/api/endpoints.ts", import.meta.url), "utf8");
const types = readFileSync(new URL("../../../types/document-distribution.types.ts", import.meta.url), "utf8");
const lanes = readFileSync(
  new URL("../config/document-distribution-lanes.ts", import.meta.url),
  "utf8",
);

test("saved document lists expose an explicit WhatsApp preview before sending", () => {
  assert.match(workspace, /Send WhatsApp Broadcast/);
  assert.match(workspaceDialogs, /Preview WhatsApp document delivery/);
  assert.match(workspaceDialogs, /Each passenger receives only the PDF shown in their row/);
  assert.match(workspace, /deliveryDocumentIds/);
  assert.match(workspaceDialogs, /Successful and uncertain deliveries are excluded automatically/);
  assert.match(workspaceDialogs, /documents_v1 preview/);
  assert.match(workspaceDialogs, /Editable text 1/);
  assert.match(workspaceDialogs, /Editable text 2/);
  assert.match(workspaceDialogs, /row\.error_message/);
});

test("frontend uses dedicated preview, send, and tracking contracts", () => {
  assert.match(endpoints, /whatsappPreview/);
  assert.match(endpoints, /whatsapp-send/);
  assert.match(endpoints, /whatsapp-deliveries\/tracking/);
  assert.match(api, /previewWhatsAppDelivery/);
  assert.match(api, /sendWhatsAppDelivery/);
  assert.match(api, /message_content_1/);
  assert.match(api, /message_content_2/);
  assert.match(api, /getDeliveryTracking/);
  assert.match(hooks, /useDocumentDeliveryPreview/);
  assert.match(hooks, /useSendDocumentWhatsAppBroadcast/);
  assert.match(hooks, /useDocumentDeliveryTracking/);
});

test("group details include compact document delivery management", () => {
  assert.match(groupPage, /GroupDocumentDeliveryPanel groupId=\{groupId\}/);
  assert.match(panel, /Document delivery tracking/);
  assert.match(panel, /Manage deliveries/);
  assert.match(panel, /Visa and International or Domestic Onward\/Return ticket WhatsApp delivery status/);
  assert.match(panel, /No document broadcasts sent yet/);
});

test("review tables keep one row per submitted passenger and nest saved documents", () => {
  assert.match(types, /documents: DistributedDocument\[\]/);
  assert.match(workspace, /documentsByPassengerId\.get\(row\.passenger_id\) \?\? \[\]/);
  assert.match(workspace, /<tr key=\{row\.passenger_id\}>/);
  assert.match(workspace, /\{documents\.length\} saved documents/);
  assert.doesNotMatch(workspace, /<tr key=\{row\.document\?\.id/);
});

test("document review exposes assignment counts, filters, and safe bulk removal choices", () => {
  assert.match(types, /visa_assigned_count: number/);
  assert.match(types, /flight_ticket_assigned_count: number/);
  assert.match(types, /flight_ticket_arrival_assigned_count: number/);
  assert.match(types, /flight_ticket_domestic_assigned_count: number/);
  assert.match(types, /flight_ticket_domestic_arrival_assigned_count: number/);
  assert.match(lanes, /title: "International Onward"/);
  assert.match(lanes, /title: "International Return"/);
  assert.match(lanes, /title: "Domestic Onward"/);
  assert.match(lanes, /title: "Domestic Return"/);
  assert.doesNotMatch(workspace, /title: "Other"/);
  assert.match(workspace, /Remove all assigned/);
  assert.match(workspaceDialogs, /Keep saved PDFs/);
  assert.match(workspaceDialogs, /Delete saved PDFs/);
  assert.match(workspace, /\["assigned", "Assigned"/);
  assert.match(workspace, /\["missing", "Missing"/);
  assert.match(workspace, /\["sent", "Sent"/);
  assert.match(workspace, /\["not_sent", "Not sent"/);
  assert.match(endpoints, /documents\/unassign/);
  assert.match(api, /unassignDocuments/);
  assert.match(hooks, /useUnassignDistributionDocuments/);
});

test("document review supports passenger search and per-file assignment removal without a scroll-only action column", () => {
  assert.match(workspace, /Search passenger name/);
  assert.match(workspace, /row\.passenger_name\.toLocaleLowerCase\(\)\.includes/);
  assert.match(workspaceReview, /onRemoveAssignment\(document\.id\)/);
  assert.match(workspaceReview, /Remove assignment/);
  assert.match(workspace, /w-full table-fixed/);
  assert.doesNotMatch(workspace, /<div className="overflow-x-auto">\s*<table className="w-full text-left text-sm">/);
});
