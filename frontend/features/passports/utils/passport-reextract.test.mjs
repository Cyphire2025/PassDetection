import assert from "node:assert/strict";
import test from "node:test";
import { getReextractFeedback, getReextractOutcome, needsReextraction } from "./passport-reextract.ts";

const fields = ["surname", "given_names", "date_of_birth", "date_of_expiry"];
const passport = {
  status: "needs_review",
  image_s3_key: "passports/front.jpg",
  extraction_status: "extraction_complete",
  processing_job_status: "succeeded",
  post_submission_verification: { provider_status: "verified", incorrect_fields: fields },
};

test("re-extraction requires more than three distinct incorrect passport fields", () => {
  assert.equal(needsReextraction(passport), true);
  for (const incorrect_fields of [fields.slice(0, 3), [fields[0], fields[0], fields[0], fields[0]], [...fields.slice(0, 3), "email"]]) {
    assert.equal(needsReextraction({ ...passport, post_submission_verification: { provider_status: "verified", incorrect_fields } }), false);
  }
});

test("extraction failure or missing confidence alone cannot request re-extraction", () => {
  assert.equal(needsReextraction({ ...passport, overall_confidence: 0, post_submission_verification: null }), false);
  for (const provider_status of ["manual_review_required", "timeout", "rate_limited"]) {
    assert.equal(needsReextraction({ ...passport, post_submission_verification: { provider_status, incorrect_fields: fields } }), false);
  }
  assert.equal(needsReextraction({ ...passport, post_submission_verification: { ...passport.post_submission_verification, stale_after_staff_edit: true } }), false);
  assert.equal(needsReextraction({ ...passport, status: "submitted" }), false);
  assert.equal(needsReextraction({ ...passport, image_s3_key: "excel-imports/person" }), false);
});

test("polling continues from extraction through queued verification", () => {
  assert.equal(getReextractOutcome({ ...passport, extraction_status: "processing" }), null);
  assert.equal(getReextractOutcome({ ...passport, status: "submitted" }), null);
  assert.equal(getReextractOutcome(passport), "completed");
  assert.equal(getReextractOutcome({ ...passport, status: "ai_approved" }), "completed");
  assert.equal(getReextractOutcome({ ...passport, extraction_status: "extraction_failed" }), "failed");
});

test("completion explains verification verdict rather than reporting extraction alone", () => {
  assert.equal(getReextractFeedback(passport).tone, "warning");
  assert.match(getReextractFeedback(passport).message, /flagged fields/);
  assert.equal(getReextractFeedback({ ...passport, status: "ai_approved" }).tone, "success");
  assert.match(getReextractFeedback({ ...passport, post_submission_verification: { provider_status: "timeout" } }).message, /retry verification/);
});
