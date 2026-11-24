import { AxiosError, isAxiosError } from "axios";
import { previousPassportIsoDate } from "@/lib/utils/passport-date";
import { formatPassportNationality, isRecognizedPassportCountryCode } from "@/lib/utils/passport-country";
import { REQUIRED_REVIEW_FIELDS, REVIEW_FIELDS } from "../components/upload-flow.constants";

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

export function errorMessage(error: unknown, fallback: string) {
  if (isPublicApiError(error)) return error.message;
  if (error instanceof Error && !(error instanceof AxiosError)) return error.message;
  if (isAxiosError(error)) {
    return extractApiErrorDetail(error.response?.data) ?? fallback;
  }
  return fallback;
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
