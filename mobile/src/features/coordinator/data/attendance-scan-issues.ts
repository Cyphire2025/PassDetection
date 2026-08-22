import { z } from 'zod';

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { openAccountDatabase } from '@/core/storage/database';

import { ATTENDANCE_QUEUE_POLICY } from './attendance-policy';

const TripIdSchema = z.string().uuid();

type RejectedAttendanceIssueRow = Readonly<{
  attempt_count: number;
  created_at: string;
  idempotency_key: string;
  last_error_code: string | null;
  updated_at: string;
}>;

export type RejectedAttendanceIssue = Readonly<{
  attemptCount: number;
  createdAt: string;
  idempotencyKey: string;
  reasonCode: string;
  updatedAt: string;
}>;

function coordinatorNamespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  return principalAccountNamespace(principal);
}

/**
 * Returns terminal issue metadata only. The v24 database trigger has already
 * replaced each rejected attendance payload with `{}`, and this query never
 * selects payload_json as a second privacy boundary.
 */
export async function listRejectedAttendanceIssues(
  tripId: string,
): Promise<RejectedAttendanceIssue[]> {
  const account = coordinatorNamespace();
  const scopedTripId = TripIdSchema.parse(tripId);
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<RejectedAttendanceIssueRow>(
    `SELECT idempotency_key, attempt_count, last_error_code, created_at, updated_at
       FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state = 'rejected'
      ORDER BY updated_at DESC, idempotency_key DESC
      LIMIT ${ATTENDANCE_QUEUE_POLICY.maxRejectedPerTrip}`,
    account,
    scopedTripId,
  );
  return rows.map((row) => ({
    attemptCount: row.attempt_count,
    createdAt: row.created_at,
    idempotencyKey: row.idempotency_key,
    reasonCode: row.last_error_code ?? 'NOT_ACCEPTED',
    updatedAt: row.updated_at,
  }));
}

export function attendanceIssueExplanation(reasonCode: string): string {
  const normalized = reasonCode.toUpperCase();
  if (normalized.includes('REFRESH') || normalized.includes('ROSTER')) {
    return 'The roster or activity changed. Synchronize, confirm the passenger, then retry.';
  }
  if (normalized.includes('SESSION') || normalized.includes('ACTIVITY')) {
    return 'The attendance activity changed or closed before the scan was confirmed.';
  }
  if (
    normalized.includes('QR')
    || normalized.includes('TOKEN')
    || normalized.includes('PASSENGER')
  ) {
    return 'The QR was invalid, expired, revoked, or outside this assigned group.';
  }
  if (normalized.includes('AUTH') || normalized.includes('ACCESS')) {
    return 'Authorization changed before the scan reached the server. Sign in online and review it.';
  }
  if (normalized.includes('CAPACITY') || normalized.includes('LIMIT')) {
    return 'The local or server attendance limit was reached. Synchronize before continuing.';
  }
  return 'The server could not confirm this saved scan. Review it before event closeout.';
}
