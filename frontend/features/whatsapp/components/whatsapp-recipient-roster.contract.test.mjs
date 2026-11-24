import assert from "node:assert/strict";
import test from "node:test";
import { readWhatsAppSource as read, readWhatsAppApiSource, readRecipientWorkspaceSource, readRecipientDetailSource } from "./whatsapp-source.contract-helper.mjs";

const recipients = readRecipientWorkspaceSource();
const exceptions = read("../workspace/recipient-exceptions.tsx");
const details = readRecipientDetailSource();
const index = read("../workspace/broadcast-index.tsx");
const hooks = read("../hooks/use-broadcast-recipient-mutations.ts");
const facade = read("../hooks/use-whatsapp.ts");
const api = readWhatsAppApiSource();

test("current recipients and exception records have distinct live owners", () => {
  assert.match(recipients, /recipientPeople\(group\.recipients, sources\.data\?\.contacts\)/);
  assert.match(recipients, /<RecipientExceptions/);
  assert.match(exceptions, /useWhatsAppRecipientRoster\(group\.id\)/);
  assert.match(exceptions, /\.filter\(\(item\) => item\.kind !== "recipient"\)/);
  assert.match(api, /recipientRoster: async[\s\S]*API_ENDPOINTS\.whatsapp\.recipientRoster/);
});

test("source passengers and merged imported details retain individual rows without discarding headings", () => {
  assert.match(details, /new Map</);
  assert.match(details, /sourcePeople\.map\(\(contact\)/);
  assert.match(details, /fields: contact\.imported_fields/);
  assert.match(details, /recipient\.merged_contacts \?\? \[\]/);
  assert.match(recipients, /Object\.values\(person\.fields\)/);
});

test("search and sorting use memoized derivations and a bounded current-recipient page", () => {
  assert.match(recipients, /useDeferredValue\(search\)/);
  assert.match(recipients, /const displayed = useMemo/);
  assert.match(recipients, /sort === "import"/);
  assert.match(recipients, /\.slice\(pageOffset, pageOffset \+ 50\)/);
  assert.match(recipients, /label="Search recipients"/);
  assert.match(recipients, /disabled=\{group\.is_archived\}/);
});

test("broadcast summaries distinguish all contact records from valid WhatsApp recipients", () => {
  assert.match(index, /group\.total_contact_count > group\.recipient_count/);
  assert.match(index, /group\.total_contact_count\.toLocaleString\(\)/);
  assert.match(index, /group\.recipient_count\.toLocaleString\(\)/);
});

test("rejected corrections retain group and rejected-row identity plus explicit consent", () => {
  assert.match(exceptions, /useResolveWhatsAppRejectedContact\(\)/);
  assert.match(exceptions, /rejectedContactId: contact\.id/);
  assert.match(exceptions, /recipientOptInConfirmed: confirmed/);
  assert.match(exceptions, /disabled=\{!confirmed\}/);
  assert.match(exceptions, /disabled=\{group\.is_archived\}/);
  assert.match(exceptions, /contact\.raw_name/);
  assert.match(exceptions, /contact\.raw_phone_number/);
});

test("replaced contacts use the durable resolution and unidentified uploads retain the matching deep link", () => {
  assert.match(facade, /from "\.\/use-broadcast-recipient-mutations"/);
  assert.match(exceptions, /broadcastGroupId: group\.id,[\s\S]*clientGroupId: person\.client_group_id,[\s\S]*resolutionId: person\.resolution_id/);
  assert.match(exceptions, /encodeURIComponent\(item\.unidentified_upload\.client_group_id\)/);
  assert.match(exceptions, /Open matching/);
  const restore = hooks.slice(hooks.indexOf("export function useRestoreWhatsAppReplacedRecipient"));
  assert.match(restore, /queryKey: \["whatsapp"\]/);
  assert.match(restore, /"whatsapp-matches"/);
  assert.match(restore, /"passport-export-history"/);
});
