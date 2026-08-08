import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspaceSource = readFileSync(
  new URL("./whatsapp-workspace.tsx", import.meta.url),
  "utf8",
);
const createSource = readFileSync(
  new URL("./whatsapp-create-broadcast-dialog.tsx", import.meta.url),
  "utf8",
);
const messageSource = readFileSync(
  new URL("./whatsapp-message-preview-dialog.tsx", import.meta.url),
  "utf8",
);
const recipientSource = readFileSync(
  new URL("./whatsapp-recipient-dialog.tsx", import.meta.url),
  "utf8",
);
const importSource = readFileSync(
  new URL("./whatsapp-recipient-import.tsx", import.meta.url),
  "utf8",
);

test("optional WhatsApp workflows remain behind dynamic loading boundaries", () => {
  assert.match(workspaceSource, /dynamic\([\s\S]*whatsapp-create-broadcast-dialog/);
  assert.match(workspaceSource, /dynamic\([\s\S]*whatsapp-message-preview-dialog/);
  assert.match(workspaceSource, /dynamic\([\s\S]*whatsapp-recipient-dialog/);
  assert.match(workspaceSource, /Loading broadcast editor/);
  assert.match(workspaceSource, /Loading message preview/);
  assert.match(workspaceSource, /Loading recipient list/);
  assert.doesNotMatch(workspaceSource, /function RecipientListDialog/);
  assert.doesNotMatch(workspaceSource, /function MessagePreviewDialog/);
  assert.doesNotMatch(workspaceSource, /function CreateBroadcastDialog/);
});

test("recipient import logic has one shared implementation", () => {
  assert.match(importSource, /export function useRecipientExcelPreview/);
  assert.match(createSource, /from "\.\/whatsapp-recipient-import"/);
  assert.match(recipientSource, /from "\.\/whatsapp-recipient-import"/);
  assert.doesNotMatch(createSource, /function useRecipientExcelPreview/);
  assert.doesNotMatch(messageSource, /function useRecipientExcelPreview/);
  assert.doesNotMatch(recipientSource, /function useRecipientExcelPreview/);
});

test("large recipient derivations are stable across unrelated dialog updates", () => {
  assert.match(recipientSource, /const messageTypes = useMemo\(/);
  assert.match(recipientSource, /new Set\(\[/);
  assert.match(recipientSource, /const visibleRosterItems = useMemo\(/);
  assert.match(recipientSource, /filterRecipientRosterItems\(/);
  assert.match(recipientSource, /const ROSTER_TABS:/);
});
