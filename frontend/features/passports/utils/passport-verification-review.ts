import type { ExtractedPassportFields, PassportSubmission } from "@/types/passport.types";
import type { PassportFieldReview, PassportReviewFieldName } from "./passport-review-fields.ts";

type VerificationSource = Pick<
  PassportSubmission,
  "status" | "post_submission_verification"
>;

const RETRYABLE_AI_PROVIDER_STATUSES = new Set([
  "manual_review_required",
  "network_error",
  "provider_unavailable",
  "rate_limited",
  "timeout",
]);

export function canRetryPassportAiVerification(
  passport: VerificationSource,
) {
  if (passport.status !== "needs_review") return false;
  const providerStatus = passport.post_submission_verification?.provider_status;
  return typeof providerStatus === "string"
    && RETRYABLE_AI_PROVIDER_STATUSES.has(providerStatus.trim().toLowerCase());
}

export function getPassportFieldReview(
  passport: VerificationSource,
  validation: ExtractedPassportFields["field_validation"] | undefined,
  field: PassportReviewFieldName,
): PassportFieldReview | null {
  if (passport.status === "needs_review") {
    const verification = passport.post_submission_verification;
    if (verification?.stale_after_staff_edit) {
      return {
        field,
        verdict: "suspicious",
        label: "Not verified",
        observed_value: null,
        confidence: 0,
        reason_code: "passport_record_changed",
      };
    }
    const providerUnavailable = typeof verification?.provider_status === "string"
      && RETRYABLE_AI_PROVIDER_STATUSES.has(
        verification.provider_status.trim().toLowerCase(),
      );
    const decisions = Array.isArray(verification?.fields) ? verification.fields : [];
    const decision = decisions.find((item) => item.field === field);
    if (decision?.verdict === "correct") return null;
    if (decision?.verdict === "suspicious" || decision?.verdict === "incorrect") {
      return {
        field,
        verdict: decision.verdict,
        observed_value: decision.observed_value,
        confidence: decision.confidence,
        reason_code: decision.reason_code,
        label: providerUnavailable
          ? "Not verified"
          : decision.verdict === "incorrect"
            ? "Incorrect"
            : "Suspicious",
      };
    }

    const incorrectFields = Array.isArray(verification?.incorrect_fields)
      ? verification.incorrect_fields
      : [];
    const suspiciousFields = Array.isArray(verification?.suspicious_fields)
      ? verification.suspicious_fields
      : [];
    const listedVerdict = incorrectFields.includes(field)
      ? "incorrect"
      : suspiciousFields.includes(field)
        ? "suspicious"
        : null;
    if (listedVerdict) {
      return {
        field,
        verdict: listedVerdict,
        label: providerUnavailable
          ? "Not verified"
          : listedVerdict === "incorrect"
            ? "Incorrect"
            : "Suspicious",
        observed_value: null,
        confidence: verification?.confidence ?? 0,
        reason_code: verification?.reason_code ?? "manual_review_required",
      };
    }

    if (decisions.length > 0 || incorrectFields.length > 0 || suspiciousFields.length > 0) {
      return null;
    }

    return {
      field,
      verdict: "suspicious",
      label: "Not verified",
      observed_value: null,
      confidence: verification?.confidence ?? 0,
      reason_code: verification?.reason_code ?? "verification_result_unavailable",
    };
  }

  const issue = validation?.issues?.find((candidate) => validationIssueMatchesField(candidate, field));
  if (!issue) return null;
  return {
    field,
    verdict: issue.severity.toLowerCase() === "error" ? "incorrect" : "suspicious",
    label: issue.severity.toLowerCase() === "error" ? "Incorrect" : "Suspicious",
    observed_value: null,
    confidence: 0,
    reason_code: issue.message,
  };
}

function validationIssueMatchesField(
  issue: { field: string; message: string },
  field: PassportReviewFieldName,
) {
  if (issue.field === field) return true;
  const text = `${issue.field} ${issue.message}`.toLowerCase().replaceAll(" ", "_");
  if (field === "surname" || field === "given_names") {
    return text.includes(field) || text.includes("name");
  }
  const aliases: Record<PassportReviewFieldName, string[]> = {
    surname: [],
    given_names: [],
    passport_number: ["passport_number"],
    nationality: ["nationality"],
    place_of_issue: ["place_of_issue"],
    date_of_birth: ["date_of_birth", "birth"],
    date_of_issue: ["date_of_issue", "issue_date"],
    date_of_expiry: ["date_of_expiry", "expiry"],
    sex: ["sex", "gender"],
  };
  return aliases[field].some((alias) => text.includes(alias));
}
