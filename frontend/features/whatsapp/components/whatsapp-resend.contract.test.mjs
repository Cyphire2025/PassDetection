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

test("resend API targets exactly one recipient and sends only the selected message type", () => {
  assert.match(
    endpointSource,
    /groups\/\$\{groupId\}\/recipients\/\$\{recipientId\}\/resend/,
  );

  const start = apiSource.indexOf("resendRecipientMessage: async");
  const end = apiSource.indexOf("previewMessage: async", start);
  const resendApi = apiSource.slice(start, end);
  assert.ok(start >= 0);
  assert.ok(end > start);
  assert.match(resendApi, /\{ message_type: messageType \}/);
  assert.doesNotMatch(resendApi, /passport_link:\s|message_content:\s/);
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

test("resend requires named confirmation and is protected from double submission", () => {
  assert.match(pageSource, /title=\{`Resend \$\{formatMessageType/);
  assert.match(
    pageSource,
    /No other recipient will receive it\./,
  );
  assert.match(
    pageSource,
    /same passport link that was previously sent; ensure that link is still active/,
  );
  assert.match(
    pageSource,
    /resendRecipientMessage\.isPending\s*\|\| resendInFlightRef\.current/,
  );
  assert.match(pageSource, /resendInFlightRef\.current = true/);
  assert.match(pageSource, /resendInFlightRef\.current = false/);
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
