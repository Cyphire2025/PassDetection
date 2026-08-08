import assert from "node:assert/strict";
import test from "node:test";
import {
  filterRecipientRosterItems,
  recipientHasFailedMessage,
  recipientHasSentMessage,
  searchRecipientRosterItems,
} from "./recipient-roster.ts";

function messageStatus({
  messageType,
  status,
  alreadySent = false,
  latestResendStatus = null,
}) {
  return {
    message_type: messageType,
    status,
    already_sent: alreadySent,
    latest_resend_status: latestResendStatus,
    resend_blocked: false,
    submitted_at: null,
    status_updated_at: "2026-07-23T00:00:00Z",
  };
}

function recipientItem({
  id,
  displayOrder,
  messageStatuses = [],
}) {
  return {
    kind: "recipient",
    display_order: displayOrder,
    recipient: {
      id,
      name: id,
      phone_number: `raw-${id}`,
      normalized_phone_number: `+91${id}`,
      imported_fields: {},
      message_statuses: messageStatuses,
    },
  };
}

function rejectedItem({ id, displayOrder, rowNumber }) {
  return {
    kind: "rejected",
    display_order: displayOrder,
    rejected_contact: {
      id,
      source_file_name: "contacts.xlsx",
      sheet_name: "Sheet1",
      row_number: rowNumber,
      raw_name: id,
      raw_phone_number: null,
      reason_code: "missing_phone",
      reason: "A WhatsApp number is required.",
      imported_fields: {},
      created_at: "2026-07-23T00:00:00Z",
    },
  };
}

function replacedItem({ id, displayOrder }) {
  return {
    kind: "replaced",
    display_order: displayOrder,
    replaced_recipient: {
      recipient_id: id,
      resolution_id: `resolution-${id}`,
      client_group_id: `group-${id}`,
      client_group_name: "Vietnam 2026",
      name: id,
      phone_number: `raw-${id}`,
      normalized_phone_number: `+91${id}`,
      imported_fields: {},
      replacement_submission_id: `submission-${id}`,
      replacement_name: `replacement-${id}`,
      replacement_phone: "+919999999999",
      replaced_at: "2026-07-24T00:00:00Z",
    },
  };
}

function unidentifiedItem({ id, displayOrder }) {
  return {
    kind: "unidentified",
    display_order: displayOrder,
    unidentified_upload: {
      submission_id: id,
      client_group_id: `group-${id}`,
      client_group_name: "Vietnam 2026",
      name: id,
      phone_number: "+919999999998",
      email: `${id}@example.com`,
      details: { passport_number: "P1234567" },
      updated_at: "2026-07-24T00:00:00Z",
    },
  };
}

const rejected = rejectedItem({
  id: "rejected-row",
  displayOrder: 10,
  rowNumber: 2,
});
const sent = recipientItem({
  id: "sent-recipient",
  displayOrder: 20,
  messageStatuses: [
    messageStatus({
      messageType: "welcome",
      status: "delivered",
      alreadySent: true,
    }),
  ],
});
const sentAndFailed = recipientItem({
  id: "mixed-recipient",
  displayOrder: 25,
  messageStatuses: [
    messageStatus({
      messageType: "welcome",
      status: "read",
      alreadySent: true,
    }),
    messageStatus({
      messageType: "passport_link",
      status: "failed",
    }),
  ],
});
const failedResend = recipientItem({
  id: "failed-resend-recipient",
  displayOrder: 30,
  messageStatuses: [
    messageStatus({
      messageType: "welcome",
      status: "sent",
      alreadySent: true,
      latestResendStatus: "failed",
    }),
  ],
});
const neverSent = recipientItem({
  id: "never-sent-recipient",
  displayOrder: 40,
});
const replaced = replacedItem({
  id: "replaced-recipient",
  displayOrder: 15,
});
const unidentified = unidentifiedItem({
  id: "unidentified-upload",
  displayOrder: 45,
});

const unorderedRoster = [
  neverSent,
  sentAndFailed,
  rejected,
  replaced,
  unidentified,
  failedResend,
  sent,
];

function itemId(item) {
  if (item.kind === "recipient") return item.recipient.id;
  if (item.kind === "rejected") return item.rejected_contact.id;
  if (item.kind === "replaced") return item.replaced_recipient.recipient_id;
  return item.unidentified_upload.submission_id;
}

