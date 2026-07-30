import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspace = readFileSync(new URL("./document-workspace.tsx", import.meta.url), "utf8");
const hooks = readFileSync(new URL("../hooks/use-document-distribution.ts", import.meta.url), "utf8");
const api = readFileSync(new URL("../api/document-distribution.api.ts", import.meta.url), "utf8");
const panel = readFileSync(new URL("../../passports/components/group-document-delivery-panel.tsx", import.meta.url), "utf8");
const groupPage = readFileSync(new URL("../../passports/components/passport-group-detail.tsx", import.meta.url), "utf8");
const endpoints = readFileSync(new URL("../../../lib/api/endpoints.ts", import.meta.url), "utf8");
const types = readFileSync(new URL("../../../types/document-distribution.types.ts", import.meta.url), "utf8");

test("saved document lists expose an explicit WhatsApp preview before sending", () => {
  assert.match(workspace, /Send WhatsApp Broadcast/);
  assert.match(workspace, /Preview WhatsApp document delivery/);
  assert.match(workspace, /Each passenger receives only the PDF shown in their row/);
  assert.match(workspace, /deliveryDocumentIds/);
  assert.match(workspace, /Successful and uncertain deliveries are excluded automatically/);
  assert.match(workspace, /documents_v1 preview/);
  assert.match(workspace, /Editable text 1/);
  assert.match(workspace, /Editable text 2/);
  assert.match(workspace, /row\.error_message/);
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
  assert.match(panel, /Visa, ticket, and travel-document WhatsApp delivery status/);
  assert.match(panel, /No document broadcasts sent yet/);
});

test("review tables keep one row per submitted passenger and nest saved documents", () => {
  assert.match(types, /documents: DistributedDocument\[\]/);
  assert.match(workspace, /const documents = reviewRowDocuments\(row\)/);
  assert.match(workspace, /<tr key=\{row\.passenger_id\}>/);
  assert.match(workspace, /\{documents\.length\} saved documents/);
  assert.doesNotMatch(workspace, /<tr key=\{row\.document\?\.id/);
});

test("document review exposes assignment counts, filters, and safe bulk removal choices", () => {
  assert.match(types, /visa_assigned_count: number/);
  assert.match(types, /flight_ticket_assigned_count: number/);
  assert.match(workspace, /Remove all assigned/);
  assert.match(workspace, /Keep saved PDFs/);
  assert.match(workspace, /Delete saved PDFs/);
  assert.match(workspace, /\["assigned", "Assigned"/);
  assert.match(workspace, /\["missing", "Missing"/);
  assert.match(workspace, /\["sent", "Sent"/);
  assert.match(workspace, /\["not_sent", "Not sent"/);
  assert.match(endpoints, /documents\/unassign/);
  assert.match(api, /unassignDocuments/);
  assert.match(hooks, /useUnassignDistributionDocuments/);
});
