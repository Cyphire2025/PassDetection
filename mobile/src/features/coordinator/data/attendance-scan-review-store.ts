import { z } from 'zod';

import { openAccountDatabase } from '@/core/storage/database';

import { ATTENDANCE_QUEUE_POLICY } from './attendance-policy';
import { coordinatorAttendanceAccountNamespace } from './attendance-queue-account';
import {
  discardAllRejectedAttendanceIssues,
  discardAttendanceScanIssue,
} from './attendance-discard-store';

const AttendanceEventIdSchema = z.string().uuid();
const AttendanceReviewPayloadSchema = z.object({ session_id: z.string().uuid() }).passthrough();

type AttendanceNeedsReviewRow = {
  idempotency_key: string;
  payload_json: string;
  attempt_count: number;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
  passenger_label: string | null;
  scan_reference: string | null;
  session_label: string | null;
};

export type AttendanceNeedsReviewItem = Readonly<{
  idempotencyKey: string;
  sessionId: string | null;
  reasonCode: string;
  createdAt: string;
  updatedAt: string;
  attemptCount: number;
  passengerLabel: string;
  safeReference: string;
  sessionLabel: string;
  retryState: 'ready_to_retry';
  lastAttemptAt: string;
}>;

export async function listAttendanceNeedsReview(
  tripId: string,
): Promise<AttendanceNeedsReviewItem[]> {
  const account = coordinatorAttendanceAccountNamespace();
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<AttendanceNeedsReviewRow>(
    `SELECT action.idempotency_key, action.payload_json, action.attempt_count,
            action.last_error_code, action.created_at, action.updated_at,
            context.passenger_label, context.session_label, context.scan_reference
       FROM pending_actions action
       LEFT JOIN attendance_scan_issue_context context
         ON context.idempotency_key = action.idempotency_key
        AND context.account_namespace = action.account_namespace
        AND context.trip_id = action.trip_id
      WHERE action.account_namespace = ? AND action.trip_id = ?
        AND action.action_type = 'attendance.scan' AND action.state = 'needs_review'
      ORDER BY action.updated_at DESC, action.idempotency_key DESC
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
      passengerLabel: row.passenger_label ?? 'Passenger resolution unavailable',
      safeReference: row.scan_reference?.slice(0, 12).toUpperCase()
        ?? row.idempotency_key.slice(-12).toUpperCase(),
      sessionLabel: row.session_label ?? 'Activity unavailable',
      retryState: 'ready_to_retry',
      lastAttemptAt: row.updated_at,
    };
  });
}

export async function acknowledgeAttendanceNeedsReview(
  tripId: string,
  idempotencyKey: string,
): Promise<boolean> {
  const eventId = AttendanceEventIdSchema.parse(idempotencyKey);
  return discardAttendanceScanIssue(tripId, eventId, 'operator_discard');
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
  return discardAllRejectedAttendanceIssues(tripId);
}
