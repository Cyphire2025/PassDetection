const MAX_TIMER_DELAY_MS = 2_147_483_647;

type AttendanceRetryTimer = {
  dueAtMs: number;
  handle: ReturnType<typeof setTimeout>;
};

type AttendanceRetryLookup = {
  getFirstAsync<T>(sql: string, ...parameters: unknown[]): Promise<T | null>;
};

const retryTimers = new Map<string, AttendanceRetryTimer>();

function retryTimerKey(account: string, tripId: string): string {
  return `${account}:${tripId}`;
}

export function clearAttendanceRetryTimer(account: string, tripId: string): void {
  const key = retryTimerKey(account, tripId);
  const current = retryTimers.get(key);
  if (!current) return;
  clearTimeout(current.handle);
  retryTimers.delete(key);
}

function scheduleAttendanceRetry(
  account: string,
  tripId: string,
  nextAttemptAt: string | null,
  onDue: () => void,
): void {
  const key = retryTimerKey(account, tripId);
  if (!nextAttemptAt) {
    clearAttendanceRetryTimer(account, tripId);
    return;
  }
  const dueAtMs = Date.parse(nextAttemptAt);
  if (!Number.isFinite(dueAtMs)) {
    clearAttendanceRetryTimer(account, tripId);
    return;
  }
  const current = retryTimers.get(key);
  if (current?.dueAtMs === dueAtMs) return;
  clearAttendanceRetryTimer(account, tripId);

  const arm = (): void => {
    const remainingMs = dueAtMs - Date.now();
    if (remainingMs > 0) {
      const handle = setTimeout(arm, Math.min(remainingMs, MAX_TIMER_DELAY_MS));
      retryTimers.set(key, { dueAtMs, handle });
      return;
    }
    retryTimers.delete(key);
    onDue();
  };

  const handle = setTimeout(
    arm,
    Math.min(Math.max(0, dueAtMs - Date.now()), MAX_TIMER_DELAY_MS),
  );
  retryTimers.set(key, { dueAtMs, handle });
}

export async function scheduleNextAttendanceRetry(
  database: AttendanceRetryLookup,
  account: string,
  tripId: string,
  onDue: () => void,
): Promise<void> {
  const row = await database.getFirstAsync<{ next_attempt_at: string | null }>(
    `SELECT MIN(next_attempt_at) AS next_attempt_at
       FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state = 'retryable' AND next_attempt_at IS NOT NULL`,
    account,
    tripId,
  );
  scheduleAttendanceRetry(account, tripId, row?.next_attempt_at ?? null, onDue);
}

export function resetAttendanceRetryTimersForTests(): void {
  for (const { handle } of retryTimers.values()) clearTimeout(handle);
  retryTimers.clear();
}
