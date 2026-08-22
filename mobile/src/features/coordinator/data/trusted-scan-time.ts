import {
  offlineAuthorizationReadiness,
} from '@/core/auth/offline-authorization-readiness';
import { OfflineAuthorizationError } from '@/core/auth/offline-authorization';

export const SCAN_CLOCK_DRIFT_WARNING_MS = 5 * 60 * 1_000;

export type TrustedAttendanceScanTime = Readonly<{
  /** Signed server time advanced by the lease's monotonic clock anchor. */
  timestampMs: number;
  /** Diagnostic only. Never used as attendance evidence or authorization. */
  deviceClockDifferenceMs: number;
}>;

/**
 * Returns the only timestamp permitted for a queued attendance record.
 * The underlying lease is signature-, identity-, installation-, expiry-, and
 * rollback-checked. Date.now() is sampled only to explain clock drift to the
 * operator; it is never returned as authoritative scan evidence.
 */
export async function trustedAttendanceScanTime(): Promise<TrustedAttendanceScanTime> {
  let authorization: Awaited<ReturnType<typeof offlineAuthorizationReadiness>>;
  try {
    authorization = await offlineAuthorizationReadiness();
  } catch (error) {
    if (error instanceof OfflineAuthorizationError) throw error;
    throw new OfflineAuthorizationError('clock_unavailable');
  }
  const trustedServerTimeMs = Math.floor(authorization.trustedServerTimeMs);
  const observedDeviceTimeMs = Date.now();
  if (
    !Number.isSafeInteger(trustedServerTimeMs)
    || trustedServerTimeMs <= 0
    || !Number.isSafeInteger(observedDeviceTimeMs)
    || observedDeviceTimeMs < 0
  ) {
    throw new OfflineAuthorizationError('clock_unavailable');
  }
  return {
    timestampMs: trustedServerTimeMs,
    deviceClockDifferenceMs: observedDeviceTimeMs - trustedServerTimeMs,
  };
}

export function trustedScanClockDriftNotice(differenceMs: number): string | null {
  if (!Number.isFinite(differenceMs)) {
    return 'Verified event time is unavailable. Scanning is paused until you reconnect and sign in again.';
  }
  if (Math.abs(differenceMs) <= SCAN_CLOCK_DRIFT_WARNING_MS) return null;
  return 'This device clock differs from verified event time by more than 5 minutes. Saved scans will use verified event time.';
}
