import {
  DURABLE_QUEUE_RETENTION_POLICY,
  durableQueueRetentionCutoffs,
} from '@/core/storage/queue-retention-policy';

// A device can hold a 10k-person activity plus headroom, while stale or hostile
// input is forced into a bounded, reviewable audit tail instead of growing forever.
export const ATTENDANCE_QUEUE_POLICY = Object.freeze({
  maxActivePerTrip: 12_000,
  maxActivePerAccount: 24_000,
  minActivePerSession: 100,
  sessionPopulationHeadroom: 25,
  sessionPopulationHeadroomRatio: 0.1,
  maxActiveAgeMs: DURABLE_QUEUE_RETENTION_POLICY.attendanceActiveAgeMs,
  rejectedRetentionMs: DURABLE_QUEUE_RETENTION_POLICY.attendanceRejectedRetentionMs,
  maxRejectedPerTrip:
    DURABLE_QUEUE_RETENTION_POLICY.maximumRejectedAttendanceActionsPerTrip,
  receiptRetentionMs: DURABLE_QUEUE_RETENTION_POLICY.attendanceReceiptRetentionMs,
  maxReceiptsPerTrip: DURABLE_QUEUE_RETENTION_POLICY.maximumAttendanceReceiptsPerTrip,
});

export function attendanceDedupeMaterial(
  account: string,
  tripId: string,
  sessionId: string,
  signedQr: string,
): string {
  return `${account}|${tripId}|${sessionId}|${signedQr}`;
}

export function attendanceSessionQueueLimit(assignedCount?: number): number {
  if (assignedCount === undefined || !Number.isFinite(assignedCount)) {
    return ATTENDANCE_QUEUE_POLICY.maxActivePerTrip;
  }
  const population = Math.max(0, Math.floor(assignedCount));
  const headroom = Math.max(
    ATTENDANCE_QUEUE_POLICY.sessionPopulationHeadroom,
    Math.ceil(population * ATTENDANCE_QUEUE_POLICY.sessionPopulationHeadroomRatio),
  );
  return Math.min(
    ATTENDANCE_QUEUE_POLICY.maxActivePerTrip,
    Math.max(ATTENDANCE_QUEUE_POLICY.minActivePerSession, population + headroom),
  );
}

export function attendanceQueueCutoffs(nowMs: number): Readonly<{
  active: string;
  rejected: string;
  receipt: string;
}> {
  const cutoffs = durableQueueRetentionCutoffs(nowMs);
  return {
    active: cutoffs.attendanceActive,
    rejected: cutoffs.attendanceRejected,
    receipt: cutoffs.attendanceReceipt,
  };
}
