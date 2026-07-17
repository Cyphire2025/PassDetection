import assert from "node:assert/strict";
import test from "node:test";
import {
  getPassportFieldReview,
  getPassportFieldReviewClassName,
  getPassportReviewerLabel,
  getPassportReviewActionState,
} from "./passport-review.ts";

test("maps suspicious and incorrect verification decisions to field-level colors", () => {
  const baseVerification = {
    verification_status: "needs_review",
    confidence: 0.7,
    incorrect_fields: ["passport_number"],
    suspicious_fields: ["surname"],
    explanation: "Review the marked fields.",
    provider_status: "success",
    reason_code: null,
    model: "test-model",
    fields: [
      {
        field: "passport_number",
        verdict: "incorrect",
        observed_value: "A1234567",
        confidence: 0.95,
        reason_code: "value_mismatch",
      },
      {
        field: "surname",
        verdict: "suspicious",
        observed_value: "SINGH",
        confidence: 0.62,
        reason_code: "low_visual_confidence",
      },
    ],
  };
  const passport = { status: "needs_review", post_submission_verification: baseVerification };

  const incorrect = getPassportFieldReview(passport, undefined, "passport_number");
  const suspicious = getPassportFieldReview(passport, undefined, "surname");

  assert.equal(incorrect?.verdict, "incorrect");
  assert.match(getPassportFieldReviewClassName(incorrect?.verdict), /border-red-400/);
  assert.equal(suspicious?.verdict, "suspicious");
  assert.match(getPassportFieldReviewClassName(suspicious?.verdict), /border-amber-400/);
});

test("marks every field suspicious when AI verification is unavailable", () => {
  const unavailable = getPassportFieldReview(
    { status: "needs_review", post_submission_verification: null },
    undefined,
    "date_of_expiry",
  );

  assert.equal(unavailable?.verdict, "suspicious");
  assert.equal(unavailable?.reason_code, "verification_result_unavailable");
  assert.match(getPassportFieldReviewClassName(unavailable?.verdict), /bg-amber-50/);
});

test("enables staff approval only while the passport needs review", () => {
  assert.deepEqual(getPassportReviewActionState("needs_review", false), {
    disabled: false,
    label: "Approve After Manual Review",
  });
  assert.deepEqual(getPassportReviewActionState("staff_approved", false), {
    disabled: true,
    label: "Staff Verified",
  });
  assert.equal(getPassportReviewActionState("submitted", false).disabled, true);
  assert.equal(getPassportReviewActionState("ai_approved", false).disabled, true);
});

test("uses a display name and never exposes another reviewer's raw UUID", () => {
  const reviewerId = "8382fc99-abcd-4a02-b9cc-ecf7ccabdc82";
  assert.equal(
    getPassportReviewerLabel(
      {
        verification_reviewed_by_user_id: reviewerId,
        verification_reviewer_name: "Nina Reviewer",
      },
      null,
    ),
    "Nina Reviewer",
  );
  assert.equal(
    getPassportReviewerLabel(
      {
        verification_reviewed_by_user_id: reviewerId,
        verification_reviewer_name: null,
      },
      { id: "someone-else", full_name: "Other Staff" },
    ),
    "Verified by staff",
  );
});
