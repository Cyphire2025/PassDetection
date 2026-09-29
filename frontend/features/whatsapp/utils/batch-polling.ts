export const WHATSAPP_BATCH_FAST_POLL_MS = 2_000;
export const WHATSAPP_BATCH_MEDIUM_POLL_MS = 5_000;
export const WHATSAPP_BATCH_SLOW_POLL_MS = 10_000;
export const WHATSAPP_BATCH_MAX_POLL_MS = 30_000;
export const WHATSAPP_BATCH_TRANSIENT_RETRY_LIMIT = 3;

const ONE_MINUTE_MS = 60_000;
const FIVE_MINUTES_MS = 5 * ONE_MINUTE_MS;
const THIRTY_MINUTES_MS = 30 * ONE_MINUTE_MS;

/** Provider acceptance is not delivery. Receipts can fail after dispatch ends. */
export function whatsappAwaitingReceiptCount(
  statusCounts: Readonly<Record<string, number>> | null | undefined,
  accepted = 0,
): number {
  return statusCounts
    ? (statusCounts.submitted ?? 0) + (statusCounts.sent ?? 0)
    : accepted;
}

export function whatsappActivityPollInterval(
  queued: number | null | undefined,
  statusCounts: Readonly<Record<string, number>> | null | undefined,
  startedAt: number | null | undefined,
  accepted = 0,
  uncertain = 0,
  now: number = Date.now(),
): number | false {
  const dispatchInterval = whatsappBatchPollInterval(queued, startedAt, now);
  if (dispatchInterval !== false) return dispatchInterval;
  if (startedAt == null || !Number.isFinite(startedAt)
    || Math.max(0, now - startedAt) >= THIRTY_MINUTES_MS) return false;
  if (whatsappAwaitingReceiptCount(statusCounts, accepted) <= 0 && uncertain <= 0) return false;
  return whatsappBatchPollInterval(1, startedAt, now);
}

/** Reconcile open rosters even when this tab did not initiate the broadcast. */
export function whatsappRecipientPollInterval(
  recipients: ReadonlyArray<{ message_statuses: ReadonlyArray<{
    status: string;
    latest_resend_status: string | null;
    status_updated_at: string;
  }> }>,
  now: number = Date.now(),
): number | false {
  let interval: number | false = false;
  for (const recipient of recipients) {
    for (const message of recipient.message_statuses) {
      for (const status of [message.status, message.latest_resend_status]) {
        const queued = status === "queued" || status === "processing";
        if (!queued && status !== "submitted" && status !== "sent" && status !== "delivery_unknown") continue;
        const candidate = whatsappActivityPollInterval(queued ? 1 : 0, undefined,
          Date.parse(message.status_updated_at), 1, 0, now);
        if (candidate !== false) interval = interval === false ? candidate : Math.min(interval, candidate);
      }
    }
  }
  return interval;
}

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
    startedAt === null || startedAt === undefined || !Number.isFinite(startedAt)
      ? THIRTY_MINUTES_MS
      : Math.max(0, now - startedAt);
  if (elapsedMs < ONE_MINUTE_MS) return WHATSAPP_BATCH_FAST_POLL_MS;
  if (elapsedMs < FIVE_MINUTES_MS) return WHATSAPP_BATCH_MEDIUM_POLL_MS;
  if (elapsedMs < THIRTY_MINUTES_MS) return WHATSAPP_BATCH_SLOW_POLL_MS;
  return WHATSAPP_BATCH_MAX_POLL_MS;
}

/** Track late document receipts for a bounded period after dispatch finishes. */
export function documentActivityPollInterval(
  queued: number | null | undefined,
  statusCounts: Readonly<Record<string, number>> | null | undefined,
  startedAt: number | null | undefined,
  now: number = Date.now(),
): number | false {
  const queuedInterval = whatsappBatchPollInterval(queued, startedAt, now);
  if (queuedInterval !== false) return queuedInterval;

  if (
    startedAt === null
    || startedAt === undefined
    || !Number.isFinite(startedAt)
    || Math.max(0, now - startedAt) >= THIRTY_MINUTES_MS
  ) {
    return false;
  }

  const awaitingReceipt =
    (statusCounts?.submitted ?? 0) > 0
    || (statusCounts?.sent ?? 0) > 0
    || (statusCounts?.delivered ?? 0) > 0;
  return awaitingReceipt ? WHATSAPP_BATCH_SLOW_POLL_MS : false;
}
