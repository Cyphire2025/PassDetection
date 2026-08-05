import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const featureDirectory = path.resolve(currentDirectory, "..");
const frontendDirectory = path.resolve(featureDirectory, "../..");

const pageSource = fs.readFileSync(
  path.join(currentDirectory, "whatsapp-workspace.tsx"),
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

test("recipient dialog exposes active, rejected, unidentified, and replaced tabs with server counts", () => {
  assert.match(pageSource, /\{ id: "all", label: "All" \}/);
  assert.match(pageSource, /\{ id: "sent", label: "Sent" \}/);
  assert.match(pageSource, /\{ id: "failed", label: "Failed" \}/);
  assert.match(pageSource, /\{ id: "rejected", label: "Rejected" \}/);
  assert.match(pageSource, /id: "unidentified"[\s\S]*label: "Unidentified"/);
  assert.match(pageSource, /\{ id: "replaced", label: "Replaced" \}/);
  assert.match(pageSource, /role="tablist"/);
  assert.match(pageSource, /role="tab"/);
  assert.match(pageSource, /recipientRoster\?\.counts\[tab\.id\] \?\? 0/);
  assert.match(pageSource, /filterRecipientRosterItems\(/);
});

test("broadcast list shows the complete roster while delivery keeps the valid count", () => {
  assert.match(apiSource, /total_contact_count: number/);
  assert.match(pageSource, /\{group\.total_contact_count\}/);
  assert.match(pageSource, /group\.recipient_count === 0/);
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

test("replaced rows stay outside All and can restore the durable group decision", () => {
  assert.match(
    rosterSource,
    /tab === "all"[\s\S]*item\.kind === "recipient"[\s\S]*item\.kind === "rejected"/,
  );
  assert.match(rosterSource, /tab === "replaced"\) return item\.kind === "replaced"/);
  assert.match(apiSource, /interface WhatsAppReplacedRecipient/);
  assert.match(apiSource, /replacement_submission_id: string/);
  assert.match(apiSource, /client_group_name: string/);
  assert.match(
    apiSource,
    /restoreReplacedRecipient:[\s\S]*restoreRosterResolution/,
  );
  assert.match(hooksSource, /useRestoreWhatsAppReplacedRecipient/);
  assert.match(pageSource, /<ReplacedRosterRow/);
  assert.match(pageSource, /Restore \/ add back/);
  assert.match(
    pageSource,
    /cannot[\s\S]*receive further messages unless they are restored/,
  );
});

test("unidentified tab explains unmatched uploads and deep-links to resolution workflow", () => {
  assert.match(apiSource, /interface WhatsAppUnidentifiedUpload/);
  assert.match(apiSource, /kind: "unidentified"/);
  assert.match(apiSource, /unidentified: number/);
  assert.match(
    rosterSource,
    /tab === "unidentified"\) return item\.kind === "unidentified"/,
  );
  assert.match(
    pageSource,
    /People who uploaded passport details but are not in this WhatsApp broadcast\./,
  );
  assert.match(pageSource, /<UnidentifiedRosterRow/);
  assert.match(pageSource, /Review \/ mark replacement/);
  assert.match(
    pageSource,
    /\/passports\/groups\/\$\{upload\.client_group_id\}\/whatsapp/,
  );
});

test("restoring reconciles WhatsApp, passport tracking, and export history caches", () => {
  assert.match(
    hooksSource,
    /useRestoreWhatsAppReplacedRecipient[\s\S]*queryKey: \["whatsapp"\]/,
  );
  assert.match(
    hooksSource,
    /useRestoreWhatsAppReplacedRecipient[\s\S]*"whatsapp-matches"/,
  );
  assert.match(
    hooksSource,
    /useRestoreWhatsAppReplacedRecipient[\s\S]*"passport-export-history"/,
  );
});
