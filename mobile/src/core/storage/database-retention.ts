import type * as SQLite from 'expo-sqlite';

import { recordStorageMaintenance } from '@/core/observability/storage-observability';

import {
  DURABLE_QUEUE_RETENTION_POLICY,
  durableQueueRetentionCutoffs,
} from './queue-retention-policy';

export const MY_PHOTOS_METADATA_RETENTION_POLICY = Object.freeze({
  maximumRemovedDownloadsPerPassengerTrip: 1_000,
  maximumOrphanedTerminalBatchesPerPassengerTrip: 100,
});

export type AccountStorageRetentionTimes = Readonly<{
  /** Device time is acceptable only for non-attendance housekeeping. */
  maintenanceNowMs: number;
  /**
   * Attendance mutation retention is destructive and therefore requires the
   * installation-bound, server-derived clock. A missing clock skips the whole
   * attendance class while unrelated maintenance continues.
   */
  trustedAttendanceNowMs: number | null;
}>;

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
  times: AccountStorageRetentionTimes,
): Promise<void> {
  assertNamespace(namespace);
  const maintenanceCutoffs = durableQueueRetentionCutoffs(times.maintenanceNowMs);
  const attendanceCutoffs = times.trustedAttendanceNowMs === null
    ? null
    : durableQueueRetentionCutoffs(times.trustedAttendanceNowMs);
  const attendanceNowIso = times.trustedAttendanceNowMs === null
    ? null
    : new Date(times.trustedAttendanceNowMs).toISOString();
  const startedAtMs = performance.now();
  let changedRows = 0;
  let began = false;
  try {
    await database.execAsync('BEGIN IMMEDIATE');
    began = true;

    if (attendanceCutoffs && attendanceNowIso) {
      changedRows += (await database.runAsync(
        `UPDATE pending_actions
            SET state = 'retryable', next_attempt_at = NULL,
                last_error_code = 'INTERRUPTED_RETRY', updated_at = ?
          WHERE account_namespace = ? AND action_type = 'attendance.scan'
            AND state = 'sending' AND updated_at < ?`,
        attendanceNowIso,
        namespace,
        attendanceCutoffs.interruptedSending,
      )).changes;
      changedRows += (await database.runAsync(
        `UPDATE pending_actions
            SET state = 'rejected', next_attempt_at = NULL,
                last_error_code = 'LOCAL_QUEUE_EXPIRED', updated_at = ?
          WHERE account_namespace = ? AND action_type = 'attendance.scan'
            AND state IN ('pending', 'sending', 'retryable') AND created_at < ?`,
        attendanceNowIso,
        namespace,
        attendanceCutoffs.attendanceActive,
      )).changes;
      changedRows += (await database.runAsync(
        `DELETE FROM pending_actions
          WHERE account_namespace = ? AND action_type = 'attendance.scan'
            AND state IN ('needs_review', 'rejected') AND updated_at < ?`,
        namespace,
        attendanceCutoffs.attendanceRejected,
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
        attendanceCutoffs.attendanceReceipt,
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
    }

    changedRows += (await database.runAsync(
      `DELETE FROM offline_document_jobs
        WHERE account_namespace = ? AND state = 'blocked' AND updated_at < ?`,
      namespace,
      maintenanceCutoffs.blockedDocumentJob,
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
      times.maintenanceNowMs,
    )).changes;

    // Removed rows are deletion receipts, not owned media: the filesystem
    // deletion completed before a row can enter `removed`. Keep a bounded
    // recent tail for diagnostics while preventing repeated download/remove
    // cycles from growing SQLite without limit. Active, retryable, corrupt,
    // and completed manifests are never compacted here.
    changedRows += (await database.runAsync(
      `DELETE FROM my_photos_downloads
        WHERE rowid IN (
          SELECT rowid
            FROM (
              SELECT rowid,
                     ROW_NUMBER() OVER (
                       PARTITION BY trip_id, passenger_id
                       ORDER BY updated_at DESC, id DESC
                     ) AS retention_rank
                FROM my_photos_downloads
               WHERE account_namespace = ? AND state = 'removed'
            ) ranked
           WHERE retention_rank > ${MY_PHOTOS_METADATA_RETENTION_POLICY.maximumRemovedDownloadsPerPassengerTrip}
        )`,
      namespace,
    )).changes;

    // Delete only already-terminal batch shells with no remaining child job.
    // Foreign-key ownership and all resumable batch checkpoints are retained.
    changedRows += (await database.runAsync(
      `DELETE FROM my_photos_download_batches
        WHERE rowid IN (
          SELECT rowid
            FROM (
              SELECT batch.rowid,
                     ROW_NUMBER() OVER (
                       PARTITION BY batch.trip_id, batch.passenger_id
                       ORDER BY batch.updated_at DESC, batch.id DESC
                     ) AS retention_rank
                FROM my_photos_download_batches batch
               WHERE batch.account_namespace = ?
                 AND batch.state IN ('completed', 'cancelled', 'failed')
                 AND NOT EXISTS (
                   SELECT 1
                     FROM my_photos_downloads download
                    WHERE download.batch_id = batch.id
                      AND download.account_namespace = batch.account_namespace
                      AND download.trip_id = batch.trip_id
                      AND download.passenger_id = batch.passenger_id
                 )
            ) ranked
           WHERE retention_rank > ${MY_PHOTOS_METADATA_RETENTION_POLICY.maximumOrphanedTerminalBatchesPerPassengerTrip}
        )`,
      namespace,
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
