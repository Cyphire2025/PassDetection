import { trustedAttendanceScanTime } from './trusted-scan-time';

/** Retention is destructive, so it may use only installation-bound trusted
 * server time. Queue visibility and delivery continue when that clock is
 * temporarily unavailable; compaction waits for the next trusted lease. */
export async function trustedQueueRetentionTime(): Promise<number | null> {
  try {
    return (await trustedAttendanceScanTime()).timestampMs;
  } catch {
    return null;
  }
}
