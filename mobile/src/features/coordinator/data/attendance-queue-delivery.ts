import { z } from 'zod';

import { apiRequest, ApiError } from '@/core/api/client';
import {
  recordAttendanceAcknowledgement,
  recordAttendanceDeliveryBatchSize,
  recordAttendanceDeliveryFailure,
  recordAttendanceQueueToConfirmation,
  recordAttendanceRefreshRecovery,
  recordAttendanceRetryOutcome,
  recordAttendanceServerConfirmation,
  recordAttendanceTerminalRejection,
  type AttendanceDeliveryFailureCategory,
} from '@/core/observability/attendance-observability';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import { AttendanceBatchResponseSchema } from '../api/coordinator-contracts';
import { refreshAttendanceSessions } from './attendance-sessions';

const REFRESH_PENDING_PREFIX = 'REFRESH_PENDING:';

export type PendingAttendanceRow = {
  created_at: string;
  idempotency_key: string;
  dedupe_key: string;
  payload_json: string;
  attempt_count: number;
  refresh_attempt_count: number;
  last_error_code: string | null;
};

export type PreparedAttendanceRow = PendingAttendanceRow & {
  payload: {
    session_id: string;
    signed_qr: string;
    scanned_at: string;
    source: 'qr';
  };
};

type RefreshRequiredAttendanceRow = PreparedAttendanceRow & {
  refreshReasonCode: string;
};

type MutableAttendanceDrainResult = {
  settledBySession: Record<string, number>;
  confirmedBySession: Record<string, number>;
  newlyAcceptedBySession: Record<string, number>;
  rejectedBySession: Record<string, number>;
};

type AttendanceReconciliation = {
  result: MutableAttendanceDrainResult;
  refreshRequiredRows: RefreshRequiredAttendanceRow[];
};

export type AttendanceDeliveryResult = Readonly<{
  result: MutableAttendanceDrainResult;
  stopDraining: boolean;
}>;

function emptyDrainResult(): MutableAttendanceDrainResult {
  return {
    settledBySession: {},
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: {},
  };
}

function recordSettled(target: Record<string, number>, sessionId: string): void {
  target[sessionId] = (target[sessionId] ?? 0) + 1;
}

function recordFinalOutcome(
  target: MutableAttendanceDrainResult,
  sessionId: string,
  outcome: 'accepted' | 'already_applied' | 'rejected',
): void {
  recordSettled(target.settledBySession, sessionId);
  if (outcome === 'accepted') {
    recordSettled(target.confirmedBySession, sessionId);
    recordSettled(target.newlyAcceptedBySession, sessionId);
  } else if (outcome === 'already_applied') {
    recordSettled(target.confirmedBySession, sessionId);
  } else {
    recordSettled(target.rejectedBySession, sessionId);
  }
}

function mergeDrainResult(
  target: MutableAttendanceDrainResult,
  source: MutableAttendanceDrainResult,
): void {
  const fields = [
    'settledBySession',
    'confirmedBySession',
    'newlyAcceptedBySession',
    'rejectedBySession',
  ] as const;
  for (const field of fields) {
    for (const [sessionId, count] of Object.entries(source[field])) {
      target[field][sessionId] = (target[field][sessionId] ?? 0) + count;
    }
  }
}

function retryDelay(attempt: number): number {
  const capped = Math.min(attempt, 8);
  const base = Math.min(5 * 60_000, 1_000 * 2 ** capped);
  return Math.round(base * (0.75 + Math.random() * 0.5));
}

function retryDelayForError(error: unknown, attempt: number): number {
  const localDelay = retryDelay(attempt);
  if (
    error instanceof ApiError
    && error.retryAfterSeconds !== null
    && Number.isSafeInteger(error.retryAfterSeconds)
    && error.retryAfterSeconds >= 0
  ) {
    return Math.max(error.retryAfterSeconds * 1_000, localDelay);
  }
  return localDelay;
}

function deliveryFailureOutcome(error: unknown): 'failure' | 'timeout' | 'offline' {
  if (
    typeof error === 'object'
    && error !== null
    && 'name' in error
    && error.name === 'TimeoutError'
  ) return 'timeout';
  return error instanceof TypeError ? 'offline' : 'failure';
}

export function attendanceDeliveryFailureCategory(
  error: unknown,
): AttendanceDeliveryFailureCategory {
  if (error instanceof ApiError && error.status === 429) return 'rate_limited';
  if (error instanceof ApiError && error.status >= 500 && error.status <= 599) {
    return 'server_error';
  }
  if (
    (error instanceof ApiError && error.status === 408)
    || (
      typeof error === 'object'
      && error !== null
      && 'name' in error
      && error.name === 'TimeoutError'
    )
  ) return 'timeout';
  if (error instanceof TypeError) return 'network';
  return 'other';
}

