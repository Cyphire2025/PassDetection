import type {
  ExtractedPassportFields,
  PassportPostSubmissionVerification,
  PassportSubmission,
  StaffApprovalOutcome,
  StaffApprovalRequest,
  PassportVerificationField,
  PassportVerificationFieldName,
  PassportVerificationVerdict,
} from "@/types/passport.types";

export const PASSPORT_REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "issuing_country",
  "date_of_birth",
  "date_of_issue",
  "date_of_expiry",
  "sex",
] as const satisfies readonly PassportVerificationFieldName[];

export type PassportReviewFieldName = typeof PASSPORT_REVIEW_FIELDS[number];

export type PassportFieldReview = Omit<PassportVerificationField, "verdict"> & {
  verdict: Exclude<PassportVerificationVerdict, "correct">;
  label: "Incorrect" | "Suspicious" | "Not verified";
};

export type StaffApprovalFeedbackKind =
  | "success"
  | "already_approved"
  | "record_changed"
  | "unavailable"
  | "temporary_error";

export interface StaffApprovalFeedback {
  kind: StaffApprovalFeedbackKind;
  message: string;
}

export function cleanPassportReviewFields(
  fields: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    PASSPORT_REVIEW_FIELDS.flatMap((field) => {
      if (!Object.prototype.hasOwnProperty.call(fields, field)) return [];
      const value = fields[field]?.trim() ?? "";
      return value || field === "surname"
        ? [[field, value] as const]
        : [];
    }),
  );
}

export function buildStaffApprovalRequest(
  fields: Record<string, string>,
  expectedExtractionRevision: number,
  reviewReason?: string,
): StaffApprovalRequest {
  const normalizedReason = reviewReason?.trim();
  return {
    confirmedFields: cleanPassportReviewFields(fields),
    expectedExtractionRevision,
    ...(normalizedReason ? { reviewReason: normalizedReason } : {}),
  };
}

export function getStaffApprovalOutcomeFeedback(
  outcome: StaffApprovalOutcome,
): StaffApprovalFeedback {
  if (outcome === "already_approved") {
    return {
      kind: "already_approved",
      message: (
        "This passport was already approved. The latest saved approval is shown "
        + "and no duplicate action was created."
      ),
    };
  }
  return {
    kind: "success",
    message: "Passport approved and reviewed corrections saved.",
  };
}

export function getStaffApprovalErrorFeedback(
  error: unknown,
): StaffApprovalFeedback {
  const candidate = (
    error && typeof error === "object"
      ? error as { code?: unknown; message?: unknown }
      : null
  );
  const code = typeof candidate?.code === "string" ? candidate.code : "";
  const serverMessage = (
    typeof candidate?.message === "string" && candidate.message.trim()
      ? candidate.message.trim()
      : null
  );

  if (code === "STAFF_APPROVAL_STALE") {
    return {
      kind: "record_changed",
      message: (
        serverMessage
        ?? "This passport changed after you opened it. Review the refreshed record and approve again."
      ),
    };
  }
  if (
    code === "STAFF_APPROVAL_UNAVAILABLE"
    || code === "VALIDATION_ERROR"
    || code === "AUTHORIZATION_ERROR"
  ) {
    return {
      kind: "unavailable",
      message: (
        serverMessage
        ?? "This passport is not currently available for staff approval."
      ),
    };
  }
  return {
    kind: "temporary_error",
    message: (
      serverMessage
      ?? "The approval response could not be confirmed. Refresh and safely retry."
    ),
  };
}

type VerificationSource = Pick<
  PassportSubmission,
  "status" | "post_submission_verification"
>;

type ReviewerSource = Pick<
  PassportSubmission,
  | "verification_reviewed_by_user_id"
  | "verification_reviewer_name"
>;

