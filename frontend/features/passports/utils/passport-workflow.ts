import type {
  PassportExtractionStatus,
  PassportStatus,
} from "@/types/passport.types";

const TRANSIENT_WORKFLOW_STATUSES = new Set<PassportStatus>([
  "processing",
  "pending_extraction",
  "extracting",
  "submitted",
]);

export function isPassportWorkflowPending(
  status: PassportStatus | string | null | undefined,
  extractionStatus?: PassportExtractionStatus | string | null,
): boolean {
  return extractionStatus === "processing"
    || (typeof status === "string" && TRANSIENT_WORKFLOW_STATUSES.has(status as PassportStatus));
}
