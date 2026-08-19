const MEBIBYTE = 1024 * 1024;

/**
 * Named policy for maintenance that must run outside user-visible transactions.
 * Execution belongs to the database lifecycle coordinator; this module only produces a bounded,
 * testable plan and never issues SQL on an arbitrary connection.
 */
export const DEFAULT_IDLE_STORAGE_MAINTENANCE_POLICY = Object.freeze({
  minimumIdleDurationMs: 30_000,
  minimumRunIntervalMs: 24 * 60 * 60 * 1_000,
  wallClockRollbackToleranceMs: 5 * 60 * 1_000,
  walCheckpointThresholdBytes: 8 * MEBIBYTE,
  minimumFreelistPages: 256,
  minimumFreelistRatio: 0.15,
  maximumIncrementalVacuumPagesPerRun: 512,
});

export type IdleStorageMaintenancePolicy = Readonly<{
  minimumIdleDurationMs: number;
  minimumRunIntervalMs: number;
  wallClockRollbackToleranceMs: number;
  walCheckpointThresholdBytes: number;
  minimumFreelistPages: number;
  minimumFreelistRatio: number;
  maximumIncrementalVacuumPagesPerRun: number;
}>;

export type IdleStorageMaintenanceSnapshot = Readonly<{
  nowMs: number;
  lastRunAtMs: number | null;
  appIsActive: boolean;
  idleDurationMs: number;
  hasPendingUserWrite: boolean;
  isCharging: boolean | null;
  lowPowerModeEnabled: boolean;
  walBytes: number | null;
  pageCount: number;
  freelistPageCount: number;
  /** SQLite PRAGMA auto_vacuum: 0=none, 1=full, 2=incremental. */
  autoVacuumMode: 0 | 1 | 2;
}>;

export type IdleStorageMaintenanceOperation =
  | Readonly<{ type: 'optimize' }>
  | Readonly<{ type: 'wal_checkpoint'; mode: 'passive' }>
  | Readonly<{ type: 'incremental_vacuum'; maximumPages: number }>;

export type IdleStorageMaintenancePlan = Readonly<{
  due: boolean;
  operations: readonly IdleStorageMaintenanceOperation[];
  skipReason:
    | 'app_not_active'
    | 'not_idle'
    | 'user_write_pending'
    | 'interval_not_elapsed'
    | null;
}>;

function assertNonNegativeSafeInteger(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative safe integer.`);
  }
}

function validateMaintenancePolicy(policy: IdleStorageMaintenancePolicy): void {
  assertNonNegativeSafeInteger(policy.minimumIdleDurationMs, 'Minimum idle duration');
  assertNonNegativeSafeInteger(policy.minimumRunIntervalMs, 'Maintenance interval');
  assertNonNegativeSafeInteger(
    policy.wallClockRollbackToleranceMs,
    'Maintenance clock tolerance',
  );
  assertNonNegativeSafeInteger(policy.walCheckpointThresholdBytes, 'WAL checkpoint threshold');
  assertNonNegativeSafeInteger(policy.minimumFreelistPages, 'Minimum freelist pages');
  assertNonNegativeSafeInteger(
    policy.maximumIncrementalVacuumPagesPerRun,
    'Incremental vacuum page limit',
  );
  if (
    !Number.isFinite(policy.minimumFreelistRatio)
    || policy.minimumFreelistRatio < 0
    || policy.minimumFreelistRatio > 1
  ) {
    throw new Error('Minimum freelist ratio must be between zero and one.');
  }
}

function validateMaintenanceSnapshot(snapshot: IdleStorageMaintenanceSnapshot): void {
  assertNonNegativeSafeInteger(snapshot.nowMs, 'Maintenance clock');
  if (snapshot.lastRunAtMs !== null) {
    assertNonNegativeSafeInteger(snapshot.lastRunAtMs, 'Last maintenance time');
  }
  assertNonNegativeSafeInteger(snapshot.idleDurationMs, 'Idle duration');
  if (snapshot.walBytes !== null) {
    assertNonNegativeSafeInteger(snapshot.walBytes, 'WAL size');
  }
  assertNonNegativeSafeInteger(snapshot.pageCount, 'Database page count');
  assertNonNegativeSafeInteger(snapshot.freelistPageCount, 'Database freelist page count');
  if (snapshot.freelistPageCount > snapshot.pageCount) {
    throw new Error('Database freelist pages cannot exceed total pages.');
  }
}

function intervalElapsed(
  snapshot: IdleStorageMaintenanceSnapshot,
  policy: IdleStorageMaintenancePolicy,
): boolean {
  if (snapshot.lastRunAtMs === null) return true;
  if (snapshot.lastRunAtMs > snapshot.nowMs + policy.wallClockRollbackToleranceMs) {
    // A rollback/future timestamp cannot suppress maintenance indefinitely.
    return true;
  }
  return snapshot.nowMs - snapshot.lastRunAtMs >= policy.minimumRunIntervalMs;
}

/**
 * Plans bounded SQLite housekeeping for an already-idle, lifecycle-coordinated connection.
 *
 * A blocking full `VACUUM` is intentionally never emitted. Incremental reclaim is proposed only
 * when the database was created with `auto_vacuum=INCREMENTAL`, the device is charging, and the
 * free-page signal is material. `wal_checkpoint(PASSIVE)` is likewise threshold-gated.
 */
export function planIdleStorageMaintenance(
  snapshot: IdleStorageMaintenanceSnapshot,
  policy: IdleStorageMaintenancePolicy = DEFAULT_IDLE_STORAGE_MAINTENANCE_POLICY,
): IdleStorageMaintenancePlan {
  validateMaintenancePolicy(policy);
  validateMaintenanceSnapshot(snapshot);

  if (!snapshot.appIsActive) {
    return { due: false, operations: [], skipReason: 'app_not_active' };
  }
  if (snapshot.idleDurationMs < policy.minimumIdleDurationMs) {
    return { due: false, operations: [], skipReason: 'not_idle' };
  }
  if (snapshot.hasPendingUserWrite) {
    return { due: false, operations: [], skipReason: 'user_write_pending' };
  }
  if (!intervalElapsed(snapshot, policy)) {
    return { due: false, operations: [], skipReason: 'interval_not_elapsed' };
  }

  const operations: IdleStorageMaintenanceOperation[] = [{ type: 'optimize' }];
  if (
    snapshot.walBytes !== null
    && snapshot.walBytes >= policy.walCheckpointThresholdBytes
  ) {
    operations.push({ type: 'wal_checkpoint', mode: 'passive' });
  }

  const freelistRatio = snapshot.pageCount === 0
    ? 0
    : snapshot.freelistPageCount / snapshot.pageCount;
  if (
    snapshot.autoVacuumMode === 2
    && snapshot.isCharging === true
    && !snapshot.lowPowerModeEnabled
    && snapshot.freelistPageCount >= policy.minimumFreelistPages
    && freelistRatio >= policy.minimumFreelistRatio
  ) {
    operations.push({
      type: 'incremental_vacuum',
      maximumPages: Math.min(
        snapshot.freelistPageCount,
        policy.maximumIncrementalVacuumPagesPerRun,
      ),
    });
  }

  return { due: true, operations, skipReason: null };
}
