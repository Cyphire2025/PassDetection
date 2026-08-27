import * as Crypto from 'expo-crypto';
import { z } from 'zod';

import {
  captureAuthenticationSnapshot,
  isAuthenticationSnapshotCurrent,
  type AuthenticationSnapshot,
} from '@/core/auth/session-store';
import {
  recordAttendanceLocalScanResult,
  recordAttendanceTerminalRejection,
} from '@/core/observability/attendance-observability';
import { recordTripDurableQueueDepths } from '@/core/observability/queue-depth-observability';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import {
  ATTENDANCE_QUEUE_POLICY,
  attendanceDedupeMaterial,
  attendanceQueueCutoffs,
  attendanceSessionQueueLimit,
} from './attendance-policy';
import { trustedQueueRetentionTime } from './attendance-retention-clock';
import { publishAttendanceCloseoutCheckpoint } from './attendance-closeout-checkpoint';
import {
  deliverAttendanceBatch,
  isAttendanceRefreshRecoveryPending,
  resumeAttendanceRefreshRecovery,
  type PendingAttendanceRow,
  type PreparedAttendanceRow,
} from './attendance-queue-delivery';
import { coordinatorAttendanceAccountNamespace as namespace } from './attendance-queue-account';
import {
  clearAttendanceRetryTimer,
  resetAttendanceRetryTimersForTests,
  scheduleNextAttendanceRetry as scheduleNextAttendanceRetryTimer,
} from './attendance-queue-scheduler';
import { markAttendanceNeedsReviewRetryable } from './attendance-scan-review-store';
import { authorizeAttendanceTokenForOfflineQueue } from './attendance-token-authorization';
import { trustedAttendanceScanTime } from './trusted-scan-time';

const AttendancePayloadSchema = z
  .object({
    session_id: z.string().uuid(),
    signed_qr: z.string().length(49).regex(/^pdatt:[A-Za-z0-9_-]{43}$/),
    scanned_at: z.string().datetime({ offset: true }),
    source: z.literal('qr'),
  })
  .strict();

const ATTENDANCE_BATCH_LIMIT = 100;

export type AttendanceDrainResult = Readonly<{
  settledBySession: Readonly<Record<string, number>>;
  confirmedBySession: Readonly<Record<string, number>>;
  newlyAcceptedBySession: Readonly<Record<string, number>>;
  rejectedBySession: Readonly<Record<string, number>>;
}>;

export type AttendanceEnqueueResult =
  | Readonly<{
      status: 'queued';
      idempotencyKey: string;
      duplicate: false;
    }>
  | Readonly<{
      status: 'already_queued' | 'already_confirmed' | 'needs_review' | 'previously_rejected';
      idempotencyKey: string;
      duplicate: true;
    }>
  | Readonly<{
      status: 'capacity_reached';
      capacity: 'session' | 'trip' | 'account';
      idempotencyKey: null;
      duplicate: false;
    }>;

export type AttendanceSessionQueueStatus = Readonly<{
  pending: number;
  sending: number;
  retryable: number;
  needsReview: number;
  awaitingConfirmation: number;
}>;

type MutableAttendanceDrainResult = {
  settledBySession: Record<string, number>;
  confirmedBySession: Record<string, number>;
  newlyAcceptedBySession: Record<string, number>;
  rejectedBySession: Record<string, number>;
};

type ExistingAttendanceAction = {
  idempotency_key: string;
  state: 'pending' | 'sending' | 'retryable' | 'needs_review' | 'rejected';
};

type AttendanceQueueStatusRow = {
  state: 'pending' | 'sending' | 'retryable' | 'needs_review';
  count: number;
};

const drainInFlight = new Map<string, Promise<AttendanceDrainResult>>();

class AttendanceEnqueueAuthenticationChangedError extends Error {
  readonly code = 'AUTH_CONTEXT_CHANGED';

  constructor() {
    super('The authentication boundary changed while saving attendance.');
    this.name = 'AttendanceEnqueueAuthenticationChangedError';
  }
}

