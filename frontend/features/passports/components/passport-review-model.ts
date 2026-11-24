import {
  formatPassportDateForUi,
  previousPassportIsoDate,
  isValidPassportIsoDate as isValidIsoDate,
} from "@/lib/utils/passport-date";
import { formatPassportNationality } from "@/lib/utils/passport-country";
import type { PassportSubmission, PassportExtractionConflict } from "@/types/passport.types";
import { PASSPORT_REVIEW_FIELDS as REVIEW_FIELDS } from "../utils/passport-review";

export function readManualImageChangeError(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    if ("response" in error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    }
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return "Could not change this image. Please try again.";
}

export function formatQrStatus(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function qrStatusVariant(status?: string): "default" | "success" | "warning" | "destructive" | "outline" {
  if (status === "active") return "success";
  if (status === "inactive" || status === "expired") return "warning";
  if (status === "revoked") return "destructive";
  return "outline";
}
export function readReviewActionError(error: unknown, fallback: string) {
  if (!error || typeof error !== "object") return fallback;
  const candidate = error as { message?: unknown };
  return typeof candidate.message === "string" && candidate.message.trim()
    ? candidate.message
    : fallback;
}

export function getWorkflowStatusMessage(status: PassportSubmission["status"]) {
  const messages: Partial<Record<PassportSubmission["status"], string>> = {
    pending_extraction: "The passport is saved and queued for automatic extraction. This page refreshes automatically.",
    extracting: "AI is reading the saved passport. This page refreshes automatically until the fields are ready.",
    processing: "The saved passport is being processed. This page refreshes automatically.",
    ready_for_client_review: "Automatic extraction is complete and waiting for the client to review and submit the details.",
    submitted: "AI verification is running. This page refreshes automatically until a final decision is ready.",
  };
  return messages[status] ?? null;
}

export function getExtractionConflicts(passport: PassportSubmission): PassportExtractionConflict[] {
  const direct = normalizeExtractionConflicts(passport.extraction_conflicts);
  if (direct.length > 0) return direct;
  return normalizeExtractionConflicts(passport.extracted_fields?.manual_review_conflicts);
}

function normalizeExtractionConflicts(value: unknown): PassportExtractionConflict[] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const candidate = item as Record<string, unknown>;
      if (
        typeof candidate.field !== "string"
        || typeof candidate.manual_value !== "string"
        || (candidate.extracted_value !== null && typeof candidate.extracted_value !== "string")
      ) {
        return [];
      }
      const status = candidate.status === "not_extracted" ? "not_extracted" : "mismatch";
      return [{
        field: candidate.field,
        manual_value: candidate.manual_value,
        extracted_value: candidate.extracted_value,
        status,
      }];
    });
  }

  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>).flatMap(([field, item]) => {
      if (!item || typeof item !== "object") return [];
      const candidate = item as Record<string, unknown>;
      if (
        typeof candidate.manual_value !== "string"
        || (candidate.extracted_value !== null && typeof candidate.extracted_value !== "string")
      ) {
        return [];
      }
      return [{
        field,
        manual_value: candidate.manual_value,
        extracted_value: candidate.extracted_value,
        status: candidate.status === "not_extracted" ? "not_extracted" as const : "mismatch" as const,
      }];
    });
  }
  return [];
}

export function processingStageLabel(stage: string | null | undefined) {
  const labels: Record<string, string> = {
    queued: "Queued safely. Processing will begin shortly.",
    running: "Reading the saved passport image.",
    downloading_image: "Preparing the saved passport image.",
    extracting_passport_fields: "Extracting passport details from the image.",
    verifying_passport_fields: "Checking extracted details against the passport.",
    saving_extraction_result: "Saving the verified details and comparison.",
  };
  return labels[stage ?? ""] ?? "Reading and verifying the saved passport image.";
}

export function isReviewField(field: string): field is typeof REVIEW_FIELDS[number] {
  return (REVIEW_FIELDS as readonly string[]).includes(field);
}

export function valuesMatch(left: string, right: string) {
  return left.trim().toLocaleUpperCase("en") === right.trim().toLocaleUpperCase("en");
}

export function formatConflictValue(field: string, value: string) {
  if (field === "nationality") {
    return formatPassportNationality(value) || value;
  }
  if (field === "date_of_birth" || field === "date_of_issue" || field === "date_of_expiry") {
    return formatPassportDateForUi(value) || value;
  }
  return value;
}
export function toLabel(value: string) {
  if (value === "given_names") return "Name";
  if (value === "place_of_issue") return "Place of Issue";
  if (value === "issuing_country") return "Issuing Country (legacy)";
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
export function hasValidReviewDates(fields: Record<string, string>) {
  const dateOfBirth = fields.date_of_birth?.trim() ?? "";
  const dateOfIssue = fields.date_of_issue?.trim() ?? "";
  const dateOfExpiry = fields.date_of_expiry?.trim() ?? "";
  for (const value of [dateOfBirth, dateOfIssue, dateOfExpiry]) {
    if (value && !isValidIsoDate(value)) return false;
  }
  const today = todayIsoDate();
  if (dateOfBirth && dateOfBirth >= today) return false;
  if (dateOfIssue && dateOfIssue > today) return false;
  if (dateOfBirth && dateOfIssue && dateOfIssue <= dateOfBirth) return false;
  if (dateOfIssue && dateOfExpiry && dateOfIssue >= dateOfExpiry) return false;
  if (dateOfBirth && dateOfExpiry && dateOfExpiry <= dateOfBirth) return false;
  return true;
}

export function todayIsoDate() {
  const now = new Date();
  return new Date(now.getTime() - (now.getTimezoneOffset() * 60_000)).toISOString().slice(0, 10);
}

export function yesterdayIsoDate() {
  const today = todayIsoDate();
  return previousPassportIsoDate(today) ?? today;
}
