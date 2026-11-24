import type { PassportPostSubmissionVerification, PassportSubmission } from "@/types/passport.types";
import type { PassportFieldReview } from "./passport-review-fields.ts";

type ReviewerSource = Pick<
  PassportSubmission,
  | "verification_reviewed_by_user_id"
  | "verification_reviewer_name"
>;

const NO_READABLE_EVIDENCE_REASON_CODES = new Set([
  "unreadable",
  "missing_submitted_value",
]);

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
  if (verification.stale_after_staff_edit) return null;
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
  };
  const inactiveLabel = inactiveLabels[status];
  if (inactiveLabel) return { disabled: true, label: inactiveLabel };
  if (status === "needs_review") {
    return { disabled: false, label: "Approve After Manual Review" };
  }
  if (status === "submitted") {
    return { disabled: false, label: "Save Changes for Review" };
  }
  if (status === "ai_approved" || status === "staff_approved") {
    return { disabled: false, label: "Save Changes and Re-review" };
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
