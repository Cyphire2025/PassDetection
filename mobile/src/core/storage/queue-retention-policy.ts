const DAY_MS = 24 * 60 * 60 * 1_000;

/**
 * Product-owned upper bounds for durable mutation queues and their audit tails.
 *
 * Active attendance work is never trimmed merely because the app is idle. It is first moved to
 * the rejected/dead-letter state after a fixed maximum age, where it remains visible long enough
 * for operational review. Only terminal records and server receipts are age/count compacted.
 */
export const DURABLE_QUEUE_RETENTION_POLICY = Object.freeze({
  attendanceActiveAgeMs: 30 * DAY_MS,
  attendanceRejectedRetentionMs: 90 * DAY_MS,
  maximumRejectedAttendanceActionsPerTrip: 1_000,
  attendanceReceiptRetentionMs: 180 * DAY_MS,
  maximumAttendanceReceiptsPerTrip: 15_000,
  blockedDocumentJobRetentionMs: 90 * DAY_MS,
  maximumBlockedDocumentJobsPerAccount: 2_000,
  interruptedSendingAgeMs: 2 * 60 * 1_000,
});

export type DurableQueueRetentionCutoffs = Readonly<{
  attendanceActive: string;
  attendanceRejected: string;
  attendanceReceipt: string;
  blockedDocumentJob: string;
  interruptedSending: string;
}>;

export function durableQueueRetentionCutoffs(nowMs: number): DurableQueueRetentionCutoffs {
  if (!Number.isSafeInteger(nowMs) || nowMs < 0) {
    throw new Error('The queue-retention clock must be a non-negative safe integer.');
  }
  return {
    attendanceActive: new Date(
      nowMs - DURABLE_QUEUE_RETENTION_POLICY.attendanceActiveAgeMs,
    ).toISOString(),
    attendanceRejected: new Date(
      nowMs - DURABLE_QUEUE_RETENTION_POLICY.attendanceRejectedRetentionMs,
    ).toISOString(),
    attendanceReceipt: new Date(
      nowMs - DURABLE_QUEUE_RETENTION_POLICY.attendanceReceiptRetentionMs,
    ).toISOString(),
    blockedDocumentJob: new Date(
      nowMs - DURABLE_QUEUE_RETENTION_POLICY.blockedDocumentJobRetentionMs,
    ).toISOString(),
    interruptedSending: new Date(
      nowMs - DURABLE_QUEUE_RETENTION_POLICY.interruptedSendingAgeMs,
    ).toISOString(),
  };
}
