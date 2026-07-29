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
const hooksSource = readFileSync(
  new URL("../hooks/use-whatsapp.ts", import.meta.url),
  "utf8",
);
const endpointsSource = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
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

test("approved-template guidance exposes the required image and body positions", () => {
  assert.match(
    pageSource,
    /uploaded picture is the required Meta IMAGE header/,
  );
  assert.match(
    pageSource,
    /text\s+below supplies BODY variable \{"\{\{1\}\}"\}/,
  );
  assert.match(
    pageSource,
    /passport upload link\s+supplies BODY variable \{"\{\{2\}\}"\}/,
  );
  assert.match(
    pageSource,
    /Passport link introduction \(BODY \{"\{\{1\}\}"\}\)/,
  );
  assert.match(
    pageSource,
    /Welcome trip message \(BODY \{\{1\}\}\)/,
  );
  assert.match(
    pageSource,
    /Passport instructions \(BODY \{\{3\}\}\)/,
  );
  assert.match(pageSource, /\? "Welcome image"\s*: "Passport Link image"/);
  assert.match(pageSource, /const hasHeaderImage = Boolean\(headerImage \|\| headerImageId\)/);
  assert.match(pageSource, /required=\{!hasHeaderImage\}/);
  assert.match(pageSource, /Previously sent image selected/);
  assert.match(apiSource, /header_image_id: resolvedHeaderImageId/);
  assert.match(apiSource, /passport_intro: passportIntro/);
});

test("recipient lists retain and expose imported spreadsheet details", () => {
  assert.match(apiSource, /imported_fields: Record<string, string>/);
  assert.match(pageSource, /recipient\.imported_fields/);
  assert.match(pageSource, /importedFieldLabel/);
  assert.match(pageSource, /imported detail/);
  assert.match(dialogSource, /contact\.imported_fields/);
});

