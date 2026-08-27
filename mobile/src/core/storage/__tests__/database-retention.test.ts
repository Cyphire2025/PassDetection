import { recordStorageMaintenance } from '@/core/observability/storage-observability';

import { applyAccountStorageRetention } from '../database-retention';

jest.mock('@/core/observability/storage-observability', () => ({
  recordStorageMaintenance: jest.fn(),
}));

const mockedRecordStorageMaintenance = jest.mocked(recordStorageMaintenance);

function databaseHarness(failAtRun = -1) {
  let runs = 0;
  return {
    execAsync: jest.fn(async (_sql: string) => undefined),
    runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => {
      runs += 1;
      if (runs === failAtRun) throw new Error('native write failed');
      return { changes: 1, lastInsertRowId: 0 };
    }),
  };
}

describe('account storage retention execution', () => {
  beforeEach(() => jest.clearAllMocks());

  test('compacts only account-scoped terminal/audit data in one crash-atomic transaction', async () => {
    const database = databaseHarness();
    await applyAccountStorageRetention(
      database as never,
      'agency.account-a',
      {
        maintenanceNowMs: Date.parse('2030-06-01T00:00:00.000Z'),
        trustedAttendanceNowMs: Date.parse('2030-06-01T00:00:00.000Z'),
      },
    );

    expect(database.execAsync.mock.calls.map(([sql]) => sql)).toEqual([
      'BEGIN IMMEDIATE',
      'COMMIT',
    ]);
    const sql = database.runAsync.mock.calls.map(([statement]) => statement).join('\n');
    expect(sql).toContain("state = 'retryable'");
    expect(sql).toContain("state = 'rejected'");
    expect(sql).toContain('ROW_NUMBER() OVER');
    expect(sql).toContain('PARTITION BY trip_id');
    expect(sql).toContain('DELETE FROM attendance_scan_receipts');
    expect(sql).toContain("offline_document_jobs\n        WHERE account_namespace = ? AND state = 'blocked'");
    expect(sql).toContain('DELETE FROM local_roster_cursors');
    expect(sql).toContain("my_photos_downloads\n               WHERE account_namespace = ? AND state = 'removed'");
    expect(sql).toContain('PARTITION BY trip_id, passenger_id');
    expect(sql).toContain("batch.state IN ('completed', 'cancelled', 'failed')");
    expect(sql).toContain('NOT EXISTS');
    expect(sql).not.toContain("state = 'completed'\n            ) ranked");
    expect(JSON.stringify(database.runAsync.mock.calls)).not.toContain('DELETE FROM pending_actions\n        WHERE account_namespace = ? AND state IN');
    for (const call of database.runAsync.mock.calls) {
      if (call.some((value) => value === 'agency.account-a')) continue;
      expect(String(call[0])).toContain('local_roster_cursors');
    }
    expect(mockedRecordStorageMaintenance).toHaveBeenCalledWith(
      expect.any(Number),
      11,
      'success',
    );
  });

  test('skips every attendance mutation when trusted time is unavailable', async () => {
    const database = databaseHarness();
    await applyAccountStorageRetention(
      database as never,
      'agency.account-a',
      {
        maintenanceNowMs: Date.parse('2040-06-01T00:00:00.000Z'),
        trustedAttendanceNowMs: null,
      },
    );

    const sql = database.runAsync.mock.calls.map(([statement]) => statement).join('\n');
    expect(sql).not.toContain("action_type = 'attendance.scan'");
    expect(sql).not.toContain('attendance_scan_receipts');
    expect(sql).toContain('offline_document_jobs');
    expect(sql).toContain('local_roster_cursors');
    expect(sql).toContain('my_photos_downloads');
    expect(mockedRecordStorageMaintenance).toHaveBeenCalledWith(
      expect.any(Number),
      5,
      'success',
    );
  });

  test('rolls back and preserves the original native failure', async () => {
    const database = databaseHarness(3);
    await expect(applyAccountStorageRetention(
      database as never,
      'agency.account-a',
      {
        maintenanceNowMs: Date.parse('2030-06-01T00:00:00.000Z'),
        trustedAttendanceNowMs: Date.parse('2030-06-01T00:00:00.000Z'),
      },
    )).rejects.toThrow('native write failed');

    expect(database.execAsync.mock.calls.map(([sql]) => sql)).toEqual([
      'BEGIN IMMEDIATE',
      'ROLLBACK',
    ]);
    expect(mockedRecordStorageMaintenance).toHaveBeenCalledWith(
      expect.any(Number),
      0,
      'failure',
    );
  });
});
