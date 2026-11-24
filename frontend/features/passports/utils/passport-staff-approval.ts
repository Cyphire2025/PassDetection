import type { StaffApprovalOutcome, StaffApprovalRequest } from "@/types/passport.types";
import { PASSPORT_REVIEW_FIELDS } from "./passport-review-fields.ts";

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
