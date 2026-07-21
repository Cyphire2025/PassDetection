import assert from "node:assert/strict";
import test from "node:test";
import {
  mergeRecipientImportContacts,
  mergeRecipientImportPreview,
  mergeRecipientImportRejectedRows,
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

test("preserves imported spreadsheet fields for review and persistence", () => {
  const result = mergeRecipientImportContacts([], [
    {
      name: "Aarav",
      phone_number: "+91 9818752221",
      imported_fields: {
        email: "aarav@example.com",
        staff_code: "GC-42",
      },
    },
  ]);

  assert.deepEqual(result.contacts[0].imported_fields, {
    email: "aarav@example.com",
    staff_code: "GC-42",
  });
});

test("keeps every valid contact from a mixed preview and returns every rejected source row", () => {
  const preview = {
    recipient_count: 2,
    accepted_count: 2,
    recipients: [
      {
        name: "Aarav Mehta",
        phone_number: "+91 9818752221",
        imported_fields: {
          email: "aarav@example.com",
          staff_code: "GC-42",
        },
      },
      {
        name: "Meera Shah",
        phone_number: "+91 9999911111",
        imported_fields: {
          agent_company: "Bluechip",
        },
      },
    ],
    rejected_count: 3,
    rejected_rows: [
      {
        sheet_name: "Delegates",
        row_number: 7,
        raw_name: "No Phone",
        raw_phone_number: null,
        reason_code: "missing_phone",
        reason: "WhatsApp number is missing.",
      },
      {
        sheet_name: "Delegates",
        row_number: 12,
        raw_name: null,
        raw_phone_number: "98187",
        reason_code: "invalid_phone",
        reason: "WhatsApp number is invalid.",
      },
      {
        sheet_name: "VIP List",
        row_number: 4,
        raw_name: "Aarav Duplicate",
        raw_phone_number: "+91 9818752221",
        reason_code: "duplicate_phone",
        reason: "WhatsApp number is duplicated in the workbook.",
      },
    ],
  };

  const result = mergeRecipientImportPreview(
    [{ name: "Manual Person", phone_number: "+91 8888811111" }],
    preview,
  );

  assert.equal(result.acceptedCount, 2);
  assert.equal(result.addedCount, 2);
  assert.equal(result.duplicateCount, 0);
  assert.equal(result.rejectedCount, 3);
  assert.deepEqual(
    result.contacts.map((contact) => contact.name),
    ["Manual Person", "Aarav Mehta", "Meera Shah"],
  );
  assert.deepEqual(result.contacts[1].imported_fields, {
    email: "aarav@example.com",
    staff_code: "GC-42",
  });
  assert.deepEqual(result.rejectedRows, preview.rejected_rows);
  assert.notEqual(result.rejectedRows, preview.rejected_rows);
});

test("deduplicates accepted preview contacts against existing broadcast numbers without hiding backend rejections", () => {
  const result = mergeRecipientImportPreview(
    [],
    {
      recipient_count: 2,
      accepted_count: 2,
      recipients: [
        { name: "Already Saved", phone_number: "9818752221" },
        { name: "New Recipient", phone_number: "9999911111" },
      ],
      rejected_count: 1,
      rejected_rows: [
        {
          sheet_name: "Recipients",
          row_number: 9,
          raw_name: "Missing Number",
          raw_phone_number: null,
          reason_code: "missing_phone",
          reason: "WhatsApp number is missing.",
        },
      ],
    },
    ["+91 9818752221"],
  );

  assert.deepEqual(result.contacts, [
    { name: "New Recipient", phone_number: "9999911111" },
  ]);
  assert.equal(result.addedCount, 1);
  assert.equal(result.duplicateCount, 1);
  assert.equal(result.rejectedRows.length, 1);
  assert.equal(result.rejectedRows[0].row_number, 9);
});

test("retains the full Saigon-shaped partial-success result", () => {
  const acceptedRecipients = Array.from({ length: 211 }, (_, index) => ({
    name: `Delegate ${index + 1}`,
    phone_number: String(9000000000 + index),
    imported_fields: {
      email: `delegate${index + 1}@example.com`,
    },
  }));
  const result = mergeRecipientImportPreview([], {
    recipient_count: 211,
    accepted_count: 211,
    recipients: acceptedRecipients,
    rejected_count: 2,
    rejected_rows: [
      {
        sheet_name: "Sheet1",
        row_number: 14,
        raw_name: "MANSURI ARIFABEN RAFIKAHEMAD",
        raw_phone_number: "919726092",
        reason_code: "invalid_phone",
        reason: "WhatsApp number is invalid.",
      },
      {
        sheet_name: "Sheet1",
        row_number: 41,
        raw_name: "Kiran Ramesh",
        raw_phone_number: "805527415",
        reason_code: "invalid_phone",
        reason: "WhatsApp number is invalid.",
      },
    ],
  });

  assert.equal(result.addedCount, 211);
  assert.equal(result.contacts.length, 211);
  assert.equal(result.rejectedCount, 2);
  assert.deepEqual(
    result.rejectedRows.map((row) => [row.sheet_name, row.row_number]),
    [
      ["Sheet1", 14],
      ["Sheet1", 41],
    ],
  );
});

test("keeps manual contacts and exposes every row when a workbook has no valid recipients", () => {
  const manualContact = {
    name: "Manual Person",
    phone_number: "+91 8888811111",
  };
  const result = mergeRecipientImportPreview(
    [manualContact],
    {
      recipient_count: 0,
      accepted_count: 0,
      recipients: [],
      rejected_count: 2,
      rejected_rows: [
        {
          sheet_name: "Sheet1",
          row_number: 2,
          raw_name: "No Phone",
          raw_phone_number: null,
          reason_code: "missing_phone",
          reason: "WhatsApp number is missing.",
        },
        {
          sheet_name: "Sheet1",
          row_number: 3,
          raw_name: null,
          raw_phone_number: "123",
          reason_code: "missing_name",
          reason: "Recipient name is missing.",
        },
      ],
    },
  );

  assert.deepEqual(result.contacts, [manualContact]);
  assert.equal(result.addedCount, 0);
  assert.equal(result.acceptedCount, 0);
  assert.equal(result.rejectedCount, 2);
  assert.equal(result.rejectedRows.length, 2);
});

test("supports the previous all-accepted preview during a staggered deployment", () => {
  const result = mergeRecipientImportPreview([], {
    recipient_count: 1,
    recipients: [
      {
        name: "Legacy Response",
        phone_number: "+91 9999911111",
      },
    ],
  });

  assert.equal(result.acceptedCount, 1);
  assert.equal(result.rejectedCount, 0);
  assert.deepEqual(result.rejectedRows, []);
  assert.equal(result.addedCount, 1);
});

test("preserves the total rejected count when the backend caps rejection details", () => {
  const result = mergeRecipientImportPreview([], {
    recipient_count: 1,
    accepted_count: 1,
    recipients: [
      {
        name: "Valid Recipient",
        phone_number: "9999911111",
      },
    ],
    rejected_count: 12,
    rejected_rows_truncated: true,
    rejected_rows: [
      {
        sheet_name: "Sheet1",
        row_number: 4,
        raw_name: "Invalid",
        raw_phone_number: "123",
        reason_code: "invalid_phone",
        reason: "WhatsApp number is invalid.",
      },
    ],
  });

  assert.equal(result.addedCount, 1);
  assert.equal(result.rejectedCount, 12);
  assert.equal(result.rejectedRows.length, 1);
  assert.equal(result.rejectedRowsTruncated, true);
  assert.equal(result.omittedRejectedCount, 11);
});

test("accumulates rejected rows across files and deduplicates only exact source rows", () => {
  const firstRow = {
    sheet_name: "Sheet1",
    row_number: 4,
    raw_name: "Invalid",
    raw_phone_number: "123",
    reason_code: "invalid_phone",
    reason: "WhatsApp number is invalid.",
  };
  const firstImport = mergeRecipientImportRejectedRows(
    [],
    [firstRow],
    "first.xlsx",
  );
  const repeatedImport = mergeRecipientImportRejectedRows(
    firstImport,
    [firstRow],
    "first.xlsx",
  );
  const accumulatedImport = mergeRecipientImportRejectedRows(
    repeatedImport,
    [
      {
        ...firstRow,
        raw_phone_number: "456",
      },
      firstRow,
    ],
    "second.xlsx",
  );

  assert.equal(repeatedImport.length, 1);
  assert.equal(accumulatedImport.length, 3);
  assert.deepEqual(
    accumulatedImport.map((row) => [
      row.source_file_name,
      row.sheet_name,
      row.row_number,
      row.raw_phone_number,
    ]),
    [
      ["first.xlsx", "Sheet1", 4, "123"],
      ["second.xlsx", "Sheet1", 4, "456"],
      ["second.xlsx", "Sheet1", 4, "123"],
    ],
  );
});

test("preserves imported fields on rejected rows for later correction", () => {
  const importedFields = {
    email: "delegate@example.com",
    staff_code: "GC-204",
  };
  const result = mergeRecipientImportPreview([], {
    recipient_count: 0,
    recipients: [],
    rejected_count: 1,
    rejected_rows: [
      {
        sheet_name: "Delegates",
        row_number: 8,
        raw_name: "Delegate Name",
        raw_phone_number: "123",
        reason_code: "invalid_phone",
        reason: "WhatsApp number is invalid.",
        imported_fields: importedFields,
      },
    ],
  });

  assert.deepEqual(result.rejectedRows[0].imported_fields, importedFields);
  assert.notEqual(result.rejectedRows[0].imported_fields, importedFields);
});
