import type * as SQLite from 'expo-sqlite';

import { recordStorageMaintenance } from '@/core/observability/storage-observability';

import {
  DURABLE_QUEUE_RETENTION_POLICY,
  durableQueueRetentionCutoffs,
} from './queue-retention-policy';

function assertNamespace(namespace: string): void {
  if (!namespace) throw new Error('An account namespace is required for storage retention.');
}

/**
 * Applies account-scoped, crash-atomic retention while the database lifecycle coordinator has
 * established an idle window. Active work is preserved or moved to a reviewable dead letter;
 * only terminal audit tails, receipts, expired cursors, and already-blocked document jobs are
 * physically compacted.
 */
export async function applyAccountStorageRetention(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  nowMs = Date.now(),
): Promise<void> {
  assertNamespace(namespace);
  const nowIso = new Date(nowMs).toISOString();
  const cutoffs = durableQueueRetentionCutoffs(nowMs);
  const startedAtMs = performance.now();
  let changedRows = 0;
  let began = false;
  try {
    await database.execAsync('BEGIN IMMEDIATE');
    began = true;

    changedRows += (await database.runAsync(
      `UPDATE pending_actions
          SET state = 'retryable', next_attempt_at = NULL,
              last_error_code = 'INTERRUPTED_RETRY', updated_at = ?
        WHERE account_namespace = ? AND action_type = 'attendance.scan'
          AND state = 'sending' AND updated_at < ?`,
      nowIso,
      namespace,
      cutoffs.interruptedSending,
    )).changes;
    changedRows += (await database.runAsync(
      `UPDATE pending_actions
          SET state = 'rejected', next_attempt_at = NULL,
              last_error_code = 'LOCAL_QUEUE_EXPIRED', updated_at = ?
        WHERE account_namespace = ? AND action_type = 'attendance.scan'
          AND state IN ('pending', 'sending', 'retryable') AND created_at < ?`,
      nowIso,
      namespace,
      cutoffs.attendanceActive,
    )).changes;
    changedRows += (await database.runAsync(
      `DELETE FROM pending_actions
        WHERE account_namespace = ? AND action_type = 'attendance.scan'
          AND state IN ('needs_review', 'rejected') AND updated_at < ?`,
      namespace,
      cutoffs.attendanceRejected,
    )).changes;
    changedRows += (await database.runAsync(
      `DELETE FROM pending_actions
        WHERE rowid IN (
          SELECT rowid
            FROM (
              SELECT rowid,
                     ROW_NUMBER() OVER (
                       PARTITION BY trip_id
                       ORDER BY updated_at DESC, idempotency_key DESC
                     ) AS retention_rank
                FROM pending_actions
               WHERE account_namespace = ? AND action_type = 'attendance.scan'
                 AND state IN ('needs_review', 'rejected')
            ) ranked
           WHERE retention_rank > ${DURABLE_QUEUE_RETENTION_POLICY.maximumRejectedAttendanceActionsPerTrip}
        )`,
      namespace,
    )).changes;

    changedRows += (await database.runAsync(
      `DELETE FROM attendance_scan_receipts
        WHERE account_namespace = ? AND accepted_at < ?`,
      namespace,
      cutoffs.attendanceReceipt,
    )).changes;
    changedRows += (await database.runAsync(
      `DELETE FROM attendance_scan_receipts
        WHERE rowid IN (
          SELECT rowid
            FROM (
              SELECT rowid,
                     ROW_NUMBER() OVER (
                       PARTITION BY trip_id
                       ORDER BY accepted_at DESC, client_event_id DESC
                     ) AS retention_rank
                FROM attendance_scan_receipts
               WHERE account_namespace = ?
            ) ranked
           WHERE retention_rank > ${DURABLE_QUEUE_RETENTION_POLICY.maximumAttendanceReceiptsPerTrip}
        )`,
      namespace,
    )).changes;

    changedRows += (await database.runAsync(
      `DELETE FROM offline_document_jobs
        WHERE account_namespace = ? AND state = 'blocked' AND updated_at < ?`,
      namespace,
      cutoffs.blockedDocumentJob,
    )).changes;
    changedRows += (await database.runAsync(
      `DELETE FROM offline_document_jobs
        WHERE document_id IN (
          SELECT document_id
            FROM offline_document_jobs
           WHERE account_namespace = ? AND state = 'blocked'
           ORDER BY updated_at DESC, document_id DESC
           LIMIT -1 OFFSET ${DURABLE_QUEUE_RETENTION_POLICY.maximumBlockedDocumentJobsPerAccount}
        )
          AND account_namespace = ? AND state = 'blocked'`,
      namespace,
      namespace,
    )).changes;
    changedRows += (await database.runAsync(
      `DELETE FROM local_roster_cursors
        WHERE account_namespace = ? AND expires_at_epoch_ms <= ?`,
      namespace,
      nowMs,
    )).changes;

    await database.execAsync('COMMIT');
    began = false;
    recordStorageMaintenance(performance.now() - startedAtMs, changedRows, 'success');
  } catch (error) {
    if (began) await database.execAsync('ROLLBACK').catch(() => undefined);
    recordStorageMaintenance(performance.now() - startedAtMs, 0, 'failure');
    throw error;
  }
}
