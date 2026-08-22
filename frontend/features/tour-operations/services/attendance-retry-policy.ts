const BASE_RETRY_DELAY_MS = 1_000;
const MAX_LOCAL_RETRY_DELAY_MS = 60_000;
const MAX_RETRY_DELAY_MS = 15 * 60_000;
const MAX_JITTER_MS = 5_000;

export type AttendanceRetryState = Readonly<{
  attemptCount: number;
  nextAttemptAt: string;
}>;

export type AttendanceCloseoutQueueRow = Readonly<{
  attemptCount: number;
  deliveryState?: "pending" | "sending";
  groupId?: string;
  queuedAt: string;
  sessionId: string;
}>;

export type AttendanceCloseoutQueueCounts = Readonly<{
  oldestQueuedAt: string | null;
  pending: number;
  retryable: number;
  sending: number;
}>;

export function attendanceRetryState({
  previousAttemptCount,
  retryAfterMs,
  nowMs = Date.now(),
  randomValue = Math.random(),
}: {
  previousAttemptCount: number;
  retryAfterMs?: number;
  nowMs?: number;
  randomValue?: number;
}): AttendanceRetryState {
  const attemptCount = Math.max(0, Math.trunc(previousAttemptCount)) + 1;
  const exponentialDelay = Math.min(
    MAX_LOCAL_RETRY_DELAY_MS,
    BASE_RETRY_DELAY_MS * (2 ** Math.min(attemptCount - 1, 16)),
  );
  const serverDelay = Number.isFinite(retryAfterMs)
    ? Math.max(0, Math.trunc(retryAfterMs ?? 0))
    : 0;
  const requiredDelay = Math.min(
    MAX_RETRY_DELAY_MS,
    Math.max(exponentialDelay, serverDelay),
  );
  const jitterWindow = Math.min(MAX_JITTER_MS, Math.ceil(requiredDelay * 0.2));
  const boundedRandom = Math.min(1, Math.max(0, randomValue));
  const jitter = Math.floor(jitterWindow * boundedRandom);
  const delayMs = Math.min(MAX_RETRY_DELAY_MS, requiredDelay + jitter);

  return {
    attemptCount,
    nextAttemptAt: new Date(nowMs + delayMs).toISOString(),
  };
}

export function attendanceAttemptAtMs(
  nextAttemptAt: string | undefined,
  fallbackAt: string,
): number {
  const parsed = nextAttemptAt ? Date.parse(nextAttemptAt) : Number.NaN;
  if (Number.isFinite(parsed)) return parsed;
  const fallback = Date.parse(fallbackAt);
  return Number.isFinite(fallback) ? fallback : 0;
}

export function isAttendanceAttemptEligible(
  nextAttemptAt: string | undefined,
  fallbackAt: string,
  nowMs = Date.now(),
) {
  return attendanceAttemptAtMs(nextAttemptAt, fallbackAt) <= nowMs;
}

export function earliestAttendanceAttemptAt(
  rows: ReadonlyArray<{ nextAttemptAt?: string; queuedAt: string }>,
): string | null {
  let earliestMs = Number.POSITIVE_INFINITY;
  for (const row of rows) {
    earliestMs = Math.min(
      earliestMs,
      attendanceAttemptAtMs(row.nextAttemptAt, row.queuedAt),
    );
  }
  return Number.isFinite(earliestMs) ? new Date(earliestMs).toISOString() : null;
}

export function classifyAttendanceCloseoutQueue(
  rows: ReadonlyArray<AttendanceCloseoutQueueRow>,
  groupId: string,
  sessionId: string,
): AttendanceCloseoutQueueCounts {
  let pending = 0;
  let retryable = 0;
  let sending = 0;
  let oldestQueuedAtMs = Number.POSITIVE_INFINITY;

  for (const row of rows) {
    if ((row.groupId && row.groupId !== groupId) || row.sessionId !== sessionId) {
      continue;
    }
    const queuedAtMs = Date.parse(row.queuedAt);
    if (Number.isFinite(queuedAtMs)) {
      oldestQueuedAtMs = Math.min(oldestQueuedAtMs, queuedAtMs);
    }
    if (row.deliveryState === "sending") {
      sending += 1;
    } else if (row.attemptCount > 0) {
      retryable += 1;
    } else {
      pending += 1;
    }
  }

  return {
    pending,
    sending,
    retryable,
    oldestQueuedAt: Number.isFinite(oldestQueuedAtMs)
      ? new Date(oldestQueuedAtMs).toISOString()
      : null,
  };
}
