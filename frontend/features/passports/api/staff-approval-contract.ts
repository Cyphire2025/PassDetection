import type {
  PassportSubmission,
  StaffApprovalOutcome,
  StaffApprovalRequest,
  StaffApprovalResult,
} from "@/types/passport.types";

export function serializeStaffApprovalRequest(request: StaffApprovalRequest) {
  return {
    ...(request.confirmedFields
      ? { confirmed_fields: request.confirmedFields }
      : {}),
    expected_extraction_revision: request.expectedExtractionRevision,
    ...(request.reviewReason?.trim()
      ? { review_reason: request.reviewReason.trim() }
      : {}),
  };
}

export function parseStaffApprovalResponse(
  submission: PassportSubmission,
  headers: Record<string, unknown>,
): StaffApprovalResult {
  const outcomeHeader = String(
    headers["x-staff-approval-outcome"] ?? "",
  );
  const outcome: StaffApprovalOutcome = outcomeHeader === "already_approved"
    ? "already_approved"
    : "approved";
  const revisionHeader = Number(headers["x-staff-approval-revision"]);
  return {
    submission,
    outcome,
    extractionRevision: Number.isSafeInteger(revisionHeader)
      ? revisionHeader
      : submission.extraction_revision,
  };
}