function summarizeQueueStatus(rows: AttendanceQueueStatusRow[]): AttendanceSessionQueueStatus {
  let pending = 0;
  let sending = 0;
  let retryable = 0;
  let needsReview = 0;
  for (const row of rows) {
    if (row.state === 'pending') pending = row.count;
    else if (row.state === 'sending') sending = row.count;
    else if (row.state === 'retryable') retryable = row.count;
    else needsReview = row.count;
  }
  return {
    pending,
    sending,
    retryable,
    needsReview,
    awaitingConfirmation: pending + sending + retryable,
  };
}

function emptyDrainResult(): MutableAttendanceDrainResult {
  return {
    settledBySession: {},
    confirmedBySession: {},
    newlyAcceptedBySession: {},
    rejectedBySession: {},
  };
}

function recordSettled(
  target: Record<string, number>,
  sessionId: string,
  count = 1,
): void {
  target[sessionId] = (target[sessionId] ?? 0) + count;
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
      recordSettled(target[field], sessionId, count);
    }
  }
}

function assertEnqueueAuthenticationBoundary(
  snapshot: AuthenticationSnapshot,
  account: string,
): void {
  if (!isAuthenticationSnapshotCurrent(snapshot)) {
    throw new AttendanceEnqueueAuthenticationChangedError();
  }
  try {
    if (namespace() !== account) throw new AttendanceEnqueueAuthenticationChangedError();
  } catch (error) {
    if (error instanceof AttendanceEnqueueAuthenticationChangedError) throw error;
    throw new AttendanceEnqueueAuthenticationChangedError();
  }
}

async function scheduleNextAttendanceRetry(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
): Promise<void> {
  await scheduleNextAttendanceRetryTimer(database, account, tripId, () => {
    try {
      if (namespace() !== account) return;
    } catch {
      return;
    }
    void drainAttendanceQueue(tripId).catch(() => undefined);
  });
}

function duplicateQueueStatus(state: ExistingAttendanceAction['state']):
  'already_queued' | 'needs_review' | 'previously_rejected' {
  if (state === 'needs_review') return 'needs_review';
  if (state === 'rejected') return 'previously_rejected';
  return 'already_queued';
}

function republishCloseoutAfterDurableEnqueue(
  tripId: string,
  sessionId: string,
  result: AttendanceEnqueueResult,
): void {
  if (
    result.status !== 'queued'
    && result.status !== 'already_queued'
    && result.status !== 'needs_review'
    && result.status !== 'previously_rejected'
  ) return;
  // This is deliberately post-commit and best effort: closeout reporting must
  // observe the durable row, while a network/reporting failure must never turn
  // a successfully saved scan into an enqueue failure.
  void publishAttendanceCloseoutCheckpoint(tripId, sessionId).catch(() => undefined);
}

async function maintainAttendanceQueue(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  nowMs: number,
): Promise<number> {
  const now = new Date(nowMs).toISOString();
  const cutoffs = attendanceQueueCutoffs(nowMs);
  const expired = await database.runAsync(
    `UPDATE pending_actions
        SET state = 'rejected', next_attempt_at = NULL,
            last_error_code = 'LOCAL_QUEUE_EXPIRED', updated_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state IN ('pending', 'sending', 'retryable') AND created_at < ?`,
    now,
    account,
    tripId,
    cutoffs.active,
  );
  await database.runAsync(
    `DELETE FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state IN ('needs_review', 'rejected') AND updated_at < ?`,
    account,
    tripId,
    cutoffs.rejected,
  );
  await database.runAsync(
    `DELETE FROM pending_actions
      WHERE idempotency_key IN (
        SELECT idempotency_key FROM pending_actions
         WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
           AND state IN ('needs_review', 'rejected')
         ORDER BY updated_at DESC, idempotency_key DESC
         LIMIT -1 OFFSET ${ATTENDANCE_QUEUE_POLICY.maxRejectedPerTrip}
      )`,
    account,
    tripId,
  );
  await database.runAsync(
    `DELETE FROM attendance_scan_receipts
      WHERE account_namespace = ? AND trip_id = ? AND accepted_at < ?`,
    account,
    tripId,
    cutoffs.receipt,
  );
  await database.runAsync(
    `DELETE FROM attendance_scan_receipts
      WHERE rowid IN (
        SELECT rowid FROM attendance_scan_receipts
         WHERE account_namespace = ? AND trip_id = ?
         ORDER BY accepted_at DESC, client_event_id DESC
         LIMIT -1 OFFSET ${ATTENDANCE_QUEUE_POLICY.maxReceiptsPerTrip}
      )`,
    account,
    tripId,
  );
  return expired.changes;
}

