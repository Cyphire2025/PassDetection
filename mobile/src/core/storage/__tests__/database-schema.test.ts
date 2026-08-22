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
    execAsync: jest.fn(async (_sql: string) => undefined),
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

    expect(harness.database.execAsync).toHaveBeenCalledWith(
      'PRAGMA auto_vacuum = INCREMENTAL',
    );
    expect(harness.runTransaction).toHaveBeenCalledTimes(1);
    const sql = harness.committedSql[0]?.join('\n') ?? '';
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS users');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS trip_purge_tombstones');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS offline_document_jobs');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS sync_rebase_staging');
    expect(sql).toContain('CREATE VIRTUAL TABLE IF NOT EXISTS coordinator_passengers_fts USING fts5');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS local_roster_cursors');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS coordinator_roster_staging');
    expect(sql).toContain("retention_class TEXT NOT NULL DEFAULT 'required'");
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS vault_eviction_tombstones');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS storage_maintenance_state');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS sync_runtime_state');
    expect(sql).toContain("'pending', 'sending', 'retryable', 'needs_review', 'rejected'");
    expect(sql).toContain('refresh_attempt_count INTEGER NOT NULL DEFAULT 0');
    expect(sql).toContain('CREATE TRIGGER IF NOT EXISTS minimize_rejected_attendance_insert');
    expect(sql).toContain('CREATE TRIGGER IF NOT EXISTS minimize_rejected_attendance_update');
    expect(sql).toContain("AND NEW.state = 'rejected'");
    expect(sql).toContain("SET payload_json = '{}'");
    expect(sql).toContain('idx_coordinator_roster_order');
    expect(sql).toContain('roster_projection_complete INTEGER NOT NULL DEFAULT 0');
    expect(sql).toContain('attendance_token_hash TEXT');
    expect(sql).toContain('attendance_evidence_valid_until TEXT');
    expect(sql).toContain('idx_coordinator_attendance_token_lookup');
    expect(sql).toContain('CREATE TABLE IF NOT EXISTS mobile_notifications');
    expect(sql).toContain('passenger_id TEXT');
    expect(sql).toContain(`PRAGMA user_version = ${ACCOUNT_DATABASE_VERSION}`);
  });

  it('applies versions 13 through 24 as separate ordered transactions', async () => {
    const harness = migrationHarness(12);

    await expect(migrateAccountDatabase(
      harness.database as never,
      harness.runTransaction as never,
    )).resolves.toBe(true);

    expect(harness.committedSql).toHaveLength(12);
    expect(harness.committedSql.map((statements) => statements.join('\n'))).toEqual([
      expect.stringContaining('PRAGMA user_version = 13'),
      expect.stringContaining('PRAGMA user_version = 14'),
      expect.stringContaining('PRAGMA user_version = 15'),
      expect.stringContaining('PRAGMA user_version = 16'),
      expect.stringContaining('PRAGMA user_version = 17'),
      expect.stringContaining('PRAGMA user_version = 18'),
      expect.stringContaining('PRAGMA user_version = 19'),
      expect.stringContaining('PRAGMA user_version = 20'),
      expect.stringContaining('PRAGMA user_version = 21'),
      expect.stringContaining('PRAGMA user_version = 22'),
      expect.stringContaining('PRAGMA user_version = 23'),
      expect.stringContaining('PRAGMA user_version = 24'),
    ]);
    expect(harness.committedSql[0]?.join('\n')).toContain('DELETE FROM sync_cursors');
    expect(harness.committedSql[1]?.join('\n')).toContain('block_trip_insert_pending_purge');
    expect(harness.committedSql[2]?.join('\n')).toContain('offline_document_jobs');
    expect(harness.committedSql[3]?.join('\n')).toContain('ADD COLUMN passenger_id');
    expect(harness.committedSql[4]?.join('\n')).toContain('sync_rebase_staging');
    expect(harness.committedSql[5]?.join('\n')).toContain('coordinator_passengers_fts');
    expect(harness.committedSql[5]?.join('\n')).toContain("VALUES ('rebuild')");
    expect(harness.committedSql[5]?.join('\n')).toContain('coordinator_roster_staging');
    expect(harness.committedSql[6]?.join('\n')).toContain('vault_eviction_tombstones');
    expect(harness.committedSql[6]?.join('\n')).toContain('storage_maintenance_state');
    expect(harness.committedSql[7]?.join('\n')).toContain('ALTER TABLE trips ADD COLUMN timezone');
    expect(harness.committedSql[8]?.join('\n')).toContain('attendance_token_hash');
    expect(harness.committedSql[8]?.join('\n')).toContain('roster_projection_complete = 0');
    expect(harness.committedSql[9]?.join('\n')).toContain('sync_runtime_state');
    expect(harness.committedSql[10]?.join('\n')).toContain('refresh_attempt_count');
    expect(harness.committedSql[10]?.join('\n')).toContain("'needs_review'");
    expect(harness.committedSql[11]?.join('\n')).toContain(
      'minimize_rejected_attendance_update',
    );
    expect(harness.committedSql[11]?.join('\n')).toContain("SET payload_json = '{}'");
  });

  it('invalidates legacy coordinator roster trust when adding token evidence', async () => {
    const harness = migrationHarness(20);

    await expect(migrateAccountDatabase(
      harness.database as never,
      harness.runTransaction as never,
    )).resolves.toBe(true);

    expect(harness.committedSql).toHaveLength(4);
    const sql = harness.committedSql[0]?.join('\n') ?? '';
    expect(sql).toContain('attendance_token_state');
    expect(sql).toContain('DELETE FROM coordinator_roster_staging');
    expect(sql).toContain('SET roster_version = -1, roster_projection_complete = 0');
    expect(sql).toContain('PRAGMA user_version = 21');
    expect(harness.committedSql[1]?.join('\n')).toContain('PRAGMA user_version = 22');
    expect(harness.committedSql[2]?.join('\n')).toContain('PRAGMA user_version = 23');
    expect(harness.committedSql[3]?.join('\n')).toContain('PRAGMA user_version = 24');
  });

  it('adds terminal attendance minimization without changing reviewable states', async () => {
    const harness = migrationHarness(23);

    await expect(migrateAccountDatabase(
      harness.database as never,
      harness.runTransaction as never,
    )).resolves.toBe(true);

    expect(harness.committedSql).toHaveLength(1);
    const sql = harness.committedSql[0]?.join('\n') ?? '';
    expect(sql).toContain("WHERE action_type = 'attendance.scan'");
    expect(sql).toContain("AND state = 'rejected'");
    expect(sql).toContain("AND NEW.state = 'rejected'");
    expect(sql).not.toContain("NEW.state = 'needs_review'");
    expect(sql).toContain('PRAGMA user_version = 24');
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
