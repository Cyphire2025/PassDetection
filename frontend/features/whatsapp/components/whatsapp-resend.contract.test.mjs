import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pageSource = readFileSync(
  new URL("./whatsapp-page.tsx", import.meta.url),
  "utf8",
);
const apiSource = readFileSync(
  new URL("../api/whatsapp.api.ts", import.meta.url),
  "utf8",
);
const hooksSource = readFileSync(
  new URL("../hooks/use-whatsapp.ts", import.meta.url),
  "utf8",
);
const endpointSource = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);

test("resend API targets exactly one recipient with the edited composer draft", () => {
  assert.match(
    endpointSource,
    /groups\/\$\{groupId\}\/recipients\/\$\{recipientId\}\/resend/,
  );

  const start = apiSource.indexOf("resendRecipientMessage: async");
  const end = apiSource.indexOf("previewMessage: async", start);
  const resendApi = apiSource.slice(start, end);
  assert.ok(start >= 0);
  assert.ok(end > start);
  assert.match(resendApi, /message_type: messageType/);
  assert.match(resendApi, /passport_intro:/);
  assert.match(resendApi, /passport_link:/);
  assert.match(resendApi, /message_content: messageContent/);
  assert.match(resendApi, /header_image_id: resolvedHeaderImageId/);
  assert.match(resendApi, /uploadWelcomeImage\(groupId, image\)/);
});

test("recipient details refresh after an accepted resend request", () => {
  const start = hooksSource.indexOf(
    "export function useResendWhatsAppRecipientMessage",
  );
  const end = hooksSource.indexOf(
    "export const WHATSAPP_BATCH_POLL_LIMIT_MS",
    start,
  );
  const resendHook = hooksSource.slice(start, end);
  assert.ok(start >= 0);
  assert.ok(end > start);
  assert.match(
    resendHook,
    /WHATSAPP_QUERY_KEYS\.group\(groupId\)/,
  );
  assert.match(resendHook, /invalidateQueries/);
});

test("only already-sent welcome and passport messages expose per-message resend", () => {
  assert.match(
    pageSource,
    /const knownMessageType =\s*isWhatsAppMessageType\(messageType\)/,
  );
  assert.match(
    pageSource,
    /knownMessageType\s*&& hasAlreadySentMessage\(recipient, messageType\)/,
  );
  assert.match(pageSource, /\{canResend && \(/);
  assert.match(
    pageSource,
    /return messageType === "welcome" \|\| messageType === "passport_link"/,
  );
});

test("resend opens the shared editor for one named recipient and is protected from double submission", () => {
  assert.match(pageSource, /<MessagePreviewDialog/);
  assert.match(pageSource, /targetRecipient=\{recipientToResend\}/);
  assert.match(pageSource, /targetRecipient \? "Resend" : "Preview"/);
  assert.match(
    pageSource,
    /No other recipient will\s+receive this resend\./,
  );
  assert.match(
    pageSource,
    /resend_recipient_id: targetRecipient\?\.recipientId \?\? null/,
  );
  assert.match(
    pageSource,
    /resendRecipientMessage\.isPending\s*\|\| resendInFlightRef\.current/,
  );
  assert.match(pageSource, /resendInFlightRef\.current = true/);
  assert.match(pageSource, /resendInFlightRef\.current = false/);
  assert.match(pageSource, /Resend to \$\{targetRecipient\.recipientName\}/);
});

test("opening the resend editor replaces the recipient-list modal instead of stacking two dialogs", () => {
  const start = pageSource.indexOf("function RecipientListDialog");
  const end = pageSource.indexOf("function DeliveryBadge", start);
  const recipientDialog = pageSource.slice(start, end);

  assert.ok(start >= 0);
  assert.ok(end > start);
  assert.match(recipientDialog, /!recipientToResend && \(\s*<DialogFrame/);
  assert.match(recipientDialog, /recipientToResend && \(\s*<MessagePreviewDialog/);
});

test("resend refreshes blocked delivery state and announces success or failure", () => {
  assert.match(hooksSource, /status\.resend_blocked/);
  assert.match(
    hooksSource,
    /status\.latest_resend_status === "queued"/,
  );
  assert.match(hooksSource, /\? 2_000\s*: false/);
  assert.match(pageSource, /await refetchGroup\(\)/);
  assert.match(pageSource, /messageStatus\?\.resend_blocked/);
  assert.match(pageSource, /latestResendStatus === "delivery_unknown"/);
  assert.match(pageSource, /Last resend failed/);
  assert.match(pageSource, />\s*Resent\s*</);
  assert.match(pageSource, /displayedResendNotice/);
  assert.match(pageSource, /role="status"/);
  assert.match(pageSource, /setResendError\(/);
  assert.match(pageSource, /setResendNotice\(/);
});