export async function enqueueQrScan(
  tripId: string,
  sessionId: string,
  signedQr: string,
  options?: Readonly<{ assignedCount?: number }>,
): Promise<AttendanceEnqueueResult> {
  const authenticationSnapshot = captureAuthenticationSnapshot();
  const account = namespace();
  const database = await openAccountDatabase(account);
  const idempotencyKey = Crypto.randomUUID();
  // Do not put device wall time into attendance evidence. This revalidates the
  // signed, installation-bound offline lease and fails closed on expiry,
  // rollback, or clock unavailability before anything is written.
  const { timestampMs: nowMs } = await trustedAttendanceScanTime();
  assertEnqueueAuthenticationBoundary(authenticationSnapshot, account);
  const now = new Date(nowMs).toISOString();
  const payload = AttendancePayloadSchema.parse({
    session_id: sessionId,
    signed_qr: signedQr,
    scanned_at: now,
    source: 'qr',
  });
  const [dedupeKey, tokenHash] = await Promise.all([
    Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      attendanceDedupeMaterial(account, tripId, sessionId, signedQr),
    ),
    Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, signedQr),
  ]);
  let enqueueResult: AttendanceEnqueueResult | null = null;
  let expiredRowCount = 0;
  await withAccountTransaction(database, async (transaction) => {
    assertEnqueueAuthenticationBoundary(authenticationSnapshot, account);
    try {
    expiredRowCount = await maintainAttendanceQueue(transaction, account, tripId, nowMs);
    const applied = await transaction.getFirstAsync<{ client_event_id: string }>(
      `SELECT client_event_id FROM attendance_scan_receipts
        WHERE account_namespace = ? AND trip_id = ? AND session_id = ? AND dedupe_key = ?
        LIMIT 1`,
      account,
      tripId,
      sessionId,
      dedupeKey,
    );
    if (applied) {
      enqueueResult = {
        status: 'already_confirmed',
        idempotencyKey: applied.client_event_id,
        duplicate: true,
      };
      return;
    }

    const existing = await transaction.getFirstAsync<ExistingAttendanceAction>(
      `SELECT idempotency_key, state FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
          AND dedupe_key = ?
        LIMIT 1`,
      account,
      tripId,
      dedupeKey,
    );
    if (existing) {
      enqueueResult = {
        status: duplicateQueueStatus(existing.state),
        idempotencyKey: existing.idempotency_key,
        duplicate: true,
      };
      return;
    }

    const authorization = await authorizeAttendanceTokenForOfflineQueue(
      transaction,
      account,
      tripId,
      sessionId,
      tokenHash,
      nowMs,
    );

    const activeTripCount = await transaction.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS count FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
          AND state IN ('pending', 'sending', 'retryable')`,
      account,
      tripId,
    );
    if ((activeTripCount?.count ?? 0) >= ATTENDANCE_QUEUE_POLICY.maxActivePerTrip) {
      enqueueResult = {
        status: 'capacity_reached',
        capacity: 'trip',
        idempotencyKey: null,
        duplicate: false,
      };
      return;
    }
    const activeSessionCount = await transaction.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS count FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
          AND state IN ('pending', 'sending', 'retryable')
          AND CASE WHEN json_valid(payload_json)
            THEN json_extract(payload_json, '$.session_id')
            ELSE NULL
          END = ?`,
      account,
      tripId,
      sessionId,
    );
    if ((activeSessionCount?.count ?? 0) >= attendanceSessionQueueLimit(options?.assignedCount)) {
      enqueueResult = {
        status: 'capacity_reached',
        capacity: 'session',
        idempotencyKey: null,
        duplicate: false,
      };
      return;
    }
    const accountCount = await transaction.getFirstAsync<{ count: number }>(
      `SELECT COUNT(*) AS count FROM pending_actions
        WHERE account_namespace = ? AND action_type = 'attendance.scan'
          AND state IN ('pending', 'sending', 'retryable')`,
      account,
    );
    if ((accountCount?.count ?? 0) >= ATTENDANCE_QUEUE_POLICY.maxActivePerAccount) {
      enqueueResult = {
        status: 'capacity_reached',
        capacity: 'account',
        idempotencyKey: null,
        duplicate: false,
      };
      return;
    }

    await transaction.runAsync(
      `INSERT OR IGNORE INTO pending_actions
        (idempotency_key, account_namespace, trip_id, action_type, dedupe_key, payload_json, base_version,
         state, attempt_count, next_attempt_at, last_error_code, created_at, updated_at)
       VALUES (?, ?, ?, 'attendance.scan', ?, ?, NULL, 'pending', 0, NULL, NULL, ?, ?)`,
      idempotencyKey,
      account,
      tripId,
      dedupeKey,
      JSON.stringify(payload),
      now,
      now,
    );
    const stored = await transaction.getFirstAsync<ExistingAttendanceAction>(
      `SELECT idempotency_key, state FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
          AND dedupe_key = ?
        LIMIT 1`,
      account,
      tripId,
      dedupeKey,
    );
    if (!stored) throw new Error('The attendance scan could not be saved securely.');
    if (stored.idempotency_key !== idempotencyKey) {
      enqueueResult = {
        status: duplicateQueueStatus(stored.state),
        idempotencyKey: stored.idempotency_key,
        duplicate: true,
      };
      return;
    }
    await transaction.runAsync(
      `INSERT INTO attendance_scan_issue_context
        (idempotency_key, account_namespace, trip_id, session_id, session_label,
         passenger_id, passenger_label, scan_reference, captured_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(idempotency_key) DO NOTHING`,
      idempotencyKey,
      account,
      tripId,
      sessionId,
      authorization.sessionLabel,
      authorization.passengerId,
      authorization.passengerLabel,
      dedupeKey,
      now,
      now,
    );
    enqueueResult = { status: 'queued', idempotencyKey, duplicate: false };
    } finally {
      // A logout, refresh rotation, or account switch during native I/O rolls
      // the transaction back instead of committing under a stale principal.
      assertEnqueueAuthenticationBoundary(authenticationSnapshot, account);
    }
  });
  assertEnqueueAuthenticationBoundary(authenticationSnapshot, account);
  // TypeScript cannot observe assignments made inside the transaction callback,
  // so re-establish the runtime-checked outcome at the callback boundary.
  const committedResult = enqueueResult as AttendanceEnqueueResult | null;
  if (!committedResult) throw new Error('The attendance scan could not be saved securely.');
  recordAttendanceTerminalRejection('LOCAL_QUEUE_EXPIRED', expiredRowCount);
  recordAttendanceLocalScanResult(committedResult.status);
  republishCloseoutAfterDurableEnqueue(tripId, sessionId, committedResult);
  return committedResult;
}

