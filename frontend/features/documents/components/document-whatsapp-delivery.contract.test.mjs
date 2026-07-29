import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspace = readFileSync(new URL("./document-workspace.tsx", import.meta.url), "utf8");
const hooks = readFileSync(new URL("../hooks/use-document-distribution.ts", import.meta.url), "utf8");
const api = readFileSync(new URL("../api/document-distribution.api.ts", import.meta.url), "utf8");
const panel = readFileSync(new URL("../../passports/components/group-document-delivery-panel.tsx", import.meta.url), "utf8");
const groupPage = readFileSync(new URL("../../passports/components/passport-group-detail.tsx", import.meta.url), "utf8");
const endpoints = readFileSync(new URL("../../../lib/api/endpoints.ts", import.meta.url), "utf8");

test("saved document lists expose an explicit WhatsApp preview before sending", () => {
  assert.match(workspace, /Send WhatsApp Broadcast/);
  assert.match(workspace, /Preview WhatsApp document delivery/);
  assert.match(workspace, /Each passenger receives only the PDF shown in their row/);
  assert.match(workspace, /deliveryDocumentIds/);
  assert.match(workspace, /Successful and uncertain deliveries are excluded automatically/);
  assert.match(workspace, /documents_v1 preview/);
  assert.match(workspace, /Editable text 1/);
  assert.match(workspace, /Editable text 2/);
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