const RETRYABLE_AI_PROVIDER_STATUSES = new Set([
  "network_error",
  "provider_unavailable",
  "rate_limited",
  "timeout",
]);
const NO_READABLE_EVIDENCE_REASON_CODES = new Set([
  "unreadable",
  "missing_submitted_value",
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
    const providerUnavailable = typeof verification?.provider_status === "string"
      && RETRYABLE_AI_PROVIDER_STATUSES.has(
        verification.provider_status.trim().toLowerCase(),
      );
    const decisions = Array.isArray(verification?.fields) ? verification.fields : [];
    const decision = decisions.find((item) => item.field === field);
    if (decision?.verdict === "correct") return null;
    if (decision?.verdict === "suspicious" || decision?.verdict === "incorrect") {
      return {
        field: decision.field,
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

export function getPassportFieldReviewClassName(verdict?: PassportFieldReview["verdict"]) {
  if (verdict === "incorrect") {
    return "border-red-400 bg-red-50 hover:border-red-500 focus:border-red-500 focus:ring-2 focus:ring-red-200";
  }
  if (verdict === "suspicious") {
    return "border-amber-400 bg-amber-50 hover:border-amber-500 focus:border-amber-500 focus:ring-2 focus:ring-amber-200";
  }
  return "border-slate-200 bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
}

export function formatPassportFieldReviewConfidence(
  review: Pick<
    PassportFieldReview,
    "confidence" | "observed_value" | "reason_code"
  >,
) {
  if (
    !review.observed_value?.trim()
    || NO_READABLE_EVIDENCE_REASON_CODES.has(review.reason_code.trim().toLowerCase())
    || !Number.isFinite(review.confidence)
    || review.confidence <= 0
  ) {
    return null;
  }
  const percentage = review.confidence <= 1
    ? review.confidence * 100
    : Math.min(100, review.confidence);
  return `${Math.round(percentage)}% confidence`;
}

export function getPassportVerificationConfidence(
  verification: PassportPostSubmissionVerification,
) {
  const containsLegacyInflatedUnreadableConfidence = verification.fields.some(
    (field) =>
      field.confidence > 0
      && (
        !field.observed_value?.trim()
        || NO_READABLE_EVIDENCE_REASON_CODES.has(
          field.reason_code.trim().toLowerCase(),
        )
      ),
  );
  if (
    containsLegacyInflatedUnreadableConfidence
    || !Number.isFinite(verification.confidence)
  ) {
    return null;
  }
  return verification.confidence;
}

export function getPassportReviewActionState(
  status: PassportSubmission["status"],
  isSaving: boolean,
) {
  if (isSaving) {
    return {
      disabled: true,
      label: status === "needs_review"
        ? "Approving and saving corrections"
        : "Saving Review",
    };
  }

  const inactiveLabels: Partial<Record<PassportSubmission["status"], string>> = {
    pending_extraction: "Extraction Pending",
    extracting: "Extraction in Progress",
    processing: "Extraction in Progress",
    ready_for_client_review: "Awaiting Client Review",
    submitted: "AI Verification in Progress",
    ai_approved: "AI Verified",
    staff_approved: "Staff Verified",
  };
  const inactiveLabel = inactiveLabels[status];
  if (inactiveLabel) return { disabled: true, label: inactiveLabel };
  if (status === "needs_review") {
    return { disabled: false, label: "Approve After Manual Review" };
  }
  return {
    disabled: false,
    label: status === "confirmed" ? "Update Confirmed Fields" : "Confirm Reviewed Fields",
  };
}

export function getPassportReviewerLabel(
  passport: ReviewerSource,
  currentUser: { id: string; full_name: string } | null,
) {
  if (passport.verification_reviewer_name?.trim()) {
    return passport.verification_reviewer_name.trim();
  }
  if (!passport.verification_reviewed_by_user_id) return null;
  if (passport.verification_reviewed_by_user_id === currentUser?.id) {
    return currentUser.full_name;
  }
  return "Verified by staff";
}

export function formatPassportVerificationReason(reasonCode: string) {
  const trimmed = reasonCode.trim();
  if (!trimmed) return "Review this field manually.";
  if (trimmed.includes(" ")) return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
  const message = trimmed.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
  return `${message}.`;
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
    issuing_country: ["issuing_country"],
    date_of_birth: ["date_of_birth", "birth"],
    date_of_issue: ["date_of_issue", "issue_date"],
    date_of_expiry: ["date_of_expiry", "expiry"],
    sex: ["sex", "gender"],
  };
  return aliases[field].some((alias) => text.includes(alias));
}