function totalOutcomes(values: Readonly<Record<string, number>>): number {
  return Object.values(values).reduce((total, count) => total + count, 0);
}

export function isAttendanceRefreshRecoveryPending(row: PendingAttendanceRow): boolean {
  return row.refresh_attempt_count === 0
    && row.last_error_code?.startsWith(REFRESH_PENDING_PREFIX) === true;
}

function refreshPendingErrorCode(reasonCode: string): string {
  return `${REFRESH_PENDING_PREFIX}${reasonCode}`;
}

function refreshReasonFromPendingRow(row: PendingAttendanceRow): string {
  if (!isAttendanceRefreshRecoveryPending(row)) return 'REFRESH_REQUIRED';
  return row.last_error_code?.slice(REFRESH_PENDING_PREFIX.length) || 'REFRESH_REQUIRED';
}

async function reconcileAttendanceBatch(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  rows: PreparedAttendanceRow[],
  response: z.infer<typeof AttendanceBatchResponseSchema>,
  allowRefreshRecovery: boolean,
): Promise<AttendanceReconciliation> {
  const resultsByEvent = new Map<string, (typeof response.results)[number]>();
  const duplicateResults = new Set<string>();
  for (const result of response.results) {
    if (resultsByEvent.has(result.client_event_id)) {
      duplicateResults.add(result.client_event_id);
    } else {
      resultsByEvent.set(result.client_event_id, result);
    }
  }

  const reconciled = emptyDrainResult();
  const refreshRequiredRows: RefreshRequiredAttendanceRow[] = [];
  const confirmedRows: Readonly<{
    durationMs: number | null;
    status: 'accepted' | 'already_applied';
  }>[] = [];
  const terminalReasons: (string | null)[] = [];
  await withAccountTransaction(database, async (transaction) => {
    const reconciledAt = new Date().toISOString();
    const reconciledAtMs = Date.parse(reconciledAt);
    for (const row of rows) {
      const result = duplicateResults.has(row.idempotency_key)
        ? undefined
        : resultsByEvent.get(row.idempotency_key);
      if (result?.status === 'accepted' || result?.status === 'already_applied') {
        recordFinalOutcome(reconciled, row.payload.session_id, result.status);
        await transaction.runAsync(
          `INSERT OR IGNORE INTO attendance_scan_receipts
            (account_namespace, trip_id, session_id, dedupe_key, client_event_id, server_status, accepted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)`,
          account,
          tripId,
          row.payload.session_id,
          row.dedupe_key,
          row.idempotency_key,
          result.status,
          reconciledAt,
        );
        await transaction.runAsync(
          `DELETE FROM pending_actions
            WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
          row.idempotency_key,
          account,
        );
        const createdAtMs = Date.parse(row.created_at);
        confirmedRows.push({
          durationMs: Number.isFinite(createdAtMs)
            && Number.isFinite(reconciledAtMs)
            && reconciledAtMs >= createdAtMs
            ? reconciledAtMs - createdAtMs
            : null,
          status: result.status,
        });
        continue;
      }

      if (result?.status === 'refresh_required') {
        const reasonCode = result.reason_code ?? 'REFRESH_REQUIRED';
        if (allowRefreshRecovery && row.refresh_attempt_count === 0) {
          refreshRequiredRows.push({ ...row, refreshReasonCode: reasonCode });
          continue;
        }
        recordFinalOutcome(reconciled, row.payload.session_id, 'rejected');
        await transaction.runAsync(
          `UPDATE pending_actions
              SET state = 'needs_review', next_attempt_at = NULL,
                  last_error_code = ?, updated_at = ?
            WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
          reasonCode,
          reconciledAt,
          row.idempotency_key,
          account,
        );
        terminalReasons.push(reasonCode);
        continue;
      }

      if (result?.status === 'rejected') {
        recordFinalOutcome(reconciled, row.payload.session_id, 'rejected');
        await transaction.runAsync(
          `UPDATE pending_actions
              SET state = 'rejected', next_attempt_at = NULL,
                  last_error_code = ?, updated_at = ?
            WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
          result.reason_code ?? result.status,
          reconciledAt,
          row.idempotency_key,
          account,
        );
        terminalReasons.push(result.reason_code);
        continue;
      }

      const protocolError = duplicateResults.has(row.idempotency_key)
        ? 'DUPLICATE_SERVER_RESULT'
        : 'MISSING_SERVER_RESULT';
      await transaction.runAsync(
        `UPDATE pending_actions
            SET state = 'retryable', next_attempt_at = ?, last_error_code = ?, updated_at = ?
          WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
        new Date(Date.now() + retryDelay(row.attempt_count + 1)).toISOString(),
        protocolError,
        reconciledAt,
        row.idempotency_key,
        account,
      );
    }
  });
  const acceptedCount = confirmedRows.filter((row) => row.status === 'accepted').length;
  const alreadyAppliedCount = confirmedRows.length - acceptedCount;
  recordAttendanceServerConfirmation('accepted', acceptedCount);
  recordAttendanceServerConfirmation('already_applied', alreadyAppliedCount);
  for (const row of confirmedRows) {
    if (row.durationMs !== null) recordAttendanceQueueToConfirmation(row.durationMs);
  }
  for (const reason of terminalReasons) recordAttendanceTerminalRejection(reason, 1);
  return { result: reconciled, refreshRequiredRows };
}

async function settleFailedBatch(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  rows: PreparedAttendanceRow[],
  error: unknown,
): Promise<boolean> {
  const permanent = error instanceof ApiError
    && error.status >= 400
    && error.status < 500
    && error.status !== 408
    && error.status !== 429;
  await withAccountTransaction(database, async (transaction) => {
    const updatedAt = new Date().toISOString();
    for (const row of rows) {
      await transaction.runAsync(
        `UPDATE pending_actions
            SET state = ?, next_attempt_at = ?, last_error_code = ?, updated_at = ?
          WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
        permanent ? 'rejected' : 'retryable',
        permanent
          ? null
          : new Date(
              Date.now() + retryDelayForError(error, row.attempt_count + 1),
            ).toISOString(),
        error instanceof ApiError ? error.code : 'NETWORK_ERROR',
        updatedAt,
        row.idempotency_key,
        account,
      );
    }
  });
  if (permanent) {
    const categorySource = error instanceof ApiError && (error.status === 401 || error.status === 403)
      ? 'AUTHORIZATION_FAILURE'
      : 'CLIENT_REQUEST_REJECTED';
    recordAttendanceTerminalRejection(categorySource, rows.length);
  }
  return permanent;
}

async function deferRefreshRecovery(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  rows: RefreshRequiredAttendanceRow[],
): Promise<void> {
  await withAccountTransaction(database, async (transaction) => {
    const updatedAt = new Date().toISOString();
    for (const row of rows) {
      await transaction.runAsync(
        `UPDATE pending_actions
            SET state = 'retryable', next_attempt_at = ?,
                last_error_code = ?, updated_at = ?
          WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
        new Date(Date.now() + retryDelay(row.attempt_count + 1)).toISOString(),
        refreshPendingErrorCode(row.refreshReasonCode),
        updatedAt,
        row.idempotency_key,
        account,
      );
    }
  });
}

async function prepareRowsAfterAuthoritativeRefresh(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  rows: RefreshRequiredAttendanceRow[],
  refreshedSessionIds: ReadonlySet<string>,
): Promise<Readonly<{
  retryRows: PreparedAttendanceRow[];
  result: MutableAttendanceDrainResult;
}>> {
  const result = emptyDrainResult();
  const retryRows: PreparedAttendanceRow[] = [];
  let unavailableSessionCount = 0;
  await withAccountTransaction(database, async (transaction) => {
    const updatedAt = new Date().toISOString();
    for (const row of rows) {
      if (!refreshedSessionIds.has(row.payload.session_id)) {
        unavailableSessionCount += 1;
        recordFinalOutcome(result, row.payload.session_id, 'rejected');
        await transaction.runAsync(
          `UPDATE pending_actions
              SET state = 'needs_review', refresh_attempt_count = 1,
                  next_attempt_at = NULL, last_error_code = ?, updated_at = ?
            WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
          row.refreshReasonCode,
          updatedAt,
          row.idempotency_key,
          account,
        );
        continue;
      }

      const updated = await transaction.runAsync(
        `UPDATE pending_actions
            SET refresh_attempt_count = 1, attempt_count = attempt_count + 1, updated_at = ?
          WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'
            AND refresh_attempt_count = 0`,
        updatedAt,
        row.idempotency_key,
        account,
      );
      if (updated.changes !== 1) {
        throw new Error('The attendance refresh recovery could not be claimed atomically.');
      }
      retryRows.push({
        ...row,
        attempt_count: row.attempt_count + 1,
        refresh_attempt_count: 1,
      });
    }
  });
  recordAttendanceTerminalRejection('ATTENDANCE_SESSION_UNAVAILABLE', unavailableSessionCount);
  return { retryRows, result };
}

async function sendAttendanceBatch(
  tripId: string,
  rows: PreparedAttendanceRow[],
): Promise<z.infer<typeof AttendanceBatchResponseSchema>> {
  const startedAtMs = performance.now();
  const retryRowCount = rows.filter((row) => row.attempt_count > 0).length;
  let outcome: 'success' | 'failure' | 'timeout' | 'offline' = 'failure';
  try {
    const response = await apiRequest(`/mobile/coordinator/groups/${tripId}/attendance/actions`, {
      method: 'POST',
      schema: AttendanceBatchResponseSchema,
      body: {
        actions: rows.map((row) => ({
          client_event_id: row.idempotency_key,
          ...row.payload,
        })),
      },
    });
    outcome = 'success';
    return response;
  } catch (error) {
    outcome = deliveryFailureOutcome(error);
    recordAttendanceDeliveryFailure(attendanceDeliveryFailureCategory(error));
    throw error;
  } finally {
    recordAttendanceAcknowledgement(performance.now() - startedAtMs, outcome);
    recordAttendanceDeliveryBatchSize(rows.length, outcome);
    recordAttendanceRetryOutcome(retryRowCount, outcome);
  }
}

async function recoverRefreshRequiredRows(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  rows: RefreshRequiredAttendanceRow[],
): Promise<AttendanceDeliveryResult> {
  let outcome: 'success' | 'partial' | 'failure' | 'timeout' | 'offline' = 'failure';
  try {
    let refreshed: Awaited<ReturnType<typeof refreshAttendanceSessions>>;
    try {
      refreshed = await refreshAttendanceSessions(tripId);
    } catch (error) {
      outcome = deliveryFailureOutcome(error);
      await deferRefreshRecovery(database, account, rows);
      return { result: emptyDrainResult(), stopDraining: true };
    }
    if (refreshed.offline) {
      outcome = 'offline';
      await deferRefreshRecovery(database, account, rows);
      return { result: emptyDrainResult(), stopDraining: true };
    }

    const prepared = await prepareRowsAfterAuthoritativeRefresh(
      database,
      account,
      rows,
      new Set(refreshed.items.map((session) => session.id)),
    );
    if (prepared.retryRows.length === 0) {
      return { result: prepared.result, stopDraining: false };
    }

    let response: z.infer<typeof AttendanceBatchResponseSchema>;
    try {
      response = await sendAttendanceBatch(tripId, prepared.retryRows);
    } catch (error) {
      outcome = deliveryFailureOutcome(error);
      const permanent = await settleFailedBatch(database, account, prepared.retryRows, error);
      if (permanent) {
        for (const row of prepared.retryRows) {
          recordFinalOutcome(prepared.result, row.payload.session_id, 'rejected');
        }
      }
      return { result: prepared.result, stopDraining: !permanent };
    }

    const retried = await reconcileAttendanceBatch(
      database,
      account,
      tripId,
      prepared.retryRows,
      response,
      false,
    );
    mergeDrainResult(prepared.result, retried.result);
    const confirmed = totalOutcomes(prepared.result.confirmedBySession);
    outcome = confirmed === rows.length ? 'success' : confirmed > 0 ? 'partial' : 'failure';
    return { result: prepared.result, stopDraining: false };
  } finally {
    recordAttendanceRefreshRecovery(rows.length, outcome);
  }
}

export function resumeAttendanceRefreshRecovery(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  rows: PreparedAttendanceRow[],
): Promise<AttendanceDeliveryResult> {
  return recoverRefreshRequiredRows(
    database,
    account,
    tripId,
    rows.map((row) => ({
      ...row,
      refreshReasonCode: refreshReasonFromPendingRow(row),
    })),
  );
}

export async function deliverAttendanceBatch(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  rows: PreparedAttendanceRow[],
): Promise<AttendanceDeliveryResult> {
  let response: z.infer<typeof AttendanceBatchResponseSchema>;
  try {
    response = await sendAttendanceBatch(tripId, rows);
  } catch (error) {
    const permanent = await settleFailedBatch(database, account, rows, error);
    const result = emptyDrainResult();
    if (permanent) {
      for (const row of rows) recordFinalOutcome(result, row.payload.session_id, 'rejected');
    }
    return { result, stopDraining: !permanent };
  }

  const reconciled = await reconcileAttendanceBatch(
    database,
    account,
    tripId,
    rows,
    response,
    true,
  );
  if (reconciled.refreshRequiredRows.length === 0) {
    return { result: reconciled.result, stopDraining: false };
  }
  const recovered = await recoverRefreshRequiredRows(
    database,
    account,
    tripId,
    reconciled.refreshRequiredRows,
  );
  mergeDrainResult(reconciled.result, recovered.result);
  return { result: reconciled.result, stopDraining: recovered.stopDraining };
}
