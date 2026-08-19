import * as Crypto from 'expo-crypto';
import { z } from 'zod';

import { apiRequest, ApiError } from '@/core/api/client';
import { principalAccountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import { AttendanceBatchResponseSchema } from '../api/coordinator-contracts';
import {
  ATTENDANCE_QUEUE_POLICY,
  attendanceDedupeMaterial,
  attendanceQueueCutoffs,
  attendanceSessionQueueLimit,
} from './attendance-policy';
import { authorizeAttendanceTokenForOfflineQueue } from './attendance-token-authorization';

const AttendancePayloadSchema = z
  .object({
    session_id: z.string().uuid(),
    signed_qr: z.string().length(49).regex(/^pdatt:[A-Za-z0-9_-]{43}$/),
    scanned_at: z.string().datetime({ offset: true }),
    source: z.literal('qr'),
  })
  .strict();

const ATTENDANCE_BATCH_LIMIT = 100;

type PendingAttendanceRow = {
  idempotency_key: string;
  dedupe_key: string;
  payload_json: string;
  attempt_count: number;
};

type PreparedAttendanceRow = PendingAttendanceRow & {
  payload: z.infer<typeof AttendancePayloadSchema>;
};

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
      status: 'already_queued' | 'already_confirmed' | 'previously_rejected';
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
  state: 'pending' | 'sending' | 'retryable' | 'rejected';
};

type AttendanceQueueStatusRow = {
  state: 'pending' | 'sending' | 'retryable';
  count: number;
};

const drainInFlight = new Map<string, Promise<AttendanceDrainResult>>();

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
      recordSettled(target[field], sessionId, count);
    }
  }
}

function namespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  return principalAccountNamespace(principal);
}

async function maintainAttendanceQueue(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  nowMs: number,
): Promise<void> {
  const now = new Date(nowMs).toISOString();
  const cutoffs = attendanceQueueCutoffs(nowMs);
  await database.runAsync(
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
        AND state = 'rejected' AND updated_at < ?`,
    account,
    tripId,
    cutoffs.rejected,
  );
  await database.runAsync(
    `DELETE FROM pending_actions
      WHERE idempotency_key IN (
        SELECT idempotency_key FROM pending_actions
         WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
           AND state = 'rejected'
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
}

export async function enqueueQrScan(
  tripId: string,
  sessionId: string,
  signedQr: string,
  options?: Readonly<{ assignedCount?: number }>,
): Promise<AttendanceEnqueueResult> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const idempotencyKey = Crypto.randomUUID();
  const nowMs = Date.now();
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
  await withAccountTransaction(database, async (transaction) => {
    await maintainAttendanceQueue(transaction, account, tripId, nowMs);
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
        status: existing.state === 'rejected' ? 'previously_rejected' : 'already_queued',
        idempotencyKey: existing.idempotency_key,
        duplicate: true,
      };
      return;
    }

    await authorizeAttendanceTokenForOfflineQueue(
      transaction,
      account,
      tripId,
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
        status: stored.state === 'rejected' ? 'previously_rejected' : 'already_queued',
        idempotencyKey: stored.idempotency_key,
        duplicate: true,
      };
      return;
    }
    enqueueResult = { status: 'queued', idempotencyKey, duplicate: false };
  });
  if (!enqueueResult) throw new Error('The attendance scan could not be saved securely.');
  return enqueueResult;
}

function retryDelay(attempt: number): number {
  const capped = Math.min(attempt, 8);
  const base = Math.min(5 * 60_000, 1_000 * 2 ** capped);
  return Math.round(base * (0.75 + Math.random() * 0.5));
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
      `SELECT idempotency_key, dedupe_key, payload_json, attempt_count
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
          SET state = 'sending', attempt_count = attempt_count + 1,
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
}

async function reconcileAttendanceBatch(
  database: Awaited<ReturnType<typeof openAccountDatabase>>,
  account: string,
  tripId: string,
  rows: PreparedAttendanceRow[],
  response: z.infer<typeof AttendanceBatchResponseSchema>,
): Promise<MutableAttendanceDrainResult> {
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
  await withAccountTransaction(database, async (transaction) => {
    const reconciledAt = new Date().toISOString();
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
        continue;
      }

      if (result) {
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
  return reconciled;
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
          : new Date(Date.now() + retryDelay(row.attempt_count + 1)).toISOString(),
        error instanceof ApiError ? error.code : 'NETWORK_ERROR',
        updatedAt,
        row.idempotency_key,
        account,
      );
    }
  });
  return permanent;
}

async function drainTrip(account: string, tripId: string): Promise<AttendanceDrainResult> {
  const database = await openAccountDatabase(account);
  const drainResult = emptyDrainResult();
  await withAccountTransaction(database, async (transaction) => {
    await maintainAttendanceQueue(transaction, account, tripId, Date.now());
  });
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
    if (claimedRows.length === 0) return drainResult;

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

    let response: z.infer<typeof AttendanceBatchResponseSchema>;
    try {
      response = await apiRequest(`/mobile/coordinator/groups/${tripId}/attendance/actions`, {
        method: 'POST',
        schema: AttendanceBatchResponseSchema,
        body: {
          actions: preparedRows.map((row) => ({
            client_event_id: row.idempotency_key,
            ...row.payload,
          })),
        },
      });
    } catch (error) {
      const permanent = await settleFailedBatch(database, account, preparedRows, error);
      if (!permanent) return drainResult;
      for (const row of preparedRows) {
        recordFinalOutcome(drainResult, row.payload.session_id, 'rejected');
      }
      continue;
    }
    const batchResult = await reconcileAttendanceBatch(
      database,
      account,
      tripId,
      preparedRows,
      response,
    );
    mergeDrainResult(drainResult, batchResult);
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
  await withAccountTransaction(database, async (transaction) => {
    await maintainAttendanceQueue(transaction, account, tripId, Date.now());
  });
  const rows = await database.getAllAsync<AttendanceQueueStatusRow>(
    `SELECT state, COUNT(*) AS count FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state IN ('pending', 'sending', 'retryable')
        AND CASE WHEN json_valid(payload_json)
          THEN json_extract(payload_json, '$.session_id')
          ELSE NULL
        END = ?
      GROUP BY state`,
    account,
    tripId,
    sessionId,
  );
  let pending = 0;
  let sending = 0;
  let retryable = 0;
  for (const row of rows) {
    if (row.state === 'pending') pending = row.count;
    else if (row.state === 'sending') sending = row.count;
    else retryable = row.count;
  }
  return {
    pending,
    sending,
    retryable,
    awaitingConfirmation: pending + sending + retryable,
  };
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

export async function acknowledgeRejectedAttendance(tripId: string): Promise<number> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const result = await database.runAsync(
    `DELETE FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND state = 'rejected'`,
    account,
    tripId,
  );
  return result.changes;
}
