import {
  DURABLE_QUEUE_RETENTION_POLICY,
  durableQueueRetentionCutoffs,
} from '../queue-retention-policy';

describe('durable queue retention policy', () => {
  test('keeps active work separate from the bounded reviewable audit tail', () => {
    expect(DURABLE_QUEUE_RETENTION_POLICY).toMatchObject({
      attendanceActiveAgeMs: 30 * 24 * 60 * 60 * 1_000,
      attendanceRejectedRetentionMs: 90 * 24 * 60 * 60 * 1_000,
      maximumRejectedAttendanceActionsPerTrip: 1_000,
      attendanceReceiptRetentionMs: 180 * 24 * 60 * 60 * 1_000,
      maximumAttendanceReceiptsPerTrip: 15_000,
      maximumBlockedDocumentJobsPerAccount: 2_000,
    });
  });

  test('derives every cutoff from one validated maintenance clock', () => {
    const now = Date.parse('2030-06-01T00:00:00.000Z');
    const cutoffs = durableQueueRetentionCutoffs(now);

    expect(Date.parse(cutoffs.attendanceActive)).toBe(
      now - DURABLE_QUEUE_RETENTION_POLICY.attendanceActiveAgeMs,
    );
    expect(Date.parse(cutoffs.attendanceRejected)).toBe(
      now - DURABLE_QUEUE_RETENTION_POLICY.attendanceRejectedRetentionMs,
    );
    expect(Date.parse(cutoffs.blockedDocumentJob)).toBe(
      now - DURABLE_QUEUE_RETENTION_POLICY.blockedDocumentJobRetentionMs,
    );
    expect(() => durableQueueRetentionCutoffs(-1)).toThrow('non-negative');
  });
});
