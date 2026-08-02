import * as Crypto from 'expo-crypto';
import { z } from 'zod';

import { apiRequest, ApiError } from '@/core/api/client';
import { accountNamespace } from '@/core/auth/types';
import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';

import { AttendanceBatchResponseSchema } from '../api/coordinator-contracts';
import { attendanceDedupeMaterial } from './attendance-policy';

const AttendancePayloadSchema = z
  .object({
    session_id: z.string().uuid(),
    signed_qr: z.string().min(16).max(4096),
    scanned_at: z.string().datetime({ offset: true }),
    source: z.literal('qr'),
  })
  .strict();

const drainInFlight = new Map<string, Promise<void>>();

function namespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  return accountNamespace({ agencyId: principal.agencyId, principalId: principal.id });
}

export async function enqueueQrScan(
  tripId: string,
  sessionId: string,
  signedQr: string,
): Promise<{ idempotencyKey: string; duplicate: boolean }> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const idempotencyKey = Crypto.randomUUID();
  const now = new Date().toISOString();
  const payload = AttendancePayloadSchema.parse({
    session_id: sessionId,
    signed_qr: signedQr,
    scanned_at: now,
    source: 'qr',
  });
  const dedupeKey = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    attendanceDedupeMaterial(account, tripId, sessionId, signedQr),
  );
  const existing = await database.getFirstAsync<{ idempotency_key: string }>(
    `SELECT idempotency_key FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND dedupe_key = ?
      LIMIT 1`,
    account,
    tripId,
    dedupeKey,
  );
  if (existing) return { idempotencyKey: existing.idempotency_key, duplicate: true };

  await database.runAsync(
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
  const stored = await database.getFirstAsync<{ idempotency_key: string }>(
    `SELECT idempotency_key FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'attendance.scan'
        AND dedupe_key = ?
      LIMIT 1`,
    account,
    tripId,
    dedupeKey,
  );
  if (!stored) throw new Error('The attendance scan could not be saved securely.');
  return {
    idempotencyKey: stored.idempotency_key,
    duplicate: stored.idempotency_key !== idempotencyKey,
  };
}

function retryDelay(attempt: number): number {
  const capped = Math.min(attempt, 8);
  const base = Math.min(5 * 60_000, 1_000 * 2 ** capped);
  return Math.round(base * (0.75 + Math.random() * 0.5));
}

async function drainTrip(tripId: string): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
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
    const row = await database.getFirstAsync<{
      idempotency_key: string;
      payload_json: string;
      attempt_count: number;
    }>(
      `SELECT idempotency_key, payload_json, attempt_count
         FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ?
          AND action_type = 'attendance.scan'
          AND state IN ('pending', 'retryable')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at
        LIMIT 1`,
      account,
      tripId,
      new Date().toISOString(),
    );
    if (!row) return;

    let rawPayload: unknown;
    try {
      rawPayload = JSON.parse(row.payload_json) as unknown;
    } catch {
      rawPayload = null;
    }
    const parsed = AttendancePayloadSchema.safeParse(rawPayload);
    if (!parsed.success) {
      await database.runAsync(
        `UPDATE pending_actions SET state = 'rejected', last_error_code = 'INVALID_LOCAL_PAYLOAD', updated_at = ?
          WHERE idempotency_key = ? AND account_namespace = ?`,
        new Date().toISOString(),
        row.idempotency_key,
        account,
      );
      continue;
    }

    await database.runAsync(
      `UPDATE pending_actions SET state = 'sending', attempt_count = attempt_count + 1, updated_at = ?
        WHERE idempotency_key = ? AND account_namespace = ?`,
      new Date().toISOString(),
      row.idempotency_key,
      account,
    );
    try {
      const response = await apiRequest(`/mobile/coordinator/groups/${tripId}/attendance/actions`, {
        method: 'POST',
        schema: AttendanceBatchResponseSchema,
        body: {
          actions: [
            {
              client_event_id: row.idempotency_key,
              ...parsed.data,
            },
          ],
        },
      });
      const result = response.results[0];
      if (result?.status === 'accepted' || result?.status === 'already_applied') {
        await database.runAsync(
          'DELETE FROM pending_actions WHERE idempotency_key = ? AND account_namespace = ?',
          row.idempotency_key,
          account,
        );
      } else {
        await database.runAsync(
          `UPDATE pending_actions SET state = 'rejected', last_error_code = ?, updated_at = ?
            WHERE idempotency_key = ? AND account_namespace = ?`,
          result?.reason_code ?? result?.status ?? 'REJECTED',
          new Date().toISOString(),
          row.idempotency_key,
          account,
        );
      }
    } catch (error) {
      const permanent = error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429;
      const attempt = row.attempt_count + 1;
      await database.runAsync(
        `UPDATE pending_actions
            SET state = ?, next_attempt_at = ?, last_error_code = ?, updated_at = ?
          WHERE idempotency_key = ? AND account_namespace = ?`,
        permanent ? 'rejected' : 'retryable',
        permanent ? null : new Date(Date.now() + retryDelay(attempt)).toISOString(),
        error instanceof ApiError ? error.code : 'NETWORK_ERROR',
        new Date().toISOString(),
        row.idempotency_key,
        account,
      );
      if (!permanent) return;
    }
  }
}

export function drainAttendanceQueue(tripId: string): Promise<void> {
  const account = namespace();
  const key = `${account}:${tripId}`;
  const active = drainInFlight.get(key);
  if (active) return active;
  const request = drainTrip(tripId).finally(() => {
    if (drainInFlight.get(key) === request) drainInFlight.delete(key);
  });
  drainInFlight.set(key, request);
  return request;
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
