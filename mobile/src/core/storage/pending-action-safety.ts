import { openAccountDatabase } from './database';

export type DurableActionQueueSummary = Readonly<{
  pending: number;
  sending: number;
  retryable: number;
  unresolvedReview: number;
  unsynchronized: number;
  unsynchronizedAttendanceScans: number;
  unsynchronizedDiscardAudits: number;
  unsynchronizedOtherActions: number;
}>;

type DurableActionQueueSummaryRow = Readonly<{
  pending_count: number;
  sending_count: number;
  retryable_count: number;
  unresolved_review_count: number;
  unsynchronized_attendance_count: number;
  unsynchronized_discard_count: number;
}>;

function verifiedCount(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`The durable action queue returned an invalid ${field} count.`);
  }
  return value;
}

/**
 * Reads every durable local mutation, not only attendance scans. Signing out is
 * safe only when no action can still change server state. Rejected/needs-review
 * rows are retained as encrypted operator evidence but are not upload work.
 */
export async function durableActionQueueSummary(
  namespace: string,
): Promise<DurableActionQueueSummary> {
  const database = await openAccountDatabase(namespace);
  const row = await database.getFirstAsync<DurableActionQueueSummaryRow>(
    `SELECT
       COALESCE(SUM(CASE WHEN state = 'pending' THEN 1 ELSE 0 END), 0) AS pending_count,
       COALESCE(SUM(CASE WHEN state = 'sending' THEN 1 ELSE 0 END), 0) AS sending_count,
       COALESCE(SUM(CASE WHEN state = 'retryable' THEN 1 ELSE 0 END), 0) AS retryable_count,
       COALESCE(SUM(CASE WHEN state IN ('rejected', 'needs_review') THEN 1 ELSE 0 END), 0) AS unresolved_review_count,
       COALESCE(SUM(CASE
         WHEN state IN ('pending', 'sending', 'retryable') AND action_type = 'attendance.scan'
         THEN 1 ELSE 0 END), 0) AS unsynchronized_attendance_count,
       (SELECT COUNT(*) FROM attendance_discard_tombstones discard
         WHERE discard.account_namespace = ?
           AND discard.state != 'synchronized') AS unsynchronized_discard_count
     FROM pending_actions
     WHERE account_namespace = ?`,
    namespace,
    namespace,
  );
  if (!row) throw new Error('The durable action queue could not be verified.');

  const pending = verifiedCount(row.pending_count, 'pending');
  const sending = verifiedCount(row.sending_count, 'sending');
  const retryable = verifiedCount(row.retryable_count, 'retryable');
  const unresolvedReview = verifiedCount(row.unresolved_review_count, 'review');
  const unsynchronizedAttendanceScans = verifiedCount(
    row.unsynchronized_attendance_count,
    'attendance',
  );
  const unsynchronizedDiscardAudits = verifiedCount(
    row.unsynchronized_discard_count,
    'attendance discard audit',
  );
  const unsynchronized = pending + sending + retryable + unsynchronizedDiscardAudits;
  if (unsynchronizedAttendanceScans > unsynchronized) {
    throw new Error('The durable action queue returned inconsistent counts.');
  }

  return {
    pending,
    sending,
    retryable,
    unresolvedReview,
    unsynchronized,
    unsynchronizedAttendanceScans,
    unsynchronizedDiscardAudits,
    unsynchronizedOtherActions: unsynchronized
      - unsynchronizedAttendanceScans
      - unsynchronizedDiscardAudits,
  };
}

export class UnsynchronizedActionsError extends Error {
  readonly code = 'UNSYNCHRONIZED_LOCAL_ACTIONS';
  readonly summary: DurableActionQueueSummary;

  constructor(summary: DurableActionQueueSummary) {
    super('Unsynchronized local actions must be uploaded or explicitly discarded before sign-out.');
    this.name = 'UnsynchronizedActionsError';
    this.summary = summary;
  }
}

export async function assertDurableActionQueueSynchronized(namespace: string): Promise<void> {
  const summary = await durableActionQueueSummary(namespace);
  if (summary.unsynchronized > 0) throw new UnsynchronizedActionsError(summary);
}

/** Counts every attendance record that an explicitly destructive account purge will remove. */
export async function durableAttendanceRecordCount(namespace: string): Promise<number> {
  const database = await openAccountDatabase(namespace);
  const row = await database.getFirstAsync<Readonly<{ attendance_count: number }>>(
    `SELECT COUNT(*) AS attendance_count
       FROM pending_actions
      WHERE account_namespace = ? AND action_type = 'attendance.scan'`,
    namespace,
  );
  if (!row) throw new Error('The attendance discard boundary could not be verified.');
  return verifiedCount(row.attendance_count, 'attendance discard');
}
