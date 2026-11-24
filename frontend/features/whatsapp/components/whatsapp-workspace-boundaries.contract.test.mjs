import assert from "node:assert/strict";
import test from "node:test";
import { readWhatsAppSource as read } from "./whatsapp-source.contract-helper.mjs";

const route = read("./whatsapp-page.tsx");
const shell = read("../workspace/broadcast-workspace-shell.tsx");
const index = read("../workspace/broadcast-index.tsx");
const create = read("./whatsapp-create-broadcast-dialog.tsx");
const add = read("../workspace/add-recipients-dialog.tsx");
const imported = read("./whatsapp-recipient-import.tsx");
const importHook = read("../hooks/use-recipient-excel-preview.ts");

test("the active WhatsApp index remains behind the route loading boundary", () => {
  assert.match(route, /dynamic\(/);
  assert.match(route, /import\("\.\.\/workspace\/broadcast-index"\)/);
  assert.match(index, /CreateBroadcastDialog/);
  assert.match(shell, /createContext<WhatsAppBroadcastGroupDetail \| null>/);
  assert.match(shell, /key=\{pathname\}/);
});

test("live create and add flows share exactly one recipient Excel preview implementation", () => {
  assert.match(imported, /export \{ useRecipientExcelPreview \} from "\.\.\/hooks\/use-recipient-excel-preview"/);
  assert.match(importHook, /export function useRecipientExcelPreview/);
  assert.match(create, /from "\.\/whatsapp-recipient-import"/);
  assert.match(add, /from "\.\.\/components\/whatsapp-recipient-import"/);
  assert.doesNotMatch(create, /function useRecipientExcelPreview/);
  assert.doesNotMatch(add, /function useRecipientExcelPreview/);
});

test("the current index clamps filtered pages and exposes recovery without losing archived history", () => {
  assert.match(index, /useWhatsAppGroups\(true\)/);
  assert.match(index, /useDeferredValue\(search\)/);
  assert.match(index, /const pageOffset = clampPageOffset\(offset, groups\.length, 20\)/);
  assert.match(index, /groups\.slice\(pageOffset, pageOffset \+ 20\)/);
  assert.match(index, /source\.refetch\(\)/);
  assert.match(shell, /group\.is_archived/);
});
