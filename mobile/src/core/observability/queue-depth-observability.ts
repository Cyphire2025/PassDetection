import type * as SQLite from 'expo-sqlite';

import { recordMobileMetric } from './mobile-observability';

type DurableQueueDepths = Readonly<{
  attendance_depth: number;
  attendance_needs_review_depth: number;
  attendance_oldest_created_at: string | null;
  document_depth: number;
}>;

const MAX_ATTENDANCE_PENDING_AGE_MS = 30 * 24 * 60 * 60 * 1_000;

function oldestPendingAgeMs(
  createdAt: string | null,
  depth: number,
  observedAtMs: number,
): number | null {
  if (depth === 0) return 0;
  if (!Number.isSafeInteger(depth) || depth < 0 || typeof createdAt !== 'string') return null;
  const createdAtMs = Date.parse(createdAt);
  if (!Number.isFinite(createdAtMs) || createdAtMs > observedAtMs) return null;
  return Math.min(observedAtMs - createdAtMs, MAX_ATTENDANCE_PENDING_AGE_MS);
}

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
         (SELECT MIN(created_at) FROM pending_actions
           WHERE account_namespace = ? AND trip_id = ?
             AND action_type = 'attendance.scan'
             AND state IN ('pending', 'sending', 'retryable')) AS attendance_oldest_created_at,
         (SELECT COUNT(*) FROM pending_actions
           WHERE account_namespace = ? AND trip_id = ?
             AND action_type = 'attendance.scan'
             AND state = 'needs_review') AS attendance_needs_review_depth,
         (SELECT COUNT(*) FROM offline_document_jobs
           WHERE account_namespace = ? AND trip_id = ?
             AND state IN ('pending', 'retryable')) AS document_depth`,
      namespace,
      tripId,
      namespace,
      tripId,
      namespace,
      tripId,
      namespace,
      tripId,
    );
    if (!depths) return;
    recordMobileMetric('queue_depth', depths.attendance_depth, { queue: 'attendance' });
    const oldestAge = oldestPendingAgeMs(
      depths.attendance_oldest_created_at,
      depths.attendance_depth,
      Date.now(),
    );
    if (oldestAge !== null) {
      recordMobileMetric('attendance_oldest_pending_age', oldestAge, { queue: 'attendance' });
    }
    recordMobileMetric('attendance_needs_review_depth', depths.attendance_needs_review_depth, {
      queue: 'attendance',
    });
    recordMobileMetric('queue_depth', depths.document_depth, { queue: 'documents' });
  } catch {
    // Telemetry is intentionally fail-open; durable queue processing owns correctness.
  }
}
