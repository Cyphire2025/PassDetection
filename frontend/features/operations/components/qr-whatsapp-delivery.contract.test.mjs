import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("./tour-group-qr-codes-page.tsx", import.meta.url), "utf8");
const hooks = readFileSync(new URL("../hooks/use-operations.ts", import.meta.url), "utf8");
const api = readFileSync(new URL("../api/operations.api.ts", import.meta.url), "utf8");
const endpoints = readFileSync(new URL("../../../lib/api/endpoints.ts", import.meta.url), "utf8");

test("QR page exposes an individual WhatsApp preview and selection workflow", () => {
  assert.match(page, /Send WhatsApp Broadcast/);
  assert.match(page, /Preview WhatsApp QR delivery/);
  assert.match(page, /Each passenger receives only the active QR shown in their row/);
  assert.match(page, /Send individually to/);
  assert.match(page, /Successful and uncertain deliveries are excluded automatically/);
  assert.match(page, /Editable message/);
});

test("frontend uses dedicated QR preview and send contracts", () => {
  assert.match(endpoints, /groupQrWhatsAppPreview/);
  assert.match(endpoints, /qr-codes\/whatsapp-preview/);
  assert.match(endpoints, /groupQrWhatsAppSend/);
  assert.match(api, /qrDeliveryPreview/);
  assert.match(api, /sendQrBroadcast/);
  assert.match(api, /message_content/);
  assert.match(hooks, /useQrDeliveryPreview/);
  assert.match(hooks, /useSendQrBroadcast/);
  assert.match(hooks, /refetchInterval: enabled \? 2_000 : false/);
  assert.match(page, /Delivery status refreshes automatically/);
});
