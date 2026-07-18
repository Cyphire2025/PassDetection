import assert from "node:assert/strict";
import test from "node:test";
import {
  mergeRecipientImportContacts,
  recipientPhoneMergeKey,
} from "./recipient-import.ts";

test("normalizes common Indian and international representations for merging", () => {
  assert.equal(recipientPhoneMergeKey("98187 52221"), "+919818752221");
  assert.equal(recipientPhoneMergeKey("+91 98187-52221"), "+919818752221");
  assert.equal(recipientPhoneMergeKey("0091 98187 52221"), "+919818752221");
  assert.equal(recipientPhoneMergeKey("+44 7700 900123"), "+447700900123");
});

test("merges imported contacts while preserving existing contacts first", () => {
  const result = mergeRecipientImportContacts(
    [{ name: "Manual Name", phone_number: "98187 52221" }],
    [
      { name: "Spreadsheet Duplicate", phone_number: "+91 9818752221" },
      { name: "New Person", phone_number: "+91 99999 11111" },
    ],
  );

  assert.deepEqual(result.contacts, [
    { name: "Manual Name", phone_number: "98187 52221" },
    { name: "New Person", phone_number: "+91 99999 11111" },
  ]);
  assert.equal(result.addedCount, 1);
  assert.equal(result.duplicateCount, 1);
});

test("does not add phone numbers that already belong to the broadcast", () => {
  const result = mergeRecipientImportContacts(
    [],
    [
      { name: "Existing Person", phone_number: "+91 9818752221" },
      { name: "New Person", phone_number: "+91 9999911111" },
    ],
    ["9818752221"],
  );

  assert.deepEqual(result.contacts, [
    { name: "New Person", phone_number: "+91 9999911111" },
  ]);
  assert.equal(result.addedCount, 1);
  assert.equal(result.duplicateCount, 1);
});

test("deduplicates repeated rows inside the same spreadsheet preview", () => {
  const result = mergeRecipientImportContacts([], [
    { name: "First", phone_number: "+91 9818752221" },
    { name: "Repeated", phone_number: "9818752221" },
  ]);

  assert.equal(result.contacts.length, 1);
  assert.equal(result.addedCount, 1);
  assert.equal(result.duplicateCount, 1);
});
