export const EXTRACTION_POLL_WINDOW_MS = 65_000;
export const EXTRACTION_POLL_INITIAL_DELAY_MS = 700;
export const EXTRACTION_POLL_SUCCESS_MAX_DELAY_MS = 1_600;
export const EXTRACTION_POLL_FAILURE_MAX_DELAY_MS = 5_000;

export function isTransientExtractionPollError(error: unknown): boolean {
  if (!error || typeof error !== "object") return true;

  const code = (error as { code?: unknown }).code;
  if (typeof code !== "string") return true;
  if (code === "NETWORK_ERROR" || code === "REQUEST_TIMEOUT") return true;

  const match = /^HTTP_(\d{3})$/.exec(code);
  if (!match) return false;
  const status = Number(match[1]);
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

export function nextExtractionPollDelay(
  currentDelayMs: number,
  outcome: "success" | "failure",
): number {
  const safeCurrent = Number.isFinite(currentDelayMs) && currentDelayMs > 0
    ? currentDelayMs
    : EXTRACTION_POLL_INITIAL_DELAY_MS;

  if (outcome === "success") {
    return Math.min(EXTRACTION_POLL_SUCCESS_MAX_DELAY_MS, safeCurrent + 150);
  }

  // Keep reconciling the durable server-side job through short mobile,
  // Cloudflare, or proxy interruptions. A failure slows polling without
  // incorrectly declaring the extraction itself failed.
  return Math.min(
    EXTRACTION_POLL_FAILURE_MAX_DELAY_MS,
    Math.max(1_200, Math.round(safeCurrent * 1.7)),
  );
}