async function claimAttendanceBatch(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
): Promise<PendingAttendanceRow[]> {
  const claimed: PendingAttendanceRow[] = [];
  await withAccountTransaction(database, async (transaction) => {
    const now = new Date().toISOString();
    const rows = await transaction.getAllAsync<PendingAttendanceRow>(
      `SELECT idempotency_key, dedupe_key, payload_json, attempt_count, created_at,
              refresh_attempt_count, last_error_code
         FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ?
          AND action_type = 'attendance.scan'
          AND state IN ('pending', 'retryable')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at, idempotency_key
        LIMIT ${ATTENDANCE_BATCH_LIMIT}`,
      account,
      tripId,
      now,
    );
    if (rows.length === 0) return;

    const placeholders = rows.map(() => '?').join(', ');
    const result = await transaction.runAsync(
      `UPDATE pending_actions
          SET state = 'sending',
              attempt_count = attempt_count + CASE
                WHEN last_error_code LIKE 'REFRESH_PENDING:%' THEN 0 ELSE 1 END,
              next_attempt_at = NULL, last_error_code = NULL, updated_at = ?
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
          AND state IN ('pending', 'retryable')
          AND idempotency_key IN (${placeholders})`,
      now,
      account,
      tripId,
      ...rows.map((row) => row.idempotency_key),
    );
    if (result.changes !== rows.length) {
      throw new Error('The attendance batch could not be claimed atomically.');
    }
    claimed.push(...rows);
  });
  return claimed;
}

