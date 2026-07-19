import assert from "node:assert/strict";
import test from "node:test";
import {
  buildStaffApprovalRequest,
  canRetryPassportAiVerification,
  cleanPassportReviewFields,
  formatPassportFieldReviewConfidence,
  getPassportFieldReview,
  getPassportFieldReviewClassName,
  getPassportReviewerLabel,
  getPassportReviewActionState,
  getPassportVerificationConfidence,
  getStaffApprovalErrorFeedback,
  getStaffApprovalOutcomeFeedback,
} from "./passport-review.ts";

test("staff review payload keeps only the nine passport fields", () => {
  assert.deepEqual(
    cleanPassportReviewFields({
      surname: "  KHAN ",
      given_names: "IRFAN",
      passport_number: " P7251478 ",
      nationality: "Indian",
      issuing_country: "India",
      date_of_birth: "1988-06-28",
      date_of_issue: "2017-01-16",
      date_of_expiry: "2027-01-15",
      sex: "M",
      base_city: "Delhi",
      staff_code: "GC-7",
      meal_preference: "Vegetarian",
      ai_verification: "must-not-leak",
    }),
    {
      surname: "KHAN",
      given_names: "IRFAN",
      passport_number: "P7251478",
      nationality: "Indian",
      issuing_country: "India",
      date_of_birth: "1988-06-28",
      date_of_issue: "2017-01-16",
      date_of_expiry: "2027-01-15",
      sex: "M",
    },
  );
});

test("staff approval request carries the current revision and bounded optional reason", () => {
  assert.deepEqual(
    buildStaffApprovalRequest(
      {
        surname: "  KHAN ",
        passport_number: " P7251478 ",
        staff_code: "must-not-leak",
      },
      14,
      "  Visual mismatch confirmed by staff.  ",
    ),
    {
      confirmedFields: {
        surname: "KHAN",
        passport_number: "P7251478",
      },
      expectedExtractionRevision: 14,
      reviewReason: "Visual mismatch confirmed by staff.",
    },
  );
});

test("staff review preserves an explicit empty surname correction", () => {
  assert.deepEqual(
    cleanPassportReviewFields({
      surname: "   ",
      given_names: "MOHIT",
      passport_number: "W6905713",
    }),
    {
      surname: "",
      given_names: "MOHIT",
      passport_number: "W6905713",
    },
  );
});

test("partial staff review objects do not inject an absent surname correction", () => {
  assert.deepEqual(
    cleanPassportReviewFields({
      passport_number: " W6905713 ",
    }),
    {
      passport_number: "W6905713",
    },
  );
});

test("maps staff approval outcomes and typed failures to actionable UI states", () => {
  assert.deepEqual(getStaffApprovalOutcomeFeedback("approved"), {
    kind: "success",
    message: "Passport approved and reviewed corrections saved.",
  });
  assert.equal(
    getStaffApprovalOutcomeFeedback("already_approved").kind,
    "already_approved",
  );
  assert.equal(
    getStaffApprovalErrorFeedback({
      code: "STAFF_APPROVAL_STALE",
      message: "Record changed.",
    }).kind,
    "record_changed",
  );
  assert.equal(
    getStaffApprovalErrorFeedback({
      code: "STAFF_APPROVAL_UNAVAILABLE",
      message: "Approval unavailable.",
    }).kind,
    "unavailable",
  );
  assert.equal(
    getStaffApprovalErrorFeedback({
      code: "NETWORK_ERROR",
      message: "Unable to reach the server.",
    }).kind,
    "temporary_error",
  );
});

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

test("never displays confidence when AI could not read a field", () => {
  assert.equal(
    formatPassportFieldReviewConfidence({
      observed_value: null,
      confidence: 1,
      reason_code: "unreadable",
    }),
    null,
  );
  assert.equal(
    formatPassportFieldReviewConfidence({
      observed_value: "Z7418523",
      confidence: 0.99,
      reason_code: "different_value",
    }),
    "99% confidence",
  );
});

test("hides legacy aggregate confidence inflated by unreadable evidence", () => {
  const verification = {
    verification_status: "needs_review",
    confidence: 1,
    incorrect_fields: [],
    suspicious_fields: ["date_of_birth"],
    explanation: "Review the marked fields.",
    provider_status: "verified",
    reason_code: null,
    model: "test-model",
    stale_after_staff_edit: false,
    fields: [{
      field: "date_of_birth",
      verdict: "suspicious",
      observed_value: null,
      confidence: 1,
      reason_code: "unreadable",
    }],
  };

  assert.equal(getPassportVerificationConfidence(verification), null);
  verification.fields[0].confidence = 0;
  verification.confidence = 0;
  assert.equal(getPassportVerificationConfidence(verification), 0);
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
  assert.deepEqual(getPassportReviewActionState("needs_review", true), {
    disabled: true,
    label: "Approving and saving corrections",
  });
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