test("mixed Excel previews keep accepted recipients and expose every rejected source row", () => {
  assert.match(apiSource, /RecipientImportPreview/);
  assert.match(pageSource, /mergeRecipientImportPreview\(/);
  assert.match(pageSource, /state\.rejectedRows\.map/);
  assert.match(pageSource, /row\.sheet_name/);
  assert.match(pageSource, /row\.row_number/);
  assert.match(pageSource, /row\.raw_name/);
  assert.match(pageSource, /row\.raw_phone_number/);
  assert.match(pageSource, /row\.reason/);
  assert.match(pageSource, /Valid recipients were kept/);
  assert.match(pageSource, /state\.rejectedRowsTruncated/);
  assert.match(pageSource, /role="status"/);
  assert.match(pageSource, /aria-label="Rejected spreadsheet rows"/);
  assert.doesNotMatch(pageSource, /<div aria-live="polite">/);
});

test("create and add flows persist rejected contacts separately from valid recipients", () => {
  assert.match(apiSource, /rejected_contacts_json/);
  assert.equal(apiSource.match(/JSON\.stringify\(rejectedContacts\)/g)?.length, 2);
  assert.match(pageSource, /toRejectedContactInputs\(rejectedContacts\)/);
  assert.match(
    pageSource,
    /contacts\.length === 0 && rejectedContacts\.length === 0/,
  );
  assert.match(pageSource, /mergeRecipientImportRejectedRows\(/);
  assert.match(pageSource, /source_file_name: contact\.source_file_name/);
});

test("saved rejected contacts are loaded in the unified ordered recipient roster", () => {
  assert.match(endpointsSource, /recipient-roster/);
  assert.match(
    apiSource,
    /type WhatsAppRecipientRosterItem[\s\S]*kind: "recipient"[\s\S]*kind: "rejected"/,
  );
  assert.match(apiSource, /display_order: number/);
  assert.match(apiSource, /rejected_contact: WhatsAppRejectedContact/);
  assert.match(apiSource, /counts:[\s\S]*all: number[\s\S]*rejected: number/);
  assert.match(hooksSource, /useWhatsAppRecipientRoster/);
  assert.match(pageSource, /useWhatsAppRecipientRoster\(group\.id\)/);
  assert.match(pageSource, /\{ id: "rejected", label: "Rejected" \}/);
  assert.match(pageSource, /filterRecipientRosterItems\(/);
  assert.match(pageSource, /item\.kind === "rejected"/);
  assert.match(pageSource, /<RejectedRosterRows/);
  assert.match(pageSource, /contact\.source_file_name/);
  assert.match(pageSource, /contact\.sheet_name/);
  assert.match(pageSource, /contact\.row_number/);
  assert.match(pageSource, /contact\.raw_name/);
  assert.match(pageSource, /contact\.raw_phone_number/);
  assert.match(pageSource, /contact\.reason/);
});

test("saved rejected contacts can be corrected into unsent recipients", () => {
  assert.match(endpointsSource, /rejected-contacts\/\$\{rejectedContactId\}\/resolve/);
  assert.match(apiSource, /resolveRejectedContact: async/);
  assert.match(apiSource, /recipient_opt_in_confirmed: recipientOptInConfirmed/);
  assert.match(hooksSource, /useResolveWhatsAppRejectedContact/);
  assert.match(pageSource, /Save and add/);
  assert.match(pageSource, /Recipient agreed to WhatsApp updates/);
  assert.match(pageSource, /added to the valid recipient list as Not sent/);
});

test("rejected rows retain imported fields and expose inline correction controls", () => {
  assert.match(apiSource, /interface WhatsAppRejectedContactInput[\s\S]*imported_fields\?: Record<string, string>/);
  assert.match(pageSource, /imported_fields: contact\.imported_fields/);
  assert.match(pageSource, /visibleImportedFieldEntries\(\s*contact\.imported_fields/);
  assert.match(pageSource, /ROSTER_SOURCE_FIELD_KEYS/);
  assert.match(pageSource, /function RejectedRosterRows/);
  assert.match(pageSource, /aria-expanded=\{isEditing\}/);
  assert.match(pageSource, />\s*Correct\s*<\/button>/);
  assert.match(pageSource, /Corrected name/);
  assert.match(pageSource, /Corrected WhatsApp number/);
  assert.match(pageSource, /Recipient agreed to WhatsApp updates/);
  assert.match(pageSource, /Save and add/);
});

test("passport-link sends custom recipients with one selected support contact", () => {
  assert.match(pageSource, /Custom select/);
  assert.match(pageSource, /Support contacts included/);
  assert.match(pageSource, /name="passport-link-support-contact"/);
  assert.match(pageSource, /setSelectedSupportContactIds\(\[contact\.id\]\)/);
  assert.match(pageSource, /Select one contact to show/);
  assert.doesNotMatch(pageSource, /Select one or more contacts to show/);
  assert.match(pageSource, /recipient_ids:/);
  assert.match(pageSource, /support_contact_ids:/);
  assert.match(apiSource, /recipient_ids: recipientIds/);
  assert.match(apiSource, /support_contact_ids: supportContactIds/);
});

test("message preview remains unsendable while the latest approved rendering loads", () => {
  assert.match(
    pageSource,
    /disabled=\{!canSend \|\| previewRequest\.isPending\}/,
  );
  assert.match(pageSource, /eligibleRecipientCount > 0/);
  assert.match(pageSource, /detail\?\.recipient_opt_in_confirmed/);
  assert.match(
    pageSource,
    /messageType !== "passport_link" \|\| resolvedSupportContactIds\.length > 0/,
  );
});

test("message editors expose selection-aware WhatsApp bold controls", () => {
  assert.match(pageSource, /toggleWhatsAppBold/);
  assert.match(pageSource, /passportIntroRef\.current/);
  assert.match(pageSource, /messageContentRef\.current/);
  assert.match(
    pageSource,
    /aria-label="Bold selected passport introduction text or start bold typing"/,
  );
  assert.match(
    pageSource,
    /aria-label="Bold selected message text or start bold typing"/,
  );
  assert.match(pageSource, /parseWhatsAppBoldSegments\(preview\.rendered_message\)/);
});
