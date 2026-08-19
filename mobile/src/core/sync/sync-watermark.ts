import { openAccountDatabase } from '@/core/storage/database';

import {
  assertSyncContextActive,
  type ImmutableSyncContext,
} from './sync-context';

type SyncRuntimeStateRow = Readonly<{
  last_successful_full_sync_at_epoch_ms: number;
}>;

export async function loadLastSuccessfulFullSyncAt(
  syncContext: ImmutableSyncContext,
): Promise<number | null> {
  assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(syncContext.namespace);
  assertSyncContextActive(syncContext);
  const row = await database.getFirstAsync<SyncRuntimeStateRow>(
    `SELECT last_successful_full_sync_at_epoch_ms
       FROM sync_runtime_state
      WHERE account_namespace = ?`,
    syncContext.namespace,
  );
  assertSyncContextActive(syncContext);
  const value = row?.last_successful_full_sync_at_epoch_ms;
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
}

export async function storeLastSuccessfulFullSyncAt(
  syncContext: ImmutableSyncContext,
  completedAtEpochMs: number,
): Promise<void> {
  if (!Number.isSafeInteger(completedAtEpochMs) || completedAtEpochMs < 0) {
    throw new Error('The full synchronization watermark was invalid.');
  }
  assertSyncContextActive(syncContext);
  const database = await openAccountDatabase(syncContext.namespace);
  assertSyncContextActive(syncContext);
  await database.runAsync(
    `INSERT INTO sync_runtime_state
      (account_namespace, last_successful_full_sync_at_epoch_ms)
     VALUES (?, ?)
     ON CONFLICT(account_namespace) DO UPDATE SET
       last_successful_full_sync_at_epoch_ms = excluded.last_successful_full_sync_at_epoch_ms`,
    syncContext.namespace,
    completedAtEpochMs,
  );
  assertSyncContextActive(syncContext);
}
