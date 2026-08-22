import { z } from 'zod';

import { recordExplicitAttendanceDiscard } from '@/core/observability/attendance-observability';
import { openAccountDatabase } from '@/core/storage/database';

import { ATTENDANCE_QUEUE_POLICY } from './attendance-policy';
import { coordinatorAttendanceAccountNamespace } from './attendance-queue-account';

const AttendanceEventIdSchema = z.string().uuid();
const AttendanceReviewPayloadSchema = z.object({ session_id: z.string().uuid() }).passthrough();

type AttendanceNeedsReviewRow = {
  idempotency_key: string;
  payload_json: string;
  attempt_count: number;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type AttendanceNeedsReviewItem = Readonly<{
  idempotencyKey: string;
  sessionId: string | null;
  reasonCode: string;
  createdAt: string;
  updatedAt: string;
  attemptCount: number;
}>;

export async function listAttendanceNeedsReview(
  tripId: string,
): Promise<AttendanceNeedsReviewItem[]> {
  const account = coordinatorAttendanceAccountNamespace();
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<AttendanceNeedsReviewRow>(
    `SELECT idempotency_key, payload_json, attempt_count, last_error_code,
            created_at, updated_at
       FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state = 'needs_review'
      ORDER BY updated_at DESC, idempotency_key DESC
      LIMIT ${ATTENDANCE_QUEUE_POLICY.maxRejectedPerTrip}`,
    account,
    tripId,
  );
  return rows.map((row) => {
    let payload: unknown;
    try {
      payload = JSON.parse(row.payload_json) as unknown;
    } catch {
      payload = null;
    }
    const parsed = AttendanceReviewPayloadSchema.safeParse(payload);
    return {
      idempotencyKey: row.idempotency_key,
      sessionId: parsed.success ? parsed.data.session_id : null,
      reasonCode: row.last_error_code ?? 'REFRESH_REQUIRED',
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      attemptCount: row.attempt_count,
    };
  });
}

export async function acknowledgeAttendanceNeedsReview(
  tripId: string,
  idempotencyKey: string,
): Promise<boolean> {
  const account = coordinatorAttendanceAccountNamespace();
  const eventId = AttendanceEventIdSchema.parse(idempotencyKey);
  const database = await openAccountDatabase(account);
  const result = await database.runAsync(
    `DELETE FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND idempotency_key = ? AND state = 'needs_review'`,
    account,
    tripId,
    eventId,
  );
  recordExplicitAttendanceDiscard(result.changes);
  return result.changes === 1;
}

export async function markAttendanceNeedsReviewRetryable(
  tripId: string,
  idempotencyKey: string,
): Promise<boolean> {
  const account = coordinatorAttendanceAccountNamespace();
  const eventId = AttendanceEventIdSchema.parse(idempotencyKey);
  const database = await openAccountDatabase(account);
  const result = await database.runAsync(
    `UPDATE pending_actions
        SET state = 'retryable', next_attempt_at = NULL,
            last_error_code = 'MANUAL_REVIEW_RETRY', updated_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND idempotency_key = ? AND state = 'needs_review'`,
    new Date().toISOString(),
    account,
    tripId,
    eventId,
  );
  return result.changes === 1;
}

export async function acknowledgeRejectedAttendance(tripId: string): Promise<number> {
  const account = coordinatorAttendanceAccountNamespace();
  const database = await openAccountDatabase(account);
  const result = await database.runAsync(
    `DELETE FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state = 'rejected'`,
    account,
    tripId,
  );
  recordExplicitAttendanceDiscard(result.changes);
  return result.changes;
}
