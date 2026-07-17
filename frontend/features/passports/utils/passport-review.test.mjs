import assert from "node:assert/strict";
import test from "node:test";
import {
  canRetryPassportAiVerification,
  getPassportFieldReview,
  getPassportFieldReviewClassName,
  getPassportReviewerLabel,
  getPassportReviewActionState,
} from "./passport-review.ts";

test("allows AI retry only for temporary provider failures", () => {
  for (const providerStatus of [
    "network_error",
    "provider_unavailable",
    "rate_limited",
    "timeout",
  ]) {
    assert.equal(
      canRetryPassportAiVerification({
        status: "needs_review",
        post_submission_verification: {
          provider_status: providerStatus,
        },
      }),
      true,
    );
  }

  assert.equal(
    canRetryPassportAiVerification({
      status: "needs_review",
      post_submission_verification: {
        provider_status: "verified",
      },
    }),
    false,
  );
  assert.equal(
    canRetryPassportAiVerification({
      status: "ai_approved",
      post_submission_verification: {
        provider_status: "provider_unavailable",
      },
    }),
    false,
  );
});

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
  assert.equal(incorrect?.label, "Incorrect");
  assert.match(getPassportFieldReviewClassName(incorrect?.verdict), /border-red-400/);
  assert.equal(suspicious?.verdict, "suspicious");
  assert.equal(suspicious?.label, "Suspicious");
  assert.match(getPassportFieldReviewClassName(suspicious?.verdict), /border-amber-400/);
});

test("labels unavailable AI fields as not verified while retaining amber styling", () => {
  const unavailable = getPassportFieldReview(
    {
      status: "needs_review",
      post_submission_verification: {
        verification_status: "needs_review",
        confidence: 0,
        incorrect_fields: [],
        suspicious_fields: ["date_of_expiry"],
        explanation: "AI verification was unavailable.",
        provider_status: "provider_unavailable",
        reason_code: "provider_unavailable",
        model: null,
        fields: [{
          field: "date_of_expiry",
          verdict: "suspicious",
          observed_value: null,
          confidence: 0,
          reason_code: "provider_unavailable",
        }],
      },
    },
    undefined,
    "date_of_expiry",
  );

  assert.equal(unavailable?.verdict, "suspicious");
  assert.equal(unavailable?.label, "Not verified");
  assert.equal(unavailable?.reason_code, "provider_unavailable");
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
