export const WHATSAPP_BATCH_FAST_POLL_MS = 2_000;
export const WHATSAPP_BATCH_MEDIUM_POLL_MS = 5_000;
export const WHATSAPP_BATCH_SLOW_POLL_MS = 10_000;
export const WHATSAPP_BATCH_MAX_POLL_MS = 30_000;
export const WHATSAPP_BATCH_TRANSIENT_RETRY_LIMIT = 3;

const ONE_MINUTE_MS = 60_000;
const FIVE_MINUTES_MS = 5 * ONE_MINUTE_MS;
const THIRTY_MINUTES_MS = 30 * ONE_MINUTE_MS;

export function whatsappBatchHttpStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) return undefined;

  const response = (error as { response?: unknown }).response;
  if (typeof response === "object" && response !== null) {
    const status = (response as { status?: unknown }).status;
    if (typeof status === "number" && Number.isInteger(status)) return status;
  }

  const code = (error as { code?: unknown }).code;
  if (typeof code !== "string") return undefined;
  const match = /^HTTP_(\d{3})$/.exec(code);
  return match ? Number(match[1]) : undefined;
}

export function isMissingWhatsAppBatchStatus(
  status: number | undefined,
): boolean {
  return status === 404;
}

/**
 * A missing batch is terminal because the server no longer has progress to
 * report. Network failures and server errors remain retryable.
 */
export function shouldRetryWhatsAppBatchStatus(
  failureCount: number,
  status: number | undefined,
): boolean {
  if (isMissingWhatsAppBatchStatus(status)) return false;
  return failureCount < WHATSAPP_BATCH_TRANSIENT_RETRY_LIMIT;
}

/**
 * Keep polling every queued batch, but reduce request pressure as it ages.
 * A terminal server response (queued === 0) is the only normal stop signal.
 */
export function whatsappBatchPollInterval(
  queued: number | null | undefined,
  startedAt: number | null | undefined,
  now: number = Date.now(),
): number | false {
  if (queued !== null && queued !== undefined && queued <= 0) return false;

  // Missing client timing metadata must not terminate polling or create a
  // hot loop; use the conservative capped interval until the server finishes.
  const elapsedMs =
    startedAt === null || startedAt === undefined
      ? THIRTY_MINUTES_MS
      : Math.max(0, now - startedAt);
  if (elapsedMs < ONE_MINUTE_MS) return WHATSAPP_BATCH_FAST_POLL_MS;
  if (elapsedMs < FIVE_MINUTES_MS) return WHATSAPP_BATCH_MEDIUM_POLL_MS;
  if (elapsedMs < THIRTY_MINUTES_MS) return WHATSAPP_BATCH_SLOW_POLL_MS;
  return WHATSAPP_BATCH_MAX_POLL_MS;
}
