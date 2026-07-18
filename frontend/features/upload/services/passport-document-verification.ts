import type {
  ExtractedPassportFields,
  PassportSubmission,
} from "@/types/passport.types";

const ACCEPTED_STATUSES = new Set(["verified", "enhanced"]);
const REPLACE_STATUSES = new Set([
  "passport_cover",
  "wrong_passport_page",
  "wrong_document",
  "document_low_quality",
  "low_quality",
  "document_unreadable",
  "unreadable",
  "document_uncertain",
  "uncertain",
  "classification_uncertain",
]);

export type PassportDocumentVerificationGate =
  | {
      accepted: true;
      action: null;
      message: null;
      status: "verified" | "enhanced";
    }
  | {
      accepted: false;
      action: "retry" | "replace";
      message: string;
      status: string | null;
    };

export function isAcceptedPassportDocument(
  fields: ExtractedPassportFields | null,
): boolean {
  const verification = fields?.ai_verification;
  return verification?.available === true
    && typeof verification.status === "string"
    && ACCEPTED_STATUSES.has(verification.status);
}

export function passportDocumentVerificationGate(
  submission: Pick<
    PassportSubmission,
    "error_message" | "extracted_fields"
  >,
): PassportDocumentVerificationGate {
  const verification = submission.extracted_fields?.ai_verification;
  const status = typeof verification?.status === "string"
    ? verification.status
    : null;
  if (
    verification?.available === true
    && (status === "verified" || status === "enhanced")
  ) {
    return {
      accepted: true,
      action: null,
      message: null,
      status,
    };
  }

  const action = status && REPLACE_STATUSES.has(status)
    ? "replace"
    : "retry";
  const savedMessage = submission.error_message?.trim();
  return {
    accepted: false,
    action,
    message: savedMessage || (
      action === "replace"
        ? "This upload could not be confirmed as the passport photo and details page. Replace it with a clear scan of the correct page before continuing."
        : "We could not verify that this is the passport photo and details page yet. Your saved image is safe; retry verification before continuing."
    ),
    status,
  };
}
