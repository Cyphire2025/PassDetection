import {
  DEFAULT_IDLE_STORAGE_MAINTENANCE_POLICY,
  planIdleStorageMaintenance,
  type IdleStorageMaintenanceSnapshot,
} from '../storage-maintenance-policy';

const DAY_MS = 24 * 60 * 60 * 1_000;

function snapshot(
  overrides: Partial<IdleStorageMaintenanceSnapshot> = {},
): IdleStorageMaintenanceSnapshot {
  return {
    nowMs: 10 * DAY_MS,
    lastRunAtMs: 8 * DAY_MS,
    appIsActive: true,
    idleDurationMs: 60_000,
    hasPendingUserWrite: false,
    isCharging: true,
    lowPowerModeEnabled: false,
    walBytes: 9 * 1024 * 1024,
    pageCount: 4_000,
    freelistPageCount: 800,
    autoVacuumMode: 2,
    ...overrides,
  };
}

describe('idle storage maintenance policy', () => {
  test('skips database work while backgrounded, busy, or inside the run interval', () => {
    expect(planIdleStorageMaintenance(snapshot({ appIsActive: false }))).toEqual({
      due: false,
      operations: [],
      skipReason: 'app_not_active',
    });
    expect(planIdleStorageMaintenance(snapshot({ idleDurationMs: 29_999 }))).toMatchObject({
      due: false,
      skipReason: 'not_idle',
    });
    expect(planIdleStorageMaintenance(snapshot({ hasPendingUserWrite: true }))).toMatchObject({
      due: false,
      skipReason: 'user_write_pending',
    });
    expect(planIdleStorageMaintenance(snapshot({
      lastRunAtMs: (10 * DAY_MS) - 1_000,
    }))).toMatchObject({
      due: false,
      skipReason: 'interval_not_elapsed',
    });
  });

  test('plans optimize, passive checkpoint, and bounded incremental reclaim when supported', () => {
    expect(planIdleStorageMaintenance(snapshot())).toEqual({
      due: true,
      operations: [
        { type: 'optimize' },
        { type: 'wal_checkpoint', mode: 'passive' },
        { type: 'incremental_vacuum', maximumPages: 512 },
      ],
      skipReason: null,
    });
  });

  test.each([
    ['auto-vacuum disabled', { autoVacuumMode: 0 as const }],
    ['full auto-vacuum mode', { autoVacuumMode: 1 as const }],
    ['not charging', { isCharging: false }],
    ['charging state unknown', { isCharging: null }],
    ['low power mode', { lowPowerModeEnabled: true }],
    ['too few free pages', { freelistPageCount: 100 }],
  ])('does not propose incremental vacuum when %s', (_label, overrides) => {
    const plan = planIdleStorageMaintenance(snapshot(overrides));
    expect(plan.operations.some((operation) => operation.type === 'incremental_vacuum')).toBe(false);
  });

  test('threshold-gates WAL checkpoint and never emits a blocking full vacuum', () => {
    const plan = planIdleStorageMaintenance(snapshot({
      walBytes: DEFAULT_IDLE_STORAGE_MAINTENANCE_POLICY.walCheckpointThresholdBytes - 1,
      autoVacuumMode: 0,
    }));

    expect(plan.operations).toEqual([{ type: 'optimize' }]);
    expect(JSON.stringify(plan)).not.toMatch(/full|VACUUM/i);
  });

  test('does not let a future maintenance timestamp suppress work indefinitely', () => {
    const tolerance = DEFAULT_IDLE_STORAGE_MAINTENANCE_POLICY.wallClockRollbackToleranceMs;
    const plan = planIdleStorageMaintenance(snapshot({
      lastRunAtMs: (10 * DAY_MS) + tolerance + 1,
    }));

    expect(plan.due).toBe(true);
  });

  test('rejects impossible page telemetry instead of planning destructive maintenance', () => {
    expect(() => planIdleStorageMaintenance(snapshot({
      pageCount: 10,
      freelistPageCount: 11,
    }))).toThrow('cannot exceed total pages');
  });
});
