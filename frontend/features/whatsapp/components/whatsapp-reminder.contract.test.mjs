import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { whatsappFeatureSource } from "./whatsapp-source.contract-helper.mjs";

const page = whatsappFeatureSource;
const api = readFileSync(new URL("../api/whatsapp.api.ts", import.meta.url), "utf8");

test("reminder_v1 is a separate broadcast option with one editable paragraph", () => {
  assert.match(page, /Send Reminder/);
  assert.match(page, /openMessagePreview\(group, "reminder"\)/);
  assert.match(page, /Edit the reminder paragraph below/);
  assert.match(page, /The header, greeting, and\s+sign-off are fixed in the approved template/);
  assert.match(page, /messageType !== "reminder" &&/);
  assert.match(api, /message_type: "reminder"/);
  assert.match(api, /sendReminder/);
});
