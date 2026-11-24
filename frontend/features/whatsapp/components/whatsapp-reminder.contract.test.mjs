import assert from "node:assert/strict";
import test from "node:test";
import { readWhatsAppSource as read, readComposerControllerSource, readComposerAudienceSource } from "./whatsapp-source.contract-helper.mjs";

const page = read("../workspace/send-message-page.tsx");
const composer = readComposerControllerSource();
const audience = readComposerAudienceSource();
const dispatch = read("../workspace/composer.api.ts");

test("the live library obtains approved message definitions and passes the selected definition to its composer", () => {
  assert.match(page, /composerApi\.catalog\(signal\)/);
  assert.match(page, /definition=\{selected\}/);
  assert.match(page, /reminder: BellRing/);
  assert.match(dispatch, /message-catalog/);
  assert.match(composer, /definition\.message_type/);
  assert.match(composer, /definition\.fields\.map/);
});

test("a not-submitted reminder resolves an active linked group before requesting a preview", () => {
  assert.match(audience, /Only people who haven’t submitted/);
  assert.match(audience, /value: "all" as const, label: "Everyone"/);
  assert.match(composer, /item\.status === "active"/);
  assert.match(composer, /activeLinks\.length === 1 \? activeLinks\[0\]\.id : null/);
  assert.match(composer, /state\.reminderAudience !== "not_submitted" \|\| Boolean\(reminderGroupId\)/);
  assert.match(composer, /enabled: !group\.is_archived && audienceReady && eligible\.length > 0/);
  assert.match(composer, /audience_client_group_id:\s*state\.reminderAudience === "not_submitted" \? reminderGroupId : null/);
});

test("the audience is the intersection of locally eligible people and server-confirmed preview IDs", () => {
  assert.match(composer, /new Set\(preview\.data\.audience_recipient_ids\)/);
  assert.match(composer, /!audienceIds \|\| audienceIds\.has\(recipient\.id\)/);
  assert.match(composer, /recipientIds: selected\.map\(\(recipient\) => recipient\.id\)/);
  assert.match(audience, /recipientIds: null,[\s\S]*previewRecipientId: null/);
});
