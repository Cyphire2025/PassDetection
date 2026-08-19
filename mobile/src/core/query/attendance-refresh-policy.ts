import { ApiError } from '@/core/api/client';

export const ACTIVE_ATTENDANCE_MIN_REFRESH_MS = 8_000;
export const ACTIVE_ATTENDANCE_MAX_REFRESH_MS = 15_000;
export const ACTIVE_ATTENDANCE_MAX_SERVER_BACKOFF_MS = 5 * 60_000;

type AttendanceRefreshInput = Readonly<{
  hasActiveSession: boolean;
  routeFocused: boolean;
  error?: unknown;
  randomValue?: number;
}>;

export function activeAttendanceRefreshInterval({
  hasActiveSession,
  routeFocused,
  error,
  randomValue = Math.random(),
}: AttendanceRefreshInput): number | false {
  if (!hasActiveSession || !routeFocused) return false;
  const boundedRandom = Math.min(1, Math.max(0, randomValue));
  const jitteredInterval = Math.round(
    ACTIVE_ATTENDANCE_MIN_REFRESH_MS +
    (ACTIVE_ATTENDANCE_MAX_REFRESH_MS - ACTIVE_ATTENDANCE_MIN_REFRESH_MS) * boundedRandom,
  );
  if (!(error instanceof ApiError) || error.retryAfterSeconds === null) {
    return jitteredInterval;
  }
  return Math.max(
    jitteredInterval,
    Math.min(
      ACTIVE_ATTENDANCE_MAX_SERVER_BACKOFF_MS,
      Math.max(0, error.retryAfterSeconds * 1_000),
    ),
  );
}
