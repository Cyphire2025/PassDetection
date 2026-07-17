import type {
  ExtractedPassportFields,
  PassportSubmission,
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
};

type VerificationSource = Pick<
  PassportSubmission,
  "status" | "post_submission_verification"
>;

type ReviewerSource = Pick<
  PassportSubmission,
  | "verification_reviewed_by_user_id"
  | "verification_reviewer_name"
>;

export function getPassportFieldReview(
  passport: VerificationSource,
  validation: ExtractedPassportFields["field_validation"] | undefined,
  field: PassportReviewFieldName,
): PassportFieldReview | null {
  if (passport.status === "needs_review") {
    const verification = passport.post_submission_verification;
    const decisions = Array.isArray(verification?.fields) ? verification.fields : [];
    const decision = decisions.find((item) => item.field === field);
    if (decision?.verdict === "correct") return null;
    if (decision?.verdict === "suspicious" || decision?.verdict === "incorrect") {
      return decision as PassportFieldReview;
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
