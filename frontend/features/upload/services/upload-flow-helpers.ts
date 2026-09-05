import { AxiosError, isAxiosError } from "axios";
import { previousPassportIsoDate } from "@/lib/utils/passport-date";
import {
  formatPassportNationality,
  isRecognizedPassportCountryCode,
} from "@/lib/utils/passport-country";
import { getPassportTextField } from "@/lib/utils/passport-fields";
import type {
  ExtractedPassportFields,
  PassportSubmission,
} from "@/types/passport.types";
import {
  REQUIRED_REVIEW_FIELDS,
  REVIEW_FIELDS,
} from "../components/upload-flow.constants";
import type {
  FamilyMember,
  PassportDocumentBundle,
} from "../components/upload-flow.types";
import { createIdempotencyKey } from "./upload-flow-session";

const CLIENT_COMPLETE_STATUSES = new Set([
  "submitted",
  "ai_approved",
  "needs_review",
  "staff_approved",
]);

const EXTRACTION_TERMINAL_STATUSES = new Set([
  "extraction_complete",
  "extraction_partial",
  "extraction_failed",
  "ready_for_review",
]);

export function createFamilyMember(index: number): FamilyMember {
  return {
    localId: typeof crypto !== "undefined" ? crypto.randomUUID() : `${Date.now()}-${index}`,
    name: "",
    relation: index === 0 ? "Head" : "",
    gender: "",
    email: "",
    phone: "",
    baseCity: "",
    nearestDomesticAirport: "",
    staffCode: "",
    agentEmployeeType: "",
    agentEmployeeCode: "",
    designation: "",
    agencyDealershipName: "",
    mealPreference: "",
    customAnswers: {},
    customDetailAnswers: {},
    submission: null,
    reviewFields: {},
    visaSelfie: null,
    visaPhotoSource: null,
    uploadIdempotencyKey: createIdempotencyKey(),
    extractionNotice: null,
    canRetryExtraction: false,
  };
}

export function createFamilyMembers(count: number) {
  return Array.from({ length: count }, (_, index) => createFamilyMember(index));
}

export function resizeFamilyMembers(
  current: FamilyMember[],
  count: number,
) {
  const next = [...current];
  while (next.length < count) next.push(createFamilyMember(next.length));
  return next.slice(0, count).map((member, index) => ({
    ...member,
    relation: index === 0 ? "Head" : member.relation,
  }));
}

export function emptyDocumentBundle(): PassportDocumentBundle {
  return {
    front: null,
    back: null,
    cover: null,
    back_cover: null,
    frontSource: null,
    backSource: null,
    frontManuallyCropped: false,
    backManuallyCropped: false,
  };
}

export function isClientSubmissionComplete(submission: PassportSubmission) {
  return CLIENT_COMPLETE_STATUSES.has(submission.status);
}

export function getInitialReviewFields(
  fields: ExtractedPassportFields | null,
) {
  return REVIEW_FIELDS.reduce<Record<string, string>>((current, key) => {
    current[key] = getPassportTextField(fields, key);
    return current;
  }, {});
}

export function passportHolderName(
  fields: ExtractedPassportFields | Record<string, string> | null,
) {
  if (!fields) return "";
  const givenNames = getPassportTextField(
    fields as ExtractedPassportFields,
    "given_names",
  );
  const surname = getPassportTextField(
    fields as ExtractedPassportFields,
    "surname",
  );
  return [givenNames, surname]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ");
}

export function mergeMissingReviewFields(
  current: Record<string, string>,
  fields: ExtractedPassportFields | null,
) {
  return REVIEW_FIELDS.reduce<Record<string, string>>((next, key) => {
    const value = getPassportTextField(fields, key);
    if (value.trim() && !next[key]?.trim()) {
      next[key] = value;
    }
    return next;
  }, { ...current });
}

export function hasMissingRequiredFields(fields: Record<string, string>) {
  return REQUIRED_REVIEW_FIELDS.some((key) => !fields[key]?.trim());
}

export function formatReviewFieldValue(
  key: typeof REVIEW_FIELDS[number],
  value: string,
) {
  if (!isRecognizedPassportCountryCode(value)) return value;
  if (key === "nationality") return formatPassportNationality(value);
  return value;
}

export function hasValidReviewDates(fields: Record<string, string>) {
  const dateOfBirth = fields.date_of_birth?.trim() ?? "";
  const dateOfIssue = fields.date_of_issue?.trim() ?? "";
  const dateOfExpiry = fields.date_of_expiry?.trim() ?? "";
  if (![dateOfBirth, dateOfExpiry].every(isValidIsoDate)) return false;
  if (dateOfIssue && !isValidIsoDate(dateOfIssue)) return false;

  const today = todayIsoDate();
  if (dateOfBirth >= today || (dateOfIssue && dateOfIssue > today)) return false;
  if (dateOfIssue && dateOfIssue <= dateOfBirth) return false;
  if (dateOfIssue && dateOfExpiry && dateOfIssue >= dateOfExpiry) return false;
  if (dateOfExpiry <= dateOfBirth) return false;
  return true;
}

function isValidIsoDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return year >= 1900
    && year <= 2200
    && parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day;
}

export function todayIsoDate() {
  const now = new Date();
  const localDate = new Date(now.getTime() - (now.getTimezoneOffset() * 60_000));
  return localDate.toISOString().slice(0, 10);
}

export function yesterdayIsoDate() {
  const today = todayIsoDate();
  return previousPassportIsoDate(today) ?? today;
}

export function toLabel(value: string) {
  if (value === "given_names") return "Name";
  if (value === "place_of_issue") return "Place of Issue";
  if (value === "issuing_country") return "Issuing Country (legacy)";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function isExtractionTerminal(submission: PassportSubmission) {
  return EXTRACTION_TERMINAL_STATUSES.has(submission.extraction_status)
    || submission.status === "ready_for_client_review"
    || submission.status === "review_required"
    || submission.status === "failed";
}

export function extractionNoticeFor(submission: PassportSubmission) {
  if (submission.extraction_status === "extraction_failed" || submission.status === "failed") {
    return "Automatic passport detail extraction failed. Your passport images are saved. Retry automatic reading or enter the details manually.";
  }
  if (submission.extraction_status === "extraction_partial") {
    return "Your passport pages were saved. Some details could not be read confidently, so check and complete the missing fields manually.";
  }
  return null;
}

export function canRetryExtractionFor(submission: PassportSubmission) {
  return submission.extraction_status === "extraction_failed" || submission.status === "failed";
}

export function formatFileSize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "Size unavailable";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

export function sleep(delayMs: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Operation cancelled", "AbortError"));
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Operation cancelled", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

const PROCESSING_STAGE_LABELS: Readonly<Record<string, string>> = {
  queued: "Your passport verification is queued and will begin shortly.",
  retry_queued: "Your verification is queued safely while we handle higher traffic.",
  starting: "Starting secure passport processing.",
  downloading_image: "Preparing the passport image for extraction.",
  extracting_passport_fields: "Extracting passport details from the passport image.",
  verifying_passport_fields: "Verifying the extracted passport details against the image.",
  saving_extraction_result: "Preparing the verified details for your review.",
  completed: "Passport details are ready for review.",
};

export function stageLabel(stage: string) {
  return PROCESSING_STAGE_LABELS[stage]
    ?? stage.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function submitErrorMessage(error: unknown) {
  if (isPublicApiError(error)) return error.message;
  if (isAxiosError(error)) {
    return extractApiErrorDetail(error.response?.data)
      ?? "Could not submit reviewed details. Please check the contact details.";
  }
  return "Could not submit reviewed details. Please try again.";
}

export function errorMessage(error: unknown, fallback: string) {
  if (isPublicApiError(error)) return error.message;
  if (error instanceof Error && !(error instanceof AxiosError)) return error.message;
  if (isAxiosError(error)) {
    return extractApiErrorDetail(error.response?.data) ?? fallback;
  }
  return fallback;
}

export function uploadPersistenceErrorMessage(error: unknown) {
  if (isPublicApiError(error)) return error.message;
  if (isAxiosError(error)) {
    const detail = extractApiErrorDetail(error.response?.data);
    if (error.response?.status && error.response.status >= 400 && error.response.status < 500) {
      return detail ?? "The passport pages were rejected. Check the file type and size, then try again.";
    }
    return detail
      ?? "We could not confirm that the passport pages were saved. Retry safely; the same upload will not create a duplicate.";
  }
  return "We could not confirm that the passport pages were saved. Check your connection and retry safely.";
}

function isPublicApiError(error: unknown): error is { code: string; message: string } {
  if (!error || typeof error !== "object") return false;
  const candidate = error as { code?: unknown; message?: unknown };
  return typeof candidate.code === "string" && typeof candidate.message === "string";
}

function extractApiErrorDetail(payload: unknown) {
  if (!payload || typeof payload !== "object") return null;
  const data = payload as { detail?: unknown; error?: { message?: unknown } };
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const record = item as { msg?: unknown; loc?: unknown };
        const label = Array.isArray(record.loc) ? record.loc.slice(1).join(".") : "";
        return typeof record.msg === "string" ? [label, record.msg].filter(Boolean).join(": ") : null;
      })
      .filter(Boolean)
      .join(" ");
  }
  if (typeof data.error?.message === "string") return data.error.message;
  return null;
}
