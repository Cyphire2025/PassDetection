import {
  ACCOUNT_DATABASE_VERSION,
  migrateAccountDatabase,
} from '../database-schema';

function migrationHarness(userVersion: number) {
  const transaction = {
    execAsync: jest.fn(async (_sql: string) => undefined),
  };
  const database = {
    getFirstAsync: jest.fn(async (_sql: string) => ({ user_version: userVersion })),
  };
  const committedSql: string[][] = [];
  const runTransaction = jest.fn(async (
    task: (value: typeof transaction) => Promise<void>,
  ) => {
    const firstCall = transaction.execAsync.mock.calls.length;
    await task(transaction);
    committedSql.push(
      transaction.execAsync.mock.calls.slice(firstCall).map(([sql]) => sql),
    );
  });
  return { committedSql, database, runTransaction, transaction };
}

describe('account database schema boundary', () => {
  it('creates the complete current schema in one transaction for a new account', async () => {
    const harness = migrationHarness(0);

    await expect(migrateAccountDatabase(
      harness.database as never,
      harness.runTransaction as never,
    )).resolves.toBe(true);

    expect(harness.runTransaction).toHaveBeenCalledTimes(1);
    const sql = harness.committedSql[0]?.join('\n') ?? '';
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS users');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS trip_purge_tombstones');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS offline_document_jobs');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS mobile_notifications');
    expect(sql).toContain('passenger_id TEXT');
    expect(sql).toContain(`PRAGMA user_version = ${ACCOUNT_DATABASE_VERSION}`);
  });

  it('applies versions 13 through 16 as separate ordered transactions', async () => {
    const harness = migrationHarness(12);

    await expect(migrateAccountDatabase(
      harness.database as never,
      harness.runTransaction as never,
    )).resolves.toBe(true);

    expect(harness.committedSql).toHaveLength(4);
    expect(harness.committedSql.map((statements) => statements.join('\n'))).toEqual([
      expect.stringContaining('PRAGMA user_version = 13'),
      expect.stringContaining('PRAGMA user_version = 14'),
      expect.stringContaining('PRAGMA user_version = 15'),
      expect.stringContaining('PRAGMA user_version = 16'),
    ]);
    expect(harness.committedSql[0]?.join('\n')).toContain('DELETE FROM sync_cursors');
    expect(harness.committedSql[1]?.join('\n')).toContain('block_trip_insert_pending_purge');
    expect(harness.committedSql[2]?.join('\n')).toContain('offline_document_jobs');
    expect(harness.committedSql[3]?.join('\n')).toContain('ADD COLUMN passenger_id');
  });

  it('does not write an already-current schema', async () => {
    const harness = migrationHarness(ACCOUNT_DATABASE_VERSION);

    await expect(migrateAccountDatabase(
      harness.database as never,
      harness.runTransaction as never,
    )).resolves.toBe(false);
    expect(harness.runTransaction).not.toHaveBeenCalled();
  });

  it('rejects a database created by a newer application', async () => {
    const harness = migrationHarness(ACCOUNT_DATABASE_VERSION + 1);

    await expect(migrateAccountDatabase(
      harness.database as never,
      harness.runTransaction as never,
    )).rejects.toThrow('newer application version');
    expect(harness.runTransaction).not.toHaveBeenCalled();
  });
});
