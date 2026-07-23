import assert from "node:assert/strict";
import test from "node:test";
import {
  filterRecipientRosterItems,
  recipientHasFailedMessage,
  recipientHasSentMessage,
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

const unorderedRoster = [
  neverSent,
  sentAndFailed,
  rejected,
  failedResend,
  sent,
];

function itemId(item) {
  return item.kind === "recipient"
    ? item.recipient.id
    : item.rejected_contact.id;
}

test("All retains valid, never-sent, failed, sent, and rejected rows in import order", () => {
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
