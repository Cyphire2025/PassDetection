import type { PassportSubmission } from "@/types/passport.types";

const PASSPORT_FIELDS = new Set([
  "surname", "given_names", "passport_number", "nationality", "place_of_issue",
  "date_of_birth", "date_of_issue", "date_of_expiry", "sex",
]);

export function needsReextraction(passport: PassportSubmission): boolean {
  const verification = passport.post_submission_verification;
  if (
    passport.status !== "needs_review"
    || !passport.image_s3_key
    || passport.image_s3_key.startsWith("excel-imports/")
    || verification?.stale_after_staff_edit
    || verification?.provider_status !== "verified"
  ) return false;
  return new Set(
    (verification.incorrect_fields ?? []).filter((field) => PASSPORT_FIELDS.has(field)),
  ).size > 3;
}

export function getReextractOutcome(
  submission: PassportSubmission,
): "completed" | "failed" | null {
  if (
    submission.status === "failed"
    || submission.extraction_status === "extraction_failed"
    || ["failed", "dead_letter", "cancelled"].includes(submission.processing_job_status ?? "")
  ) return "failed";
  // A successful extraction queues verification. Keep polling until that verdict is saved.
  if (submission.extraction_status === "processing" || submission.status === "submitted") return null;
  if (
    ["extraction_complete", "extraction_partial", "ready_for_review"].includes(submission.extraction_status)
    || submission.processing_job_status === "succeeded"
  ) return "completed";
  return null;
}

export function getReextractFeedback(passport: PassportSubmission): {
  tone: "success" | "warning" | "error";
  message: string;
} {
  if (getReextractOutcome(passport) === "failed") {
    return {
      tone: "error",
      message: passport.error_message || "The saved passport could not be extracted. Open it to review the details.",
    };
  }
  const verification = passport.post_submission_verification;
  if (passport.status === "ai_approved") {
    return { tone: "success", message: "Re-extraction and AI verification finished. All passport fields passed verification." };
  }
  if (passport.status === "needs_review") {
    return {
      tone: "warning",
      message: verification?.provider_status === "verified"
        ? "Re-extraction and AI verification finished. Open the passport to review the flagged fields."
        : "Extraction finished, but AI verification could not complete. Open the passport to retry verification.",
    };
  }
  return { tone: "success", message: "Extraction finished. Open the passport to review the results." };
}