test("All retains active and rejected rows but excludes replaced and unidentified people", () => {
  const result = filterRecipientRosterItems(unorderedRoster, "all");

  assert.deepEqual(result.map(itemId), [
    "rejected-row",
    "sent-recipient",
    "mixed-recipient",
    "failed-resend-recipient",
    "never-sent-recipient",
  ]);
});

test("Sent includes any recipient with an accepted message and keeps import order", () => {
  const result = filterRecipientRosterItems(unorderedRoster, "sent");

  assert.deepEqual(result.map(itemId), [
    "sent-recipient",
    "mixed-recipient",
    "failed-resend-recipient",
  ]);
  assert.equal(recipientHasSentMessage(sentAndFailed.recipient), true);
  assert.equal(recipientHasSentMessage(neverSent.recipient), false);
});

test("Failed includes current failures and failed resends without hiding mixed outcomes", () => {
  const result = filterRecipientRosterItems(unorderedRoster, "failed");

  assert.deepEqual(result.map(itemId), [
    "mixed-recipient",
    "failed-resend-recipient",
  ]);
  assert.equal(recipientHasFailedMessage(sentAndFailed.recipient), true);
  assert.equal(recipientHasFailedMessage(failedResend.recipient), true);
  assert.equal(recipientHasFailedMessage(sent.recipient), false);
});

test("Rejected contains only invalid spreadsheet rows", () => {
  const result = filterRecipientRosterItems(unorderedRoster, "rejected");

  assert.deepEqual(result.map(itemId), ["rejected-row"]);
});

test("Replaced contains only suppressed recipients and preserves import order", () => {
  const result = filterRecipientRosterItems(unorderedRoster, "replaced");

  assert.deepEqual(result.map(itemId), ["replaced-recipient"]);
  assert.equal(filterRecipientRosterItems(unorderedRoster, "all").includes(replaced), false);
});

test("Unidentified contains only passport uploads not in the broadcast", () => {
  const result = filterRecipientRosterItems(unorderedRoster, "unidentified");

  assert.deepEqual(result.map(itemId), ["unidentified-upload"]);
  assert.equal(
    filterRecipientRosterItems(unorderedRoster, "all").includes(unidentified),
    false,
  );
});

test("equal display orders keep the server response order for deterministic numbering", () => {
  const first = recipientItem({
    id: "first",
    displayOrder: 50,
  });
  const second = rejectedItem({
    id: "second",
    displayOrder: 50,
    rowNumber: 12,
  });

  const result = filterRecipientRosterItems([second, first], "all");

  assert.deepEqual(result.map(itemId), ["second", "first"]);
});

test("recipient search matches names, numbers, and imported passenger details", () => {
  const passenger = recipientItem({
    id: "searchable-passenger",
    displayOrder: 60,
  });
  passenger.recipient.name = "Raman Jha";
  passenger.recipient.phone_number = "+91 98187 52221";
  passenger.recipient.imported_fields = {
    passport_number: "N1234567",
    destination: "Da Nang",
  };

  assert.deepEqual(
    searchRecipientRosterItems([neverSent, passenger], "raman").map(itemId),
    ["searchable-passenger"],
  );
  assert.deepEqual(
    searchRecipientRosterItems([neverSent, passenger], "98187").map(itemId),
    ["searchable-passenger"],
  );
  assert.deepEqual(
    searchRecipientRosterItems([neverSent, passenger], "n1234567").map(itemId),
    ["searchable-passenger"],
  );
  assert.deepEqual(
    searchRecipientRosterItems([neverSent, passenger], "da nang").map(itemId),
    ["searchable-passenger"],
  );
});

test("recipient search covers rejected, replaced, and unidentified roster rows", () => {
  assert.deepEqual(
    searchRecipientRosterItems(unorderedRoster, "rejected-row").map(itemId),
    ["rejected-row"],
  );
  assert.deepEqual(
    searchRecipientRosterItems(unorderedRoster, "replacement-replaced-recipient").map(itemId),
    ["replaced-recipient"],
  );
  assert.deepEqual(
    searchRecipientRosterItems(unorderedRoster, "p1234567").map(itemId),
    ["unidentified-upload"],
  );
});

test("blank recipient search preserves the already-filtered roster", () => {
  const filtered = filterRecipientRosterItems(unorderedRoster, "failed");
  assert.equal(searchRecipientRosterItems(filtered, "  "), filtered);
});
