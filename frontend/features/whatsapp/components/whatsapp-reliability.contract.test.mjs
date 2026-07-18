import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pageSource = readFileSync(
  new URL("./whatsapp-page.tsx", import.meta.url),
  "utf8",
);
const dialogSource = readFileSync(
  new URL("./whatsapp-dialog-ui.tsx", import.meta.url),
  "utf8",
);
const apiSource = readFileSync(
  new URL("../api/whatsapp.api.ts", import.meta.url),
  "utf8",
);

test("create and send actions have synchronous single-flight guards", () => {
  assert.match(pageSource, /if \(isLoading \|\| submitInFlightRef\.current\) return;/);
  assert.match(pageSource, /if \(isSending \|\| sendInFlightRef\.current\) return;/);
  assert.match(pageSource, /submitInFlightRef\.current = false;/);
  assert.match(pageSource, /sendInFlightRef\.current = false;/);
});

test("changing a preview cancels the superseded HTTP request", () => {
  assert.match(pageSource, /const controller = new AbortController\(\);/);
  assert.match(pageSource, /signal: controller\.signal/);
  assert.match(pageSource, /controller\.abort\(\);/);
  assert.match(
    apiSource,
    /previewMessage: async \(\s*groupId: string,\s*draft: WhatsAppMessageDraft,\s*signal\?: AbortSignal,/,
  );
  assert.match(apiSource, /\{ signal \}/);
});

test("WhatsApp dialogs expose modal semantics and announce errors", () => {
  assert.match(dialogSource, /role="dialog"/);
  assert.match(dialogSource, /aria-modal="true"/);
  assert.match(dialogSource, /aria-labelledby=\{titleId\}/);
  assert.match(dialogSource, /role="alert"/);
  assert.match(dialogSource, /disabled=\{isBusy\}/);
});

test("broadcast creation asks for group name without an organisation field", () => {
  const start = pageSource.indexOf("function CreateBroadcastDialog");
  const end = pageSource.indexOf("function MessagePreviewDialog", start);
  const createDialog = pageSource.slice(start, end);

  assert.ok(start >= 0);
  assert.ok(end > start);
  assert.match(createDialog, /label="Group name"/);
  assert.doesNotMatch(
    createDialog,
    /organi[sz](?:ing|ation)|company name|organizing_company_name/i,
  );
});

test("approved-template guidance exposes the exact fixed header and body positions", () => {
  assert.match(
    pageSource,
    /approved Meta header is fixed as Dear Delegates/,
  );
  assert.match(
    pageSource,
    /messageType === "welcome" \? "\{\{1\}\}" : "\{\{3\}\}"/,
  );
  assert.match(
    pageSource,
    /passport upload link supplies BODY variable \{"\{\{2\}\}"\}/,
  );
  assert.match(
    pageSource,
    /Welcome trip message \(BODY \{\{1\}\}\)/,
  );
  assert.match(
    pageSource,
    /Passport instructions \(BODY \{\{3\}\}\)/,
  );
});

test("message preview remains unsendable while the latest approved rendering loads", () => {
  assert.match(
    pageSource,
    /disabled=\{!canSend \|\| previewRequest\.isPending\}/,
  );
  assert.match(pageSource, /eligibleRecipientCount > 0/);
  assert.match(pageSource, /detail\?\.recipient_opt_in_confirmed/);
  assert.match(pageSource, /detail\.support_contacts\.length > 0/);
});
