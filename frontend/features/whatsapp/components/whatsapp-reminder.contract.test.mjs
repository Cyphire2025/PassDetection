import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { whatsappFeatureSource } from "./whatsapp-source.contract-helper.mjs";

const page = whatsappFeatureSource;
const api = readFileSync(new URL("../api/whatsapp.api.ts", import.meta.url), "utf8");
const audience = readFileSync(
  new URL("./whatsapp-reminder-audience.tsx", import.meta.url),
  "utf8",
);
const preview = readFileSync(
  new URL("./whatsapp-message-preview-dialog.tsx", import.meta.url),
  "utf8",
);

test("reminder_v1 is a separate broadcast option with one editable paragraph", () => {
  assert.match(page, /Send Reminder/);
  assert.match(page, /openMessagePreview\(group, "reminder"\)/);
  assert.match(page, /Edit the reminder paragraph below/);
  assert.match(page, /The header, greeting, and\s+sign-off are fixed in the approved template/);
  assert.match(page, /messageType !== "reminder" &&/);
  assert.match(api, /message_type: "reminder"/);
  assert.match(api, /sendReminder/);
});

test("each reviewed reminder can target everyone or one linked group's not-submitted people", () => {
  assert.match(audience, /Send to everyone/);
  assert.match(audience, /Only people who haven&apos;t submitted/);
  assert.match(audience, /Passport upload group used to check submissions/);
  assert.match(audience, /ambiguous matches are both excluded/);
  assert.match(api, /audience\?: WhatsAppReminderAudience/);
  assert.match(api, /audience_client_group_id\?: string \| null/);
  assert.match(api, /excluded_needs_review_count\?: number/);
  assert.match(api, /recipient_ids: recipientIds,[\s\S]*?audience,[\s\S]*?audience_client_group_id/);
  assert.match(preview, /reminderAudienceConfirmed/);
  assert.match(preview, /server did not confirm the not-submitted audience/);
  assert.match(preview, /Send to \$\{eligibleRecipientCount\} not submitted/);
});
