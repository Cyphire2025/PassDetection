import * as Crypto from 'expo-crypto';
import { z } from 'zod';

import { apiRequest, ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { getInstallationId } from '@/core/storage/secure-store';

const DISCARD_BATCH_LIMIT = 100;
const SYNCHRONIZED_RETENTION_MS = 30 * 24 * 60 * 60_000;
const SHA256_HEX = /^[0-9a-f]{64}$/;

const AttendanceDiscardBatchResponseSchema = z.object({
  items: z.array(z.object({
    discard_event_id: z.string().uuid(),
    received_at: z.string().datetime({ offset: true }).nullable(),
    reason_code: z.string().max(100).nullable().optional(),
    status: z.enum(['accepted', 'already_applied', 'rejected']),
  }).strict()).max(DISCARD_BATCH_LIMIT),
}).strict();

export type AttendanceDiscardReason =
  | 'operator_discard'
  | 'wrong_group'
  | 'expired_authorization'
  | 'activity_closed'
  | 'duplicate'
  | 'server_rejected'
  | 'corrupted_entry'
  | 'other';

type DiscardSourceRow = Readonly<{
  captured_at: string;
  idempotency_key: string;
  passenger_id: string;
  scan_reference: string;
  session_id: string;
  state: 'pending' | 'sending' | 'retryable' | 'needs_review' | 'rejected';
  trip_id: string;
}>;

type AttendanceDiscardRow = Readonly<{
  account_namespace: string;
  attempt_count: number;
  captured_at: string | null;
  discard_event_id: string;
  discarded_at: string;
  installation_runtime_id: string;
  last_error_code: string | null;
  next_attempt_at: string | null;
  reason_category: AttendanceDiscardReason;
  scan_reference: string;
  session_id: string;
  state: 'pending' | 'sending' | 'retryable' | 'rejected' | 'synchronized';
  trip_id: string;
}>;

export type AttendanceDiscardAuditStatus = Readonly<{
  pending: number;
  rejected: number;
  synchronized: number;
}>;

const drainLanes = new Map<string, Promise<AttendanceDiscardAuditStatus>>();

function activeCoordinatorIdentity(): Readonly<{
  account: string;
  coordinatorUserId: string;
}> {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  return {
    account: principalAccountNamespace(principal),
    coordinatorUserId: principal.id,
  };
}

function retryDelayMs(attempt: number, error?: unknown): number {
  const cappedAttempt = Math.min(Math.max(0, attempt), 8);
  const localDelay = Math.min(5 * 60_000, 1_000 * 2 ** cappedAttempt);
  if (
    error instanceof ApiError
    && error.retryAfterSeconds !== null
    && Number.isSafeInteger(error.retryAfterSeconds)
    && error.retryAfterSeconds >= 0
  ) {
    return Math.max(localDelay, error.retryAfterSeconds * 1_000);
  }
  return localDelay;
}

function isTerminalDiscardDeliveryError(error: unknown): boolean {
  return error instanceof ApiError
    && error.status >= 400
    && error.status < 500
    && ![401, 403, 408, 425, 429].includes(error.status);
}

async function createTombstoneForSource(
  transaction: Awaited<ReturnType<typeof openAccountDatabase>>,
  input: Readonly<{
    account: string;
    coordinatorUserId: string;
    installationId: string;
    reason: AttendanceDiscardReason;
    row: DiscardSourceRow;
    tripId: string;
  }>,
): Promise<boolean> {
  if (!SHA256_HEX.test(input.row.scan_reference)) {
    throw new Error('The scan issue reference is unavailable for safe discard evidence.');
  }
  const now = new Date().toISOString();
  const discardEventId = Crypto.randomUUID();
  const inserted = await transaction.runAsync(
    `INSERT OR IGNORE INTO attendance_discard_tombstones
      (discard_event_id, source_idempotency_key, account_namespace, trip_id,
       session_id, coordinator_user_id, installation_runtime_id, scan_reference,
       reason_category, captured_at, discarded_at, state, attempt_count,
       next_attempt_at, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)`,
    discardEventId,
    input.row.idempotency_key,
    input.account,
    input.tripId,
    input.row.session_id,
    input.coordinatorUserId,
    input.installationId,
    input.row.scan_reference,
    input.reason,
    input.row.captured_at,
    now,
    now,
    now,
    now,
  );
  const persisted = await transaction.getFirstAsync<Readonly<{
    account_namespace: string;
    scan_reference: string;
    session_id: string;
    trip_id: string;
  }>>(
    `SELECT account_namespace, trip_id, session_id, scan_reference
       FROM attendance_discard_tombstones
      WHERE source_idempotency_key = ?
      LIMIT 1`,
    input.row.idempotency_key,
  );
  if (
    !persisted
    || persisted.account_namespace !== input.account
    || persisted.trip_id !== input.tripId
    || persisted.session_id !== input.row.session_id
    || persisted.scan_reference !== input.row.scan_reference
  ) {
    throw new Error('The attendance discard idempotency boundary conflicted.');
  }
  await transaction.runAsync(
    `DELETE FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND idempotency_key = ?`,
    input.account,
    input.tripId,
    input.row.idempotency_key,
  );
  return inserted.changes === 1;
}

async function sourceRows(
  transaction: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId?: string,
  idempotencyKey?: string,
): Promise<DiscardSourceRow[]> {
  return transaction.getAllAsync<DiscardSourceRow>(
    `SELECT action.idempotency_key, action.state, action.trip_id, context.session_id,
            context.passenger_id, context.scan_reference, context.captured_at
       FROM pending_actions action
       JOIN attendance_scan_issue_context context
         ON context.idempotency_key = action.idempotency_key
        AND context.account_namespace = action.account_namespace
        AND context.trip_id = action.trip_id
      WHERE action.account_namespace = ? AND action.action_type = 'attendance.scan'
        AND action.state IN ('pending', 'sending', 'retryable', 'needs_review', 'rejected')
        AND (? IS NULL OR action.trip_id = ?)
        AND (? IS NULL OR action.idempotency_key = ?)
      ORDER BY action.created_at, action.idempotency_key`,
    account,
    tripId ?? null,
    tripId ?? null,
    idempotencyKey ?? null,
    idempotencyKey ?? null,
  );
}

/** Atomically persists privacy-safe discard evidence before removing one issue. */
export async function discardAttendanceScanIssue(
  tripId: string,
  idempotencyKey: string,
  reason: AttendanceDiscardReason = 'operator_discard',
): Promise<boolean> {
  const identity = activeCoordinatorIdentity();
  const installationId = await getInstallationId();
  const database = await openAccountDatabase(identity.account);
  let inserted = false;
  await withAccountTransaction(database, async (transaction) => {
    const rows = await sourceRows(
      transaction,
      identity.account,
      tripId,
      idempotencyKey,
    );
    const row = rows[0];
    if (!row) {
      const existing = await transaction.getFirstAsync<Readonly<{
        account_namespace: string;
        trip_id: string;
      }>>(
        `SELECT account_namespace, trip_id
           FROM attendance_discard_tombstones
          WHERE source_idempotency_key = ?
          LIMIT 1`,
        idempotencyKey,
      );
      if (
        existing?.account_namespace === identity.account
        && existing.trip_id === tripId
      ) {
        inserted = false;
        return;
      }
      throw new Error('The scan issue lacks attributable discard evidence and was preserved.');
    }
    inserted = await createTombstoneForSource(transaction, {
      ...identity,
      installationId,
      reason,
      row,
      tripId,
    });
  });
  return inserted;
}

/**
 * Converts every attributable attendance record before a deliberate sign-out.
 * Legacy rows without context are intentionally left encrypted in place.
 */
export async function preserveAttendanceDiscardsForSignOut(
  account: string,
  coordinatorUserId: string,
  installationId: string,
): Promise<number> {
  const database = await openAccountDatabase(account);
  let created = 0;
  await withAccountTransaction(database, async (transaction) => {
    const rows = await sourceRows(transaction, account);
    for (const row of rows) {
      const reason: AttendanceDiscardReason = row.state === 'rejected'
        ? 'server_rejected'
        : 'operator_discard';
      if (await createTombstoneForSource(transaction, {
        account,
        coordinatorUserId,
        installationId,
        reason,
        row,
        tripId: row.trip_id,
      })) created += 1;
    }
  });
  return created;
}

export async function discardAllRejectedAttendanceIssues(tripId: string): Promise<number> {
  const identity = activeCoordinatorIdentity();
  const installationId = await getInstallationId();
  const database = await openAccountDatabase(identity.account);
  let created = 0;
  await withAccountTransaction(database, async (transaction) => {
    const rows = (await sourceRows(transaction, identity.account, tripId))
      .filter((row) => row.state === 'rejected');
    for (const row of rows) {
      if (await createTombstoneForSource(transaction, {
        ...identity,
        installationId,
        reason: 'server_rejected',
        row,
        tripId,
      })) created += 1;
    }
  });
  return created;
}

async function claimDiscardBatch(
  account: string,
  tripId?: string,
): Promise<AttendanceDiscardRow[]> {
  const database = await openAccountDatabase(account);
  let claimed: AttendanceDiscardRow[] = [];
  await withAccountTransaction(database, async (transaction) => {
    const now = new Date().toISOString();
    const first = await transaction.getFirstAsync<Readonly<{
      session_id: string;
      trip_id: string;
    }>>(
      `SELECT trip_id, session_id
         FROM attendance_discard_tombstones
        WHERE account_namespace = ? AND state IN ('pending', 'retryable')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
          AND (? IS NULL OR trip_id = ?)
        ORDER BY COALESCE(next_attempt_at, discarded_at), discard_event_id
        LIMIT 1`,
      account,
      now,
      tripId ?? null,
      tripId ?? null,
    );
    if (!first) return;
    const rows = await transaction.getAllAsync<AttendanceDiscardRow>(
      `SELECT account_namespace, attempt_count, captured_at, discard_event_id,
              discarded_at, installation_runtime_id, last_error_code,
              next_attempt_at, reason_category, scan_reference, session_id,
              state, trip_id
         FROM attendance_discard_tombstones
        WHERE account_namespace = ? AND trip_id = ? AND session_id = ?
          AND state IN ('pending', 'retryable')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY COALESCE(next_attempt_at, discarded_at), discard_event_id
        LIMIT ${DISCARD_BATCH_LIMIT}`,
      account,
      first.trip_id,
      first.session_id,
      now,
    );
    if (rows.length === 0) return;
    for (const row of rows) {
      await transaction.runAsync(
        `UPDATE attendance_discard_tombstones
            SET state = 'sending', last_attempt_at = ?, updated_at = ?
          WHERE account_namespace = ? AND discard_event_id = ?
            AND state IN ('pending', 'retryable')`,
        now,
        now,
        account,
        row.discard_event_id,
      );
    }
    claimed = rows;
  });
  return claimed;
}

async function reconcileDiscardBatch(
  account: string,
  rows: readonly AttendanceDiscardRow[],
  response: z.infer<typeof AttendanceDiscardBatchResponseSchema>,
): Promise<void> {
  const results = new Map(response.items.map((item) => [item.discard_event_id, item]));
  if (results.size !== rows.length || rows.some((row) => !results.has(row.discard_event_id))) {
    throw new Error('The discard synchronization response was incomplete.');
  }
  const database = await openAccountDatabase(account);
  await withAccountTransaction(database, async (transaction) => {
    for (const row of rows) {
      const result = results.get(row.discard_event_id)!;
      if (result.status === 'rejected') {
        const updatedAt = new Date().toISOString();
        await transaction.runAsync(
          `UPDATE attendance_discard_tombstones
              SET state = 'rejected', next_attempt_at = NULL,
                  last_error_code = ?, updated_at = ?
            WHERE account_namespace = ? AND discard_event_id = ? AND state = 'sending'`,
          result.reason_code ?? 'DISCARD_REJECTED',
          updatedAt,
          account,
          row.discard_event_id,
        );
        continue;
      }
      if (result.received_at === null) {
        throw new Error('The discard synchronization receipt was incomplete.');
      }
      await transaction.runAsync(
        `UPDATE attendance_discard_tombstones
            SET state = 'synchronized', next_attempt_at = NULL,
                last_error_code = NULL, synchronized_at = ?, updated_at = ?
          WHERE account_namespace = ? AND discard_event_id = ? AND state = 'sending'`,
        result.received_at,
        result.received_at,
        account,
        row.discard_event_id,
      );
    }
  });
}

async function releaseDiscardBatch(
  account: string,
  rows: readonly AttendanceDiscardRow[],
  error: unknown,
): Promise<void> {
  const terminal = isTerminalDiscardDeliveryError(error);
  const database = await openAccountDatabase(account);
  await withAccountTransaction(database, async (transaction) => {
    const updatedAt = new Date().toISOString();
    for (const row of rows) {
      const attemptCount = row.attempt_count + 1;
      await transaction.runAsync(
        `UPDATE attendance_discard_tombstones
            SET state = ?, attempt_count = ?, next_attempt_at = ?,
                last_error_code = ?, updated_at = ?
          WHERE account_namespace = ? AND discard_event_id = ? AND state = 'sending'`,
        terminal ? 'rejected' : 'retryable',
        attemptCount,
        terminal ? null : new Date(Date.now() + retryDelayMs(attemptCount, error)).toISOString(),
        error instanceof ApiError ? error.code : 'DISCARD_DELIVERY_FAILED',
        updatedAt,
        account,
        row.discard_event_id,
      );
    }
  });
}

async function attendanceDiscardStatusForAccount(
  account: string,
  tripId?: string,
  sessionId?: string,
): Promise<AttendanceDiscardAuditStatus> {
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<Readonly<{ count: number; state: string }>>(
    `SELECT state, COUNT(*) AS count
       FROM attendance_discard_tombstones
      WHERE account_namespace = ?
        AND (? IS NULL OR trip_id = ?)
        AND (? IS NULL OR session_id = ?)
      GROUP BY state`,
    account,
    tripId ?? null,
    tripId ?? null,
    sessionId ?? null,
    sessionId ?? null,
  );
  let pending = 0;
  let rejected = 0;
  let synchronized = 0;
  for (const row of rows) {
    if (row.state === 'synchronized') synchronized += row.count;
    else if (row.state === 'rejected') rejected += row.count;
    else pending += row.count;
  }
  return { pending, rejected, synchronized };
}

export async function attendanceDiscardAuditStatus(
  tripId?: string,
  sessionId?: string,
): Promise<AttendanceDiscardAuditStatus> {
  const { account } = activeCoordinatorIdentity();
  return attendanceDiscardStatusForAccount(account, tripId, sessionId);
}

async function performDiscardDrain(
  account: string,
  tripId?: string,
): Promise<AttendanceDiscardAuditStatus> {
  for (;;) {
    const rows = await claimDiscardBatch(account, tripId);
    if (rows.length === 0) break;
    const groupId = rows[0]!.trip_id;
    const sessionId = rows[0]!.session_id;
    let response: z.infer<typeof AttendanceDiscardBatchResponseSchema>;
    try {
      response = await apiRequest(
        `/mobile/coordinator/groups/${groupId}/attendance/sessions/${sessionId}/discards`,
        {
          method: 'POST',
          schema: AttendanceDiscardBatchResponseSchema,
          body: {
            items: rows.map((row) => ({
              captured_at: row.captured_at,
              discard_event_id: row.discard_event_id,
              discarded_at: row.discarded_at,
              reason_category: row.reason_category,
              scan_reference: row.scan_reference,
            })),
          },
        },
      );
      await reconcileDiscardBatch(account, rows, response);
    } catch (error) {
      await releaseDiscardBatch(account, rows, error);
      if (!isTerminalDiscardDeliveryError(error)) break;
    }
  }
  const database = await openAccountDatabase(account);
  await database.runAsync(
    `DELETE FROM attendance_discard_tombstones
      WHERE account_namespace = ? AND state = 'synchronized'
        AND synchronized_at IS NOT NULL AND synchronized_at < ?`,
    account,
    new Date(Date.now() - SYNCHRONIZED_RETENTION_MS).toISOString(),
  );
  return attendanceDiscardStatusForAccount(account, tripId);
}

export function drainAttendanceDiscardTombstones(
  tripId?: string,
): Promise<AttendanceDiscardAuditStatus> {
  const { account } = activeCoordinatorIdentity();
  const key = `${account}:${tripId ?? '*'}`;
  const existing = drainLanes.get(key);
  if (existing) return existing;
  const request = performDiscardDrain(account, tripId).finally(() => {
    if (drainLanes.get(key) === request) drainLanes.delete(key);
  });
  drainLanes.set(key, request);
  return request;
}
