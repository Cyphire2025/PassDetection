import { isAxiosError } from "axios";
import {
  createUploadRecoveryRecord,
  parseUploadRecoveryRecord,
  serializeUploadRecoveryRecord,
} from "./upload-recovery";

const PERMANENT_QUALIFIER_ERROR_STATUSES = new Set([
  400,
  401,
  403,
  404,
  410,
  422,
]);
const MISSING_SUBMISSION_STATUSES = new Set([404, 410]);

function uploadRecoveryStorageKey(groupToken: string) {
  return `gct:upload-recovery:${groupToken}`;
}

function qualifierStorageKey(groupToken: string) {
  return `gct:qualifier-selection:${groupToken}`;
}

export function createIdempotencyKey() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  if (
    typeof crypto !== "undefined"
    && typeof crypto.getRandomValues === "function"
  ) {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    return Array.from(
      bytes,
      (value) => value.toString(16).padStart(2, "0"),
    ).join("");
  }
  throw new Error(
    "Secure random number generation is required for passport upload.",
  );
}

export function readUploadRecoveryRecord(groupToken: string) {
  try {
    return parseUploadRecoveryRecord(
      window.sessionStorage.getItem(uploadRecoveryStorageKey(groupToken)),
    );
  } catch {
    return null;
  }
}

export function writeUploadRecoveryRecord(
  groupToken: string,
  record: ReturnType<typeof createUploadRecoveryRecord>,
) {
  try {
    window.sessionStorage.setItem(
      uploadRecoveryStorageKey(groupToken),
      serializeUploadRecoveryRecord(record),
    );
  } catch {
    // Recovery storage is optional in privacy-restricted in-app browsers.
    // Backend idempotency still protects the active in-memory attempt.
  }
}

export function readQualifierSelectionToken(groupToken: string) {
  try {
    return window.sessionStorage.getItem(qualifierStorageKey(groupToken));
  } catch {
    return null;
  }
}

export function writeQualifierSelectionToken(
  groupToken: string,
  selectionToken: string,
) {
  try {
    window.sessionStorage.setItem(
      qualifierStorageKey(groupToken),
      selectionToken,
    );
  } catch {
    // Session storage is an optional recovery aid. The in-memory bearer token
    // remains sufficient for the current upload attempt.
  }
}

export function clearQualifierSelectionToken(groupToken: string) {
  try {
    window.sessionStorage.removeItem(qualifierStorageKey(groupToken));
  } catch {
    // Storage may be unavailable in privacy-restricted in-app browsers.
  }
}

export function isPermanentQualifierRestoreError(error: unknown) {
  if (!isAxiosError(error)) return false;
  return PERMANENT_QUALIFIER_ERROR_STATUSES.has(error.response?.status ?? 0);
}

export function isMissingSavedSubmissionError(error: unknown) {
  if (!isAxiosError(error)) return false;
  return MISSING_SUBMISSION_STATUSES.has(error.response?.status ?? 0);
}
