import assert from "node:assert/strict";
import test from "node:test";
import {
  countEligibleRecipients,
  hasAlreadySentMessage,
} from "./recipient-delivery.ts";

const status = (messageType, deliveryStatus, alreadySent) => ({
  message_type: messageType,
  status: deliveryStatus,
  already_sent: alreadySent,
  submitted_at: null,
  status_updated_at: "2026-07-18T00:00:00Z",
});

test("treats only a successful delivery ledger entry as already sent", () => {
  const recipient = {
    message_statuses: [
      status("welcome", "failed", false),
      status("passport_link", "sent", true),
    ],
  };

  assert.equal(hasAlreadySentMessage(recipient, "welcome"), false);
  assert.equal(hasAlreadySentMessage(recipient, "passport_link"), true);
});

test("supports future message types without changing the eligibility logic", () => {
  const recipients = [
    { message_statuses: [status("flight_update", "sent", true)] },
    { message_statuses: [status("flight_update", "failed", false)] },
    { message_statuses: [] },
  ];

  assert.equal(countEligibleRecipients(recipients, "flight_update"), 2);
});

test("suppresses an in-progress claim while allowing failed deliveries to retry", () => {
  const recipients = [
    { message_statuses: [status("welcome", "queued", false)] },
    { message_statuses: [status("welcome", "failed", false)] },
  ];

  assert.equal(countEligibleRecipients(recipients, "welcome"), 1);
});

test("suppresses an unknown delivery outcome to prevent accidental duplicates", () => {
  const recipients = [
    { message_statuses: [status("welcome", "delivery_unknown", false)] },
    { message_statuses: [status("welcome", "failed", false)] },
  ];

  assert.equal(countEligibleRecipients(recipients, "welcome"), 1);
});

test("does not suppress one message type because another type was sent", () => {
  const recipients = [
    { message_statuses: [status("welcome", "sent", true)] },
    { message_statuses: [status("passport_link", "sent", true)] },
  ];

  assert.equal(countEligibleRecipients(recipients, "welcome"), 1);
  assert.equal(countEligibleRecipients(recipients, "passport_link"), 1);
});
