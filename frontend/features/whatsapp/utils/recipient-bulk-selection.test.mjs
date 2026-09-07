import assert from "node:assert/strict";
import test from "node:test";
import { getBulkResendEligibility, summarizeBulkResend } from "./recipient-bulk-selection.ts";

function recipient(overrides = {}) {
  return {
    message_statuses: [{
      message_type: "welcome", status: "sent", already_sent: true,
      latest_resend_status: null, resend_blocked: false, ...overrides,
    }],
  };
}

test("explicit resend includes a previously sent message and a failed attempt", () => {
  assert.equal(getBulkResendEligibility(recipient(), "welcome"), "eligible");
  assert.equal(getBulkResendEligibility(recipient({status: "failed", already_sent: false}), "welcome"), "eligible");
});

test("saved welcome does not imply there is a saved personal passport message", () => {
  assert.equal(getBulkResendEligibility(recipient(), "passport_link"), "no_saved_message");
  assert.equal(getBulkResendEligibility({message_statuses: []}, "welcome"), "no_saved_message");
});

test("latest resend in flight or uncertain blocks duplicate delivery despite original sent status", () => {
  for (const status of ["queued", "processing"]) {
    assert.equal(getBulkResendEligibility(recipient({latest_resend_status: status}), "welcome"), "in_progress");
  }
  assert.equal(getBulkResendEligibility(recipient({latest_resend_status: "delivery_unknown"}), "welcome"), "delivery_unknown");
  assert.equal(getBulkResendEligibility(recipient({resend_blocked: true}), "welcome"), "blocked");
});

test("original pending and unknown delivery are excluded independently of latest resend", () => {
  assert.equal(getBulkResendEligibility(recipient({status: "processing", already_sent: false}), "welcome"), "in_progress");
  assert.equal(getBulkResendEligibility(recipient({status: "delivery_unknown", already_sent: false}), "welcome"), "delivery_unknown");
});

test("review totals account for every selected recipient without mutating input", () => {
  const selected = [
    recipient(), recipient({status: "failed", already_sent: false}),
    recipient({latest_resend_status: "queued"}),
    recipient({latest_resend_status: "delivery_unknown"}),
    recipient({resend_blocked: true}), {message_statuses: []},
  ];
  const before = structuredClone(selected);
  assert.deepEqual(summarizeBulkResend(selected, "welcome"), {
    selected: 6, eligible: 2, noSavedMessage: 1, inProgress: 1, deliveryUnknown: 1, blocked: 1,
  });
  assert.deepEqual(selected, before);
  assert.deepEqual(summarizeBulkResend([], "passport_link"), {
    selected: 0, eligible: 0, noSavedMessage: 0, inProgress: 0, deliveryUnknown: 0, blocked: 0,
  });
});
