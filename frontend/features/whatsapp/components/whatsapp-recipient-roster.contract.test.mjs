import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const featureDirectory = path.resolve(currentDirectory, "..");
const frontendDirectory = path.resolve(featureDirectory, "../..");

const pageSource = fs.readFileSync(
  path.join(currentDirectory, "whatsapp-page.tsx"),
  "utf8",
);
const apiSource = fs.readFileSync(
  path.join(featureDirectory, "api/whatsapp.api.ts"),
  "utf8",
);
const hooksSource = fs.readFileSync(
  path.join(featureDirectory, "hooks/use-whatsapp.ts"),
  "utf8",
);
const rosterSource = fs.readFileSync(
  path.join(featureDirectory, "utils/recipient-roster.ts"),
  "utf8",
);
const endpointsSource = fs.readFileSync(
  path.join(frontendDirectory, "lib/api/endpoints.ts"),
  "utf8",
);

test("recipient dialog loads the unified valid and rejected roster endpoint", () => {
  assert.match(endpointsSource, /recipientRoster:[\s\S]*recipient-roster/);
  assert.match(apiSource, /recipientRoster: async[\s\S]*API_ENDPOINTS\.whatsapp\.recipientRoster/);
  assert.match(hooksSource, /export function useWhatsAppRecipientRoster/);
  assert.match(pageSource, /useWhatsAppRecipientRoster\(group\.id\)/);
  assert.match(pageSource, /recipientRoster\.items/);
});

test("recipient dialog exposes All, Sent, Failed, and Rejected tabs with server counts", () => {
  assert.match(pageSource, /\{ id: "all", label: "All" \}/);
  assert.match(pageSource, /\{ id: "sent", label: "Sent" \}/);
  assert.match(pageSource, /\{ id: "failed", label: "Failed" \}/);
  assert.match(pageSource, /\{ id: "rejected", label: "Rejected" \}/);
  assert.match(pageSource, /role="tablist"/);
  assert.match(pageSource, /role="tab"/);
  assert.match(pageSource, /recipientRoster\?\.counts\[tab\.id\] \?\? 0/);
  assert.match(pageSource, /filterRecipientRosterItems\(/);
});

test("roster filtering preserves overlapping sent and failed outcomes", () => {
  assert.match(
    rosterSource,
    /recipient\.message_statuses\.some\(\(status\) => status\.already_sent\)/,
  );
  assert.match(rosterSource, /status\.status === "failed"/);
  assert.match(rosterSource, /status\.latest_resend_status === "failed"/);
  assert.match(
    rosterSource,
    /tab === "sent"[\s\S]*recipientHasSentMessage[\s\S]*recipientHasFailedMessage/,
  );
});

test("all roster rows keep durable import order and receive visible serial numbers", () => {
  assert.match(rosterSource, /left\.item\.display_order - right\.item\.display_order/);
  assert.match(pageSource, /visibleRosterItems\.map\(\(item, index\) =>/);
  assert.match(pageSource, /const serialNumber = index \+ 1/);
  assert.match(pageSource, />#<\/th>/);
  assert.match(pageSource, /serialNumber=\{serialNumber\}/);
  assert.match(pageSource, /\{serialNumber\}/);
});

test("rejected rows remain correctable inside the same filtered roster", () => {
  assert.match(pageSource, /item\.kind === "rejected"/);
  assert.match(pageSource, /<RejectedRosterRows/);
  assert.match(pageSource, /Save and add/);
  assert.match(pageSource, /resolveRejectedContact\.mutateAsync/);
});