async function rejectInvalidLocalRows(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  rows: PendingAttendanceRow[],
): Promise<void> {
  if (rows.length === 0) return;
  await withAccountTransaction(database, async (transaction) => {
    const now = new Date().toISOString();
    for (const row of rows) {
      await transaction.runAsync(
        `UPDATE pending_actions
            SET state = 'rejected', next_attempt_at = NULL,
                last_error_code = 'INVALID_LOCAL_PAYLOAD', updated_at = ?
          WHERE idempotency_key = ? AND account_namespace = ? AND state = 'sending'`,
        now,
        row.idempotency_key,
        account,
      );
    }
  });
  recordAttendanceTerminalRejection('INVALID_LOCAL_PAYLOAD', rows.length);
}

async function drainTrip(account: string, tripId: string): Promise<AttendanceDrainResult> {
  clearAttendanceRetryTimer(account, tripId);
  const database = await openAccountDatabase(account);
  const drainResult = emptyDrainResult();
  let expiredRowCount = 0;
  const retentionNowMs = await trustedQueueRetentionTime();
  if (retentionNowMs !== null) {
    await withAccountTransaction(database, async (transaction) => {
      expiredRowCount = await maintainAttendanceQueue(transaction, account, tripId, retentionNowMs);
    });
  }
  recordAttendanceTerminalRejection('LOCAL_QUEUE_EXPIRED', expiredRowCount);
  const staleSendingBefore = new Date(Date.now() - 2 * 60_000).toISOString();
  await database.runAsync(
    `UPDATE pending_actions
        SET state = 'retryable', next_attempt_at = NULL, last_error_code = 'INTERRUPTED_RETRY', updated_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state = 'sending' AND updated_at < ?`,
    new Date().toISOString(),
    account,
    tripId,
    staleSendingBefore,
  );
  while (true) {
    const claimedRows = await claimAttendanceBatch(database, account, tripId);
    if (claimedRows.length === 0) {
      await scheduleNextAttendanceRetry(database, account, tripId);
      await recordTripDurableQueueDepths(database, account, tripId);
      return drainResult;
    }

    const preparedRows: PreparedAttendanceRow[] = [];
    const invalidRows: PendingAttendanceRow[] = [];
    for (const row of claimedRows) {
      let rawPayload: unknown;
      try {
        rawPayload = JSON.parse(row.payload_json) as unknown;
      } catch {
        rawPayload = null;
      }
      const parsed = AttendancePayloadSchema.safeParse(rawPayload);
      if (parsed.success) {
        preparedRows.push({ ...row, payload: parsed.data });
      } else {
        invalidRows.push(row);
      }
    }
    await rejectInvalidLocalRows(database, account, invalidRows);
    if (preparedRows.length === 0) continue;

    const refreshRecoveryRows = preparedRows.filter(isAttendanceRefreshRecoveryPending);
    const ordinaryRows = preparedRows.filter((row) => !isAttendanceRefreshRecoveryPending(row));
    let stopDraining = false;
    if (refreshRecoveryRows.length > 0) {
      const resumed = await resumeAttendanceRefreshRecovery(
        database,
        account,
        tripId,
        refreshRecoveryRows,
      );
      mergeDrainResult(drainResult, resumed.result);
      stopDraining = resumed.stopDraining;
    }
    if (ordinaryRows.length > 0) {
      const delivered = await deliverAttendanceBatch(database, account, tripId, ordinaryRows);
      mergeDrainResult(drainResult, delivered.result);
      stopDraining = stopDraining || delivered.stopDraining;
    }
    if (stopDraining) {
      await scheduleNextAttendanceRetry(database, account, tripId);
      await recordTripDurableQueueDepths(database, account, tripId);
      return drainResult;
    }
  }
}

