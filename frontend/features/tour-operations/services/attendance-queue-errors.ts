import { isRecoverableAttendanceScanError } from "./attendance-sync-policy";

export function isLikelyNetworkFailure(error: unknown) {
  if (!navigator.onLine) return true;
  const code = getErrorCode(error);
  const message = getErrorMessage(error);
  return isRecoverableAttendanceScanError(code)
    || code === "NETWORK_ERROR"
    || code === "REQUEST_TIMEOUT"
    || /network|fetch|timeout|offline|connection/i.test(message);
}

export function getErrorCode(error: unknown) {
  if (typeof error !== "object" || error === null || !("code" in error)) return "";
  return String(error.code);
}

export function getRetryAfterMs(error: unknown) {
  if (typeof error !== "object" || error === null || !("retryAfterMs" in error)) {
    return undefined;
  }
  const value = Number(error.retryAfterMs);
  return Number.isFinite(value) ? Math.max(0, value) : undefined;
}

export function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (typeof error !== "object" || error === null || !("message" in error)) return "";
  return String(error.message);
}
