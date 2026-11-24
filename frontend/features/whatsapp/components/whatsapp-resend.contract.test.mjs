import assert from "node:assert/strict";
import test from "node:test";
import { readWhatsAppSource as read } from "./whatsapp-source.contract-helper.mjs";

const history = read("../workspace/history.api.ts");
const resend = read("../workspace/historical-resend-dialog.tsx");
const report = read("../workspace/message-delivery-report.tsx");
const controls = read("../workspace/recipient-controls.tsx");
const hooks = read("../hooks/use-broadcast-queries.ts");
const facade = read("../hooks/use-whatsapp.ts");

test("historical resend names exactly one recipient and retains its original message identity", () => {
  assert.match(history, /resendRecipientMessage\(\s*groupId,\s*recipient\.recipient_id/);
  assert.match(history, /source_message_log_id: recipient\.message_log_id/);
  assert.match(history, /request_id: requestId/);
  assert.match(resend, /Only \$\{recipient\.name \|\| "this recipient"\} will receive this message/);
  assert.match(resend, /recipient\.current_phone_number/);
  assert.match(resend, /recipient\.rendered_message \|\| entry\.message_preview/);
});

test("document history uses its dedicated resend route without a broadcast message override", () => {
  assert.match(history, /messageType === "document_update"[\s\S]*resend-update/);
  assert.match(history, /messageType === "document_update"\s*\? \{\}\s*: \{ message_type: messageType \}/);
});

test("resend has one retained request ID, synchronous single-flight protection, and no automatic retry", () => {
  assert.match(resend, /useState\(\(\) => crypto\.randomUUID\(\)\)/);
  assert.match(resend, /if \(lock\.current\) return/);
  assert.match(resend, /lock\.current = true/);
  assert.match(resend, /lock\.current = false/);
  assert.match(resend, /retry: false/);
  assert.match(resend, /recipient\.status === "failed" \? "Retry" : "Resend"/);
});

test("accepted resends refresh current history and groups and announce the recorded request", () => {
  assert.match(resend, /queryKey: \["whatsapp", "history", groupId\]/);
  assert.match(resend, /queryKey: \["whatsapp", "groups"\]/);
  assert.match(resend, /role="status"/);
  assert.match(resend, /Track its current status in Delivery history/);
  assert.match(report, /refetchInterval: 10_000/);
  assert.match(report, /!recipient\.can_resend \|\| !summary\.data/);
  assert.match(report, /<HistoricalResend/);
});

test("the current recipient editor uses the scoped phone update and refreshes history", () => {
  assert.match(facade, /from "\.\/use-broadcast-queries"/);
  assert.match(controls, /useUpdateWhatsAppRecipientPhone/);
  assert.match(controls, /mutation\.mutateAsync\(\{ groupId, recipientId, phoneNumber \}\)/);
  assert.match(controls, /queryKey: \["whatsapp", "history", groupId\]/);
  assert.match(hooks, /whatsappRecipientPollInterval/);
});
