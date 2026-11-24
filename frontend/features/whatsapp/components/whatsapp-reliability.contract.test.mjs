import assert from "node:assert/strict";
import test from "node:test";
import { readWhatsAppSource as read, readWhatsAppApiSource, readComposerControllerSource, readComposerViewSource, readComposerAudienceSource } from "./whatsapp-source.contract-helper.mjs";

const composer = readComposerControllerSource();
const editor = readComposerViewSource();
const audience = readComposerAudienceSource();
const create = read("./whatsapp-create-broadcast-dialog.tsx");
const add = read("../workspace/add-recipients-dialog.tsx");
const importFacade = read("./whatsapp-recipient-import.tsx");
const imported = read("../hooks/use-recipient-excel-preview.ts");
const importView = read("./excel-recipient-import.tsx");
const rejectedRows = read("./rejected-import-rows.tsx");
const dialog = read("./whatsapp-dialog-ui.tsx");
const api = readWhatsAppApiSource();

test("current create, add, and send actions have synchronous single-flight guards", () => {
  assert.match(create, /if \(isLoading \|\| submitInFlightRef\.current\) return/);
  assert.match(add, /if \(lock\.current \|\| !ready\) return/);
  assert.match(add, /lock\.current = false/);
  assert.match(composer, /if \(sending\.current \|\| \(!ready && !\(retryPrevious && recovery\)\)\) return/);
  assert.match(composer, /sending\.current = false/);
});

test("superseded previews receive query cancellation and cannot authorize the latest draft", () => {
  assert.match(composer, /queryFn: \(\{ signal \}\) =>\s*whatsappApi\.previewMessage\(group\.id, debouncedDraft, signal\)/);
  assert.match(composer, /currentKey === debouncedKey/);
  assert.match(composer, /!preview\.isPlaceholderData[\s\S]*!preview\.isFetching[\s\S]*!preview\.error/);
  assert.match(composer, /gcTime: 0,[\s\S]*retry: false/);
  assert.match(api, /previewMessage: async \(\s*groupId: string,\s*draft: WhatsAppMessageDraft,\s*signal\?: AbortSignal/);
});

test("the live send gate requires reviewed content, approval, consent, welcome delivery and an active broadcast", () => {
  const gate = composer.slice(composer.indexOf("const ready = Boolean("), composer.indexOf("useEffect(", composer.indexOf("const ready = Boolean(")));
  for (const expression of ["current", "selected.length > 0", "fieldReady", "definition.image_required", "!preview.data?.welcome_required_count", "preview.data?.template_name", "group.recipient_opt_in_confirmed", "!group.is_archived", "!mutation.isPending", "!imageError"]) assert.ok(gate.includes(expression), expression);
  assert.match(editor, /disabled=\{!model\.ready && !model\.recovery\}/);
});

test("an unconfirmed transport request retains its exact payload and reviewed snapshot for recovery", () => {
  assert.match(composer, /retryPrevious && recovery\s*\? recovery/);
  assert.match(composer, /else setRecovery\(variables\)/);
  assert.match(composer, /cause instanceof UncertainWhatsAppSendError/);
  assert.match(composer, /reviewedMessage: recovery\s*\? reviewedSend\?\.message/);
  assert.match(editor, /Boolean\(model\.uncertain\)/);
});

test("WhatsApp dialogs expose modal semantics and announce errors", () => {
  assert.match(dialog, /role="dialog"/);
  assert.match(dialog, /aria-modal="true"/);
  assert.match(dialog, /aria-labelledby=\{titleId\}/);
  assert.match(dialog, /role="alert"/);
  assert.match(dialog, /disabled=\{isBusy\}/);
});

test("mixed Excel previews preserve rejected rows and imported headings in both live mutation flows", () => {
  assert.match(importFacade, /export \{ useRecipientExcelPreview \} from "\.\.\/hooks\/use-recipient-excel-preview"/);
  assert.match(importFacade, /export \{ ExcelRecipientImport \} from "\.\/excel-recipient-import"/);
  assert.match(imported, /mergeRecipientImportPreview\(/);
  assert.match(imported, /mergeRecipientImportRejectedRows\(/);
  assert.match(imported, /mergeRecipientImportMatchingFields\(/);
  assert.match(importView, /<RejectedImportRows rows=\{state\.rejectedRows\}/);
  assert.match(rejectedRows, /rows\.slice\(pageOffset, pageOffset \+ 50\)/);
  for (const source of [create, add]) {
    assert.match(source, /toRejectedContactInputs\(/);
    assert.match(source, /importedFieldKeys/);
  }
  assert.equal(api.match(/JSON\.stringify\(rejectedContacts\)/g)?.length, 2);
  assert.equal(api.match(/formData\.append\("imported_field_keys_json", JSON\.stringify\(importedFieldKeys \?\? \[\]\)\)/g)?.length, 2);
});

test("the live composer uses one support contact and bounded searchable selection", () => {
  assert.match(composer, /\? \[state\.supportContactId\]/);
  assert.match(editor, /value=\{model\.state\.supportContactId \?\? ""\}/);
  assert.match(audience, /new Set\(model\.selectedIds\)/);
  assert.match(audience, /selected\.has\(recipient\.id\)/);
  assert.match(audience, /useDeferredValue\(search\)/);
  assert.match(audience, /WorkspacePagination/);
});
