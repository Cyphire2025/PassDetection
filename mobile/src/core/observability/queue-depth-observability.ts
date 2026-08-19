import type * as SQLite from 'expo-sqlite';

import { recordMobileMetric } from './mobile-observability';

type DurableQueueDepths = Readonly<{
  attendance_depth: number;
  document_depth: number;
}>;

/**
 * Emits only aggregate, low-cardinality queue gauges. Observability must never
 * become part of synchronization correctness, so database/telemetry failures
 * are deliberately contained here.
 */
export async function recordTripDurableQueueDepths(
  database: SQLite.SQLiteDatabase,
  namespace: string,
  tripId: string,
): Promise<void> {
  try {
    const depths = await database.getFirstAsync<DurableQueueDepths>(
      `SELECT
         (SELECT COUNT(*) FROM pending_actions
           WHERE account_namespace = ? AND trip_id = ?
             AND action_type = 'attendance.scan'
             AND state IN ('pending', 'sending', 'retryable')) AS attendance_depth,
         (SELECT COUNT(*) FROM offline_document_jobs
           WHERE account_namespace = ? AND trip_id = ?
             AND state IN ('pending', 'retryable')) AS document_depth`,
      namespace,
      tripId,
      namespace,
      tripId,
    );
    if (!depths) return;
    recordMobileMetric('queue_depth', depths.attendance_depth, { queue: 'attendance' });
    recordMobileMetric('queue_depth', depths.document_depth, { queue: 'documents' });
  } catch {
    // Telemetry is intentionally fail-open; durable queue processing owns correctness.
  }
}
