import * as Crypto from 'expo-crypto';
import { z } from 'zod';

import { apiRequest, ApiError } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { openAccountDatabase } from '@/core/storage/database';

import { IncidentActionResponseSchema } from '../api/coordinator-contracts';

const IncidentPayloadSchema = z.object({
  title: z.string().trim().min(3).max(160),
  description: z.string().trim().min(3).max(2_000),
  severity: z.enum(['low', 'medium', 'high', 'critical']),
  occurred_at: z.string().datetime({ offset: true }),
}).strict();

export type IncidentInput = Omit<z.infer<typeof IncidentPayloadSchema>, 'occurred_at'>;
const drainInFlight = new Map<string, Promise<void>>();

function namespace(): string {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') throw new Error('Coordinator authentication is required.');
  return principalAccountNamespace(principal);
}

export async function enqueueIncident(tripId: string, input: IncidentInput): Promise<string> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const idempotencyKey = Crypto.randomUUID();
  const now = new Date().toISOString();
  const payload = IncidentPayloadSchema.parse({ ...input, occurred_at: now });
  await database.runAsync(
    `INSERT INTO pending_actions
      (idempotency_key, account_namespace, trip_id, action_type, dedupe_key, payload_json,
       base_version, state, attempt_count, next_attempt_at, last_error_code, created_at, updated_at)
     VALUES (?, ?, ?, 'incident.create', NULL, ?, NULL, 'pending', 0, NULL, NULL, ?, ?)`,
    idempotencyKey,
    account,
    tripId,
    JSON.stringify(payload),
    now,
    now,
  );
  return idempotencyKey;
}

function retryAt(attempt: number): string {
  const base = Math.min(5 * 60_000, 1_000 * 2 ** Math.min(attempt, 8));
  const jittered = base * (0.75 + Math.random() * 0.5);
  return new Date(Date.now() + jittered).toISOString();
}

async function drainTripIncidents(tripId: string): Promise<void> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  await database.runAsync(
    `UPDATE pending_actions SET state = 'retryable', next_attempt_at = NULL,
       last_error_code = 'INTERRUPTED_RETRY', updated_at = ?
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'incident.create'
        AND state = 'sending' AND updated_at < ?`,
    new Date().toISOString(),
    account,
    tripId,
    new Date(Date.now() - 2 * 60_000).toISOString(),
  );
  while (true) {
    const row = await database.getFirstAsync<{ idempotency_key: string; payload_json: string; attempt_count: number }>(
      `SELECT idempotency_key, payload_json, attempt_count FROM pending_actions
        WHERE account_namespace = ? AND trip_id = ? AND action_type = 'incident.create'
          AND state IN ('pending', 'retryable')
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at LIMIT 1`,
      account,
      tripId,
      new Date().toISOString(),
    );
    if (!row) return;
    let raw: unknown = null;
    try { raw = JSON.parse(row.payload_json) as unknown; } catch { /* validated below */ }
    const payload = IncidentPayloadSchema.safeParse(raw);
    if (!payload.success) {
      await database.runAsync(
        `UPDATE pending_actions SET state = 'rejected', last_error_code = 'INVALID_LOCAL_PAYLOAD', updated_at = ?
          WHERE account_namespace = ? AND idempotency_key = ?`,
        new Date().toISOString(), account, row.idempotency_key,
      );
      continue;
    }
    await database.runAsync(
      `UPDATE pending_actions SET state = 'sending', attempt_count = attempt_count + 1, updated_at = ?
        WHERE account_namespace = ? AND idempotency_key = ?`,
      new Date().toISOString(), account, row.idempotency_key,
    );
    try {
      const result = await apiRequest(`/mobile/coordinator/groups/${tripId}/incidents`, {
        method: 'POST',
        schema: IncidentActionResponseSchema,
        body: { client_event_id: row.idempotency_key, ...payload.data },
      });
      if (result.status === 'accepted' || result.status === 'already_applied') {
        await database.runAsync('DELETE FROM pending_actions WHERE account_namespace = ? AND idempotency_key = ?', account, row.idempotency_key);
      } else {
        await database.runAsync(
          `UPDATE pending_actions SET state = 'rejected', last_error_code = ?, updated_at = ?
            WHERE account_namespace = ? AND idempotency_key = ?`,
          result.reason_code ?? 'REJECTED', new Date().toISOString(), account, row.idempotency_key,
        );
      }
    } catch (error) {
      const permanent = error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429;
      await database.runAsync(
        `UPDATE pending_actions SET state = ?, next_attempt_at = ?, last_error_code = ?, updated_at = ?
          WHERE account_namespace = ? AND idempotency_key = ?`,
        permanent ? 'rejected' : 'retryable',
        permanent ? null : retryAt(row.attempt_count + 1),
        error instanceof ApiError ? error.code : 'NETWORK_ERROR',
        new Date().toISOString(), account, row.idempotency_key,
      );
      return;
    }
  }
}

export function drainIncidentQueue(tripId: string): Promise<void> {
  const account = namespace();
  const key = `${account}:${tripId}`;
  const current = drainInFlight.get(key);
  if (current) return current;
  const request = drainTripIncidents(tripId).finally(() => {
    if (drainInFlight.get(key) === request) drainInFlight.delete(key);
  });
  drainInFlight.set(key, request);
  return request;
}

export async function incidentQueueCount(tripId: string): Promise<number> {
  const account = namespace();
  const database = await openAccountDatabase(account);
  const row = await database.getFirstAsync<{ count: number }>(
    `SELECT COUNT(*) AS count FROM pending_actions
      WHERE account_namespace = ? AND trip_id = ? AND action_type = 'incident.create'
        AND state IN ('pending', 'sending', 'retryable')`,
    account, tripId,
  );
  return row?.count ?? 0;
}