export function drainAttendanceQueue(tripId: string): Promise<AttendanceDrainResult> {
  const account = namespace();
  const key = `${account}:${tripId}`;
  const active = drainInFlight.get(key);
  if (active) return active;
  const request = drainTrip(account, tripId).finally(() => {
    if (drainInFlight.get(key) === request) drainInFlight.delete(key);
  });
  drainInFlight.set(key, request);
  return request;
}

export async function attendanceSessionQueueStatus(
  tripId: string,
  sessionId: string,
): Promise<AttendanceSessionQueueStatus> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  let expiredRowCount = 0;
  const retentionNowMs = await trustedQueueRetentionTime();
  if (retentionNowMs !== null) {
    await withAccountTransaction(database, async (transaction) => {
      expiredRowCount = await maintainAttendanceQueue(transaction, account, tripId, retentionNowMs);
    });
  }
  recordAttendanceTerminalRejection('LOCAL_QUEUE_EXPIRED', expiredRowCount);
  const rows = await database.getAllAsync<AttendanceQueueStatusRow>(
    `SELECT state, COUNT(*) AS count FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state IN ('pending', 'sending', 'retryable', 'needs_review')
        AND CASE WHEN json_valid(payload_json)
          THEN json_extract(payload_json, '$.session_id')
          ELSE NULL
        END = ?
      GROUP BY state`,
    account,
    tripId,
    sessionId,
  );
  return summarizeQueueStatus(rows);
}

export async function attendanceTripQueueStatus(
  tripId: string,
): Promise<AttendanceSessionQueueStatus> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  let expiredRowCount = 0;
  const retentionNowMs = await trustedQueueRetentionTime();
  if (retentionNowMs !== null) {
    await withAccountTransaction(database, async (transaction) => {
      expiredRowCount = await maintainAttendanceQueue(transaction, account, tripId, retentionNowMs);
    });
  }
  recordAttendanceTerminalRejection('LOCAL_QUEUE_EXPIRED', expiredRowCount);
  const rows = await database.getAllAsync<AttendanceQueueStatusRow>(
    `SELECT state, COUNT(*) AS count FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state IN ('pending', 'sending', 'retryable', 'needs_review')
      GROUP BY state`,
    account,
    tripId,
  );
  return summarizeQueueStatus(rows);
}

export async function attendanceQueueCounts(tripId: string) {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const rows = await database.getAllAsync<{ state: string; count: number }>(
    `SELECT state, COUNT(*) AS count FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
      GROUP BY state`,
    account,
    tripId,
  );
  return Object.fromEntries(rows.map((row) => [row.state, row.count])) as Record<string, number>;
}

export {
  acknowledgeAttendanceNeedsReview,
  acknowledgeRejectedAttendance,
  listAttendanceNeedsReview,
} from './attendance-scan-review-store';
export type { AttendanceNeedsReviewItem } from './attendance-scan-review-store';

export async function retryAttendanceNeedsReview(
  tripId: string,
  idempotencyKey: string,
): Promise<AttendanceDrainResult | null> {
  if (!(await markAttendanceNeedsReviewRetryable(tripId, idempotencyKey))) return null;
  return drainAttendanceQueue(tripId);
}

export function resetAttendanceQueueRuntimeForTests(): void {
  resetAttendanceRetryTimersForTests();
  drainInFlight.clear();
}
