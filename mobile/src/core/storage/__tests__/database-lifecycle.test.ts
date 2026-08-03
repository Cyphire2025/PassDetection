const mockOpenDatabaseAsync = jest.fn<Promise<unknown>, [string, { useNewConnection?: boolean }?]>();
const mockDeleteDatabaseAsync = jest.fn<Promise<void>, [string]>(async (_name) => undefined);
const mockDigestStringAsync = jest.fn<Promise<string>, [string, string]>(
  async (_algorithm, value) => digest(value),
);
type MockDatabaseHealthMarker = {
  formatVersion: 1;
  state: 'clean' | 'dirty';
  schemaVersion: number;
  lastIntegrityCheckAtMs: number;
};
const mockHealthMarkers = new Map<string, MockDatabaseHealthMarker>();
const mockGetDatabaseHealthMarker = jest.fn(
  async (namespace: string): Promise<MockDatabaseHealthMarker | null> => (
    mockHealthMarkers.get(namespace) ?? null
  ),
);
const mockSetDatabaseHealthMarker = jest.fn(
  async (namespace: string, marker: MockDatabaseHealthMarker): Promise<void> => {
    mockHealthMarkers.set(namespace, { ...marker });
  },
);
const mockClearDatabaseHealthMarker = jest.fn(async (namespace: string): Promise<void> => {
  mockHealthMarkers.delete(namespace);
});

function digest(value: string): string {
  const marker = Array.from(value).reduce(
    (total, character) => total + character.charCodeAt(0),
    0,
  );
  return marker.toString(16).padEnd(64, '0');
}

jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA256' },
  digestStringAsync: (algorithm: string, value: string) => mockDigestStringAsync(algorithm, value),
}));

jest.mock('expo-file-system', () => {
  const entries: (MockFile | MockDirectory)[] = [];
  const deletedUris: string[] = [];
  const uriFor = (...parts: unknown[]) => {
    const encoded = parts.map((part) => (
      typeof part === 'object' && part !== null && 'uri' in part
        ? String((part as { uri: string }).uri)
        : String(part)
    ));
    return encoded.reduce((current, part) => (
      current ? `${current.replace(/\/$/, '')}/${part.replace(/^\//, '')}` : part
    ), '');
  };
  class MockFile {
    readonly name: string;
    readonly uri: string;
    exists = true;

    constructor(...parts: unknown[]) {
      this.uri = uriFor(...parts);
      this.name = this.uri.slice(this.uri.lastIndexOf('/') + 1);
    }

    delete() {
      this.exists = false;
      deletedUris.push(this.uri);
    }
  }
  class MockDirectory {
    readonly name: string;
    readonly uri: string;
    exists = true;

    constructor(...parts: unknown[]) {
      this.uri = uriFor(...parts);
      this.name = this.uri.slice(this.uri.lastIndexOf('/') + 1);
    }

    list() {
      return entries;
    }
  }
  return {
    Directory: MockDirectory,
    File: MockFile,
    __mockDatabaseDirectoryEntries: entries,
    __mockDeletedDatabaseUris: deletedUris,
  };
});

jest.mock('expo-sqlite', () => ({
  defaultDatabaseDirectory: '/sqlite',
  openDatabaseAsync: (name: string, options?: { useNewConnection?: boolean }) => (
    mockOpenDatabaseAsync(name, options)
  ),
  deleteDatabaseAsync: (name: string) => mockDeleteDatabaseAsync(name),
}));

jest.mock('../secure-store', () => ({
  clearDatabaseHealthMarker: (namespace: string) => mockClearDatabaseHealthMarker(namespace),
  getDatabaseHealthMarker: (namespace: string) => mockGetDatabaseHealthMarker(namespace),
  getOrCreateSecret: jest.fn(async () => 'a'.repeat(64)),
  setDatabaseHealthMarker: (namespace: string, marker: MockDatabaseHealthMarker) => (
    mockSetDatabaseHealthMarker(namespace, marker)
  ),
}));

// eslint-disable-next-line import/first -- Install native module mocks before loading the singleton.
import {
  closeAccountDatabase,
  deleteAllManagedAccountDatabases,
  deleteAccountDatabase,
  OfflineDatabaseIntegrityError,
  openAccountDatabase,
  withAccountTransaction,
} from '../database';

type MockDatabaseFileSystem = {
  Directory: new (...parts: unknown[]) => { readonly name: string; readonly uri: string };
  File: new (...parts: unknown[]) => {
    readonly name: string;
    readonly uri: string;
    exists: boolean;
    delete: () => void;
  };
  __mockDatabaseDirectoryEntries: unknown[];
  __mockDeletedDatabaseUris: string[];
};

function databaseFileSystem(): MockDatabaseFileSystem {
  return jest.requireMock('expo-file-system') as MockDatabaseFileSystem;
}

type Deferred = {
  promise: Promise<void>;
  resolve: () => void;
};

type RunResult = { changes: number; lastInsertRowId: number };

type FakeDatabase = {
  closeAsync: jest.Mock<Promise<void>, []>;
  execAsync: jest.Mock<Promise<void>, [string]>;
  getFirstAsync: jest.Mock<Promise<Record<string, unknown> | null>, [string, ...unknown[]]>;
  runAsync: jest.Mock<Promise<RunResult>, [string, ...unknown[]]>;
};

function deferred(): Deferred {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function fakeDatabase(userVersion = 16): FakeDatabase {
  return {
    closeAsync: jest.fn(async () => undefined),
    execAsync: jest.fn(async (_sql: string) => undefined),
    getFirstAsync: jest.fn(async (sql: string) => {
      if (sql === 'PRAGMA quick_check(1)') return { quick_check: 'ok' };
      if (sql.includes("name = 'pending_actions'")) return { table_exists: 1 };
      if (sql === 'SELECT COUNT(*) AS count FROM pending_actions') return { count: 0 };
      if (sql === 'PRAGMA user_version') return { user_version: userVersion };
      return null;
    }),
    runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
      changes: 1,
      lastInsertRowId: 1,
    })),
  };
}

function queueAccountConnections(
  database: FakeDatabase,
  transactionDatabase: FakeDatabase,
): void {
  mockOpenDatabaseAsync
    .mockResolvedValueOnce(database)
    .mockResolvedValueOnce(transactionDatabase);
}

beforeEach(async () => {
  await closeAccountDatabase();
  mockOpenDatabaseAsync.mockReset();
  mockDeleteDatabaseAsync.mockClear();
  mockDigestStringAsync.mockClear();
  mockGetDatabaseHealthMarker.mockClear();
  mockSetDatabaseHealthMarker.mockClear();
  mockClearDatabaseHealthMarker.mockClear();
  mockHealthMarkers.clear();
  databaseFileSystem().__mockDatabaseDirectoryEntries.length = 0;
  databaseFileSystem().__mockDeletedDatabaseUris.length = 0;
});

afterAll(async () => {
  await closeAccountDatabase();
});

test('installation reset deletes exact GC databases and sidecars while preserving unrelated files', async () => {
  const fs = databaseFileSystem();
  const hash = 'a'.repeat(32);
  const main = new fs.File('file:///sqlite', `gc_${hash}.db`);
  const wal = new fs.File('file:///sqlite', `gc_${hash}.db-wal`);
  const orphan = new fs.File('file:///sqlite', `gc_${'b'.repeat(32)}.db-shm`);
  const unrelated = new fs.File('file:///sqlite', 'user-owned.db');
  const lookalike = new fs.File('file:///sqlite', `gc_${hash}.db.backup`);
  const unrelatedDirectory = new fs.Directory('file:///sqlite', `gc_${hash}.db`);
  fs.__mockDatabaseDirectoryEntries.push(
    main,
    wal,
    orphan,
    unrelated,
    lookalike,
    unrelatedDirectory,
  );

  await expect(deleteAllManagedAccountDatabases()).resolves.toBeUndefined();

  expect(mockDeleteDatabaseAsync).toHaveBeenCalledWith(`gc_${hash}.db`);
  expect(new Set(fs.__mockDeletedDatabaseUris)).toEqual(new Set([
    main.uri,
    wal.uri,
    orphan.uri,
  ]));
  expect(unrelated.exists).toBe(true);
  expect(lookalike.exists).toBe(true);
});

test('prevalidates every managed database path before deleting any artifact', async () => {
  const fs = databaseFileSystem();
  const first = new fs.File('file:///sqlite', `gc_${'a'.repeat(32)}.db`);
  const escaped = new fs.File('file:///sqlite', `gc_${'b'.repeat(32)}.db-wal`);
  Object.defineProperty(escaped, 'uri', {
    configurable: true,
    value: `file:///outside/gc_${'b'.repeat(32)}.db-wal`,
  });
  fs.__mockDatabaseDirectoryEntries.push(first, escaped);

  await expect(deleteAllManagedAccountDatabases()).rejects.toThrow(
    'A managed database artifact escaped its private directory.',
  );

  expect(mockDeleteDatabaseAsync).not.toHaveBeenCalled();
  expect(fs.__mockDeletedDatabaseUris).toEqual([]);
  expect(first.exists).toBe(true);
});

test('coalesces concurrent startup calls onto one main and one keyed transaction connection', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  const opening = deferred();
  mockOpenDatabaseAsync
    .mockImplementationOnce(async () => {
      await opening.promise;
      return database;
    })
    .mockResolvedValueOnce(transactionDatabase);

  const first = openAccountDatabase('agency.passenger');
  const second = openAccountDatabase('agency.passenger');
  opening.resolve();

  await expect(Promise.all([first, second])).resolves.toEqual([database, database]);
  expect(mockOpenDatabaseAsync).toHaveBeenCalledTimes(2);
  expect(mockOpenDatabaseAsync).toHaveBeenNthCalledWith(2, expect.any(String), {
    useNewConnection: true,
  });
  expect(database.getFirstAsync.mock.calls.filter(([sql]) => sql === 'PRAGMA user_version')).toHaveLength(1);
  expect(database.getFirstAsync.mock.calls.filter(([sql]) => sql === 'PRAGMA quick_check(1)')).toHaveLength(1);
  expect(transactionDatabase.execAsync).toHaveBeenCalledWith(
    expect.stringContaining('PRAGMA key'),
  );
});

test('skips the periodic integrity walk after a verified clean close', async () => {
  const firstDatabase = fakeDatabase();
  const firstTransactionDatabase = fakeDatabase();
  queueAccountConnections(firstDatabase, firstTransactionDatabase);

  await openAccountDatabase('agency.clean-reopen');
  await closeAccountDatabase();

  expect(mockHealthMarkers.get('agency.clean-reopen')).toMatchObject({
    state: 'clean',
    schemaVersion: 16,
  });

  const reopenedDatabase = fakeDatabase();
  const reopenedTransactionDatabase = fakeDatabase();
  queueAccountConnections(reopenedDatabase, reopenedTransactionDatabase);
  await openAccountDatabase('agency.clean-reopen');

  expect(reopenedDatabase.getFirstAsync.mock.calls.filter(
    ([sql]) => sql === 'PRAGMA quick_check(1)',
  )).toHaveLength(0);
});

test('validates after an unclean shutdown marker', async () => {
  mockHealthMarkers.set('agency.dirty-restart', {
    formatVersion: 1,
    state: 'dirty',
    schemaVersion: 16,
    lastIntegrityCheckAtMs: Date.now(),
  });
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase('agency.dirty-restart');

  expect(database.getFirstAsync.mock.calls.filter(
    ([sql]) => sql === 'PRAGMA quick_check(1)',
  )).toHaveLength(1);
});

test.each([
  ['a stale periodic marker', {
    formatVersion: 1 as const,
    state: 'clean' as const,
    schemaVersion: 16,
    lastIntegrityCheckAtMs: Date.now() - (8 * 24 * 60 * 60 * 1_000),
  }],
  ['a marker for an older schema', {
    formatVersion: 1 as const,
    state: 'clean' as const,
    schemaVersion: 15,
    lastIntegrityCheckAtMs: Date.now(),
  }],
])('validates when opening with %s', async (_description, marker) => {
  const namespace = `agency.policy-${marker.schemaVersion}-${marker.lastIntegrityCheckAtMs}`;
  mockHealthMarkers.set(namespace, marker);
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase(namespace);

  expect(database.getFirstAsync.mock.calls.filter(
    ([sql]) => sql === 'PRAGMA quick_check(1)',
  )).toHaveLength(1);
});

test('rechecks integrity after migration even when a clean marker skips the initial walk', async () => {
  const namespace = 'agency.migration-health';
  mockHealthMarkers.set(namespace, {
    formatVersion: 1,
    state: 'clean',
    schemaVersion: 16,
    lastIntegrityCheckAtMs: Date.now(),
  });
  const database = fakeDatabase(15);
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase(namespace);

  expect(transactionDatabase.execAsync.mock.calls.flatMap(([sql]) => sql)).toEqual(
    expect.arrayContaining([expect.stringContaining('PRAGMA user_version = 16')]),
  );
  expect(database.getFirstAsync.mock.calls.filter(
    ([sql]) => sql === 'PRAGMA quick_check(1)',
  )).toHaveLength(1);
});

test('creates the current account schema with stable account and version-state indexes', async () => {
  const database = fakeDatabase(0);
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase('agency.fresh-account');

  const schemaSql = transactionDatabase.execAsync.mock.calls
    .map(([sql]) => sql)
    .join('\n');
  expect(schemaSql).toContain('account_id TEXT NOT NULL');
  expect(schemaSql).toContain('passenger_id TEXT');
  expect(schemaSql).toContain('ON users(account_namespace, account_id)');
  expect(schemaSql).toContain('itinerary_version INTEGER NOT NULL DEFAULT -1');
  expect(schemaSql).toContain('advertised_itinerary_version INTEGER NOT NULL DEFAULT 0');
  expect(schemaSql).toContain(
    'ON document_metadata(account_namespace, trip_id, scope DESC, category, display_name)',
  );
  expect(schemaSql).toContain('WHERE revoked_at IS NULL');
  expect(schemaSql).toContain('CREATE TABLE IF NOT EXISTS trip_purge_tombstones');
  expect(schemaSql).toContain('CREATE TRIGGER IF NOT EXISTS block_trip_insert_pending_purge');
  expect(schemaSql).toContain("SELECT RAISE(ABORT, 'trip purge pending')");
  expect(schemaSql).toContain('CREATE TABLE IF NOT EXISTS offline_document_jobs');
  expect(schemaSql).toContain('CREATE INDEX IF NOT EXISTS idx_offline_document_jobs_due');
  expect(schemaSql).toContain('PRAGMA user_version = 16');
});

test('migrates version 11 coordinator detail caches to the versioned payload contract', async () => {
  const database = fakeDatabase(11);
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase('agency.coordinator');

  const migrationSql = transactionDatabase.execAsync.mock.calls
    .map(([sql]) => sql)
    .join('\n');
  expect(migrationSql).toContain(
    'ALTER TABLE coordinator_passengers ADD COLUMN detail_payload_json TEXT',
  );
  expect(migrationSql).toContain(
    'ALTER TABLE coordinator_passengers ADD COLUMN detail_contract_version INTEGER',
  );
  expect(migrationSql).toContain('PRAGMA user_version = 12');
});

test('migrates version 12 trips into separate advertised and unapplied resource state', async () => {
  const database = fakeDatabase(12);
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase('agency.version-state');

  const migrationSql = transactionDatabase.execAsync.mock.calls
    .map(([sql]) => sql)
    .join('\n');
  expect(migrationSql).toContain('ALTER TABLE users ADD COLUMN account_id TEXT');
  expect(migrationSql).toContain(
    "UPDATE users SET account_id = id WHERE account_id IS NULL OR account_id = ''",
  );
  expect(migrationSql).toContain('ON users(account_namespace, account_id)');
  expect(migrationSql).toContain(
    'ALTER TABLE trips ADD COLUMN advertised_itinerary_version INTEGER NOT NULL DEFAULT 0',
  );
  expect(migrationSql).toContain(
    'advertised_personal_document_version = personal_document_version',
  );
  expect(migrationSql).toContain('itinerary_version = -1');
  expect(migrationSql).toContain('qr_version = -1');
  expect(migrationSql).toContain('DELETE FROM sync_cursors');
  expect(migrationSql).toContain(
    'ON document_metadata(account_namespace, trip_id, scope DESC, category, display_name)',
  );
  expect(migrationSql).toContain('WHERE revoked_at IS NULL');
  expect(migrationSql).toContain('PRAGMA user_version = 13');
  expect(migrationSql.indexOf('advertised_itinerary_version = itinerary_version')).toBeLessThan(
    migrationSql.indexOf('itinerary_version = -1'),
  );
});

test('migrates version 13 databases to durable trip purge tombstones', async () => {
  const database = fakeDatabase(13);
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase('agency.trip-purge-state');

  const migrationSql = transactionDatabase.execAsync.mock.calls
    .map(([sql]) => sql)
    .join('\n');
  expect(migrationSql).toContain('CREATE TABLE IF NOT EXISTS trip_purge_tombstones');
  expect(migrationSql).toContain('purge_epoch INTEGER NOT NULL DEFAULT 1');
  expect(migrationSql).toContain('CREATE INDEX IF NOT EXISTS idx_trip_purge_retry');
  expect(migrationSql).toContain('CREATE TRIGGER IF NOT EXISTS block_trip_insert_pending_purge');
  expect(migrationSql).toContain("SELECT RAISE(ABORT, 'trip purge pending')");
  expect(migrationSql).toContain('PRAGMA user_version = 14');
  expect(migrationSql).toContain('CREATE TABLE IF NOT EXISTS offline_document_jobs');
  expect(migrationSql).toContain('PRAGMA user_version = 15');
  expect(migrationSql).toContain('ALTER TABLE users ADD COLUMN passenger_id TEXT');
  expect(migrationSql).toContain('PRAGMA user_version = 16');
});

test('migrates version 14 databases to durable offline document jobs', async () => {
  const database = fakeDatabase(14);
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase('agency.document-retry-state');

  const migrationSql = transactionDatabase.execAsync.mock.calls
    .map(([sql]) => sql)
    .join('\n');
  expect(migrationSql).toContain('CREATE TABLE IF NOT EXISTS offline_document_jobs');
  expect(migrationSql).toContain("state IN ('pending', 'retryable', 'blocked')");
  expect(migrationSql).toContain('CREATE INDEX IF NOT EXISTS idx_offline_document_jobs_due');
  expect(migrationSql).toContain('PRAGMA user_version = 15');
  expect(migrationSql).toContain('ALTER TABLE users ADD COLUMN passenger_id TEXT');
  expect(migrationSql).toContain('PRAGMA user_version = 16');
});

test('migrates version 15 databases to an explicit passenger ownership boundary', async () => {
  const database = fakeDatabase(15);
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);

  await openAccountDatabase('agency.passenger-record-boundary');

  const migrationSql = transactionDatabase.execAsync.mock.calls
    .map(([sql]) => sql)
    .join('\n');
  expect(migrationSql).toContain('ALTER TABLE users ADD COLUMN passenger_id TEXT');
  expect(migrationSql).toContain('PRAGMA user_version = 16');
});

test('fails closed and preserves a corrupt account database with queued local actions', async () => {
  const database = fakeDatabase();
  database.getFirstAsync.mockImplementation(async (sql) => {
    if (sql === 'PRAGMA quick_check(1)') {
      return { quick_check: 'database disk image is malformed' };
    }
    if (sql.includes("name = 'pending_actions'")) return { table_exists: 1 };
    if (sql === 'SELECT COUNT(*) AS count FROM pending_actions') return { count: 2 };
    if (sql === 'PRAGMA user_version') return { user_version: 13 };
    return null;
  });
  mockOpenDatabaseAsync.mockResolvedValueOnce(database);

  await expect(openAccountDatabase('agency.coordinator-with-work')).rejects.toBeInstanceOf(
    OfflineDatabaseIntegrityError,
  );

  expect(database.closeAsync).toHaveBeenCalledTimes(1);
  expect(mockDeleteDatabaseAsync).not.toHaveBeenCalled();
  expect(mockOpenDatabaseAsync).toHaveBeenCalledTimes(1);
});

test('fails closed when corruption prevents proving that the local action queue is empty', async () => {
  const database = fakeDatabase();
  database.getFirstAsync.mockRejectedValue(new Error('database page is unreadable'));
  mockOpenDatabaseAsync.mockResolvedValueOnce(database);

  await expect(openAccountDatabase('agency.unreadable')).rejects.toMatchObject({
    code: 'OFFLINE_DATABASE_INTEGRITY_FAILED',
    localChangesPreserved: true,
  });

  expect(database.closeAsync).toHaveBeenCalledTimes(1);
  expect(mockDeleteDatabaseAsync).not.toHaveBeenCalled();
});

test('rebuilds only the affected account database after verifying its action queue is empty', async () => {
  const corruptDatabase = fakeDatabase();
  corruptDatabase.getFirstAsync.mockImplementation(async (sql) => {
    if (sql === 'PRAGMA quick_check(1)') return { quick_check: 'row missing from index' };
    if (sql.includes("name = 'pending_actions'")) return { table_exists: 1 };
    if (sql === 'SELECT COUNT(*) AS count FROM pending_actions') return { count: 0 };
    if (sql === 'PRAGMA user_version') return { user_version: 13 };
    return null;
  });
  const rebuiltDatabase = fakeDatabase(0);
  const rebuiltTransactionDatabase = fakeDatabase();
  mockOpenDatabaseAsync
    .mockResolvedValueOnce(corruptDatabase)
    .mockResolvedValueOnce(rebuiltDatabase)
    .mockResolvedValueOnce(rebuiltTransactionDatabase);

  await expect(openAccountDatabase('agency.safe-rebuild')).resolves.toBe(rebuiltDatabase);

  expect(corruptDatabase.closeAsync).toHaveBeenCalledTimes(1);
  expect(mockDeleteDatabaseAsync).toHaveBeenCalledTimes(1);
  expect(mockDeleteDatabaseAsync).toHaveBeenCalledWith(
    expect.stringMatching(/^gc_[0-9a-f]{32}\.db$/),
  );
  expect(rebuiltDatabase.getFirstAsync.mock.calls.filter(
    ([sql]) => sql === 'PRAGMA quick_check(1)',
  )).toHaveLength(2);
});

test('does not treat a migrated database with a missing queue table as safe to rebuild', async () => {
  const database = fakeDatabase();
  database.getFirstAsync.mockImplementation(async (sql) => {
    if (sql === 'PRAGMA quick_check(1)') return { quick_check: 'schema page is malformed' };
    if (sql.includes("name = 'pending_actions'")) return null;
    if (sql === 'PRAGMA user_version') return { user_version: 13 };
    return null;
  });
  mockOpenDatabaseAsync.mockResolvedValueOnce(database);

  await expect(openAccountDatabase('agency.missing-queue')).rejects.toBeInstanceOf(
    OfflineDatabaseIntegrityError,
  );
  expect(mockDeleteDatabaseAsync).not.toHaveBeenCalled();
});

test('refuses recovery deletion when the corrupt native connection cannot be closed', async () => {
  const database = fakeDatabase();
  database.closeAsync.mockRejectedValue(new Error('native close failed'));
  database.getFirstAsync.mockImplementation(async (sql) => {
    if (sql === 'PRAGMA quick_check(1)') return { quick_check: 'page checksum mismatch' };
    if (sql.includes("name = 'pending_actions'")) return { table_exists: 1 };
    if (sql === 'SELECT COUNT(*) AS count FROM pending_actions') return { count: 0 };
    return null;
  });
  mockOpenDatabaseAsync.mockResolvedValueOnce(database);

  await expect(openAccountDatabase('agency.close-failure')).rejects.toBeInstanceOf(
    OfflineDatabaseIntegrityError,
  );
  expect(mockDeleteDatabaseAsync).not.toHaveBeenCalled();
});

test('runs a second integrity check after migration and preserves newly detected local damage', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  let quickChecks = 0;
  database.getFirstAsync.mockImplementation(async (sql) => {
    if (sql === 'PRAGMA quick_check(1)') {
      quickChecks += 1;
      return {
        quick_check: quickChecks === 1 ? 'ok' : 'database disk image is malformed',
      };
    }
    if (sql.includes("name = 'pending_actions'")) return { table_exists: 1 };
    if (sql === 'SELECT COUNT(*) AS count FROM pending_actions') return { count: 1 };
    if (sql === 'PRAGMA user_version') return { user_version: 11 };
    return null;
  });
  queueAccountConnections(database, transactionDatabase);

  await expect(openAccountDatabase('agency.post-migration-damage')).rejects.toBeInstanceOf(
    OfflineDatabaseIntegrityError,
  );

  expect(quickChecks).toBe(2);
  expect(transactionDatabase.closeAsync).toHaveBeenCalledTimes(1);
  expect(database.closeAsync).toHaveBeenCalledTimes(1);
  expect(mockDeleteDatabaseAsync).not.toHaveBeenCalled();
});

test('an immediate close cannot overtake an open while its namespace digest is pending', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  const hashing = deferred();
  mockDigestStringAsync.mockImplementationOnce(async (_algorithm, value) => {
    await hashing.promise;
    return digest(value);
  });
  queueAccountConnections(database, transactionDatabase);

  const opening = openAccountDatabase('agency.passenger');
  const closing = closeAccountDatabase();
  hashing.resolve();

  await Promise.all([opening, closing]);
  expect(transactionDatabase.closeAsync).toHaveBeenCalledTimes(1);
  expect(database.closeAsync).toHaveBeenCalledTimes(1);
});

test('an immediate delete cannot overtake an open while its namespace digest is pending', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  const hashing = deferred();
  mockDigestStringAsync.mockImplementationOnce(async (_algorithm, value) => {
    await hashing.promise;
    return digest(value);
  });
  queueAccountConnections(database, transactionDatabase);

  const opening = openAccountDatabase('agency.passenger');
  const deleting = deleteAccountDatabase('agency.passenger');
  hashing.resolve();

  await Promise.all([opening, deleting]);
  expect(transactionDatabase.closeAsync).toHaveBeenCalledTimes(1);
  expect(database.closeAsync).toHaveBeenCalledTimes(1);
  expect(mockDeleteDatabaseAsync).toHaveBeenCalledTimes(1);
  expect(mockClearDatabaseHealthMarker).toHaveBeenCalledWith('agency.passenger');
  expect(mockHealthMarkers.has('agency.passenger')).toBe(false);
});

test('serializes 50 complete transaction lifecycles on the dedicated connection', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  let activeTransactions = 0;
  let maximumActiveTransactions = 0;
  transactionDatabase.execAsync.mockImplementation(async (sql) => {
    if (sql === 'BEGIN IMMEDIATE') {
      activeTransactions += 1;
      maximumActiveTransactions = Math.max(maximumActiveTransactions, activeTransactions);
    }
    if (sql === 'COMMIT' || sql === 'ROLLBACK') activeTransactions -= 1;
  });
  queueAccountConnections(database, transactionDatabase);
  const opened = await openAccountDatabase('agency.passenger');
  transactionDatabase.execAsync.mockClear();

  await Promise.all(
    Array.from({ length: 50 }, () => withAccountTransaction(
      opened,
      async (transaction) => {
        expect(transaction).toBe(transactionDatabase);
        await Promise.resolve();
      },
    )),
  );

  expect(maximumActiveTransactions).toBe(1);
  expect(transactionDatabase.execAsync.mock.calls.filter(([sql]) => sql === 'BEGIN IMMEDIATE')).toHaveLength(50);
  expect(database.execAsync.mock.calls.some(([sql]) => /\b(?:BEGIN|COMMIT|ROLLBACK)\b/.test(sql))).toBe(false);
});

test('a direct main-connection write cannot enter or roll back an active transaction', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  const transactionStarted = deferred();
  const finishTransaction = deferred();
  const writeUnlocked = deferred();
  const events: string[] = [];
  let transactionActive = false;

  transactionDatabase.execAsync.mockImplementation(async (sql) => {
    if (sql === 'BEGIN IMMEDIATE') {
      transactionActive = true;
      events.push('begin');
    } else if (sql === 'COMMIT' || sql === 'ROLLBACK') {
      events.push(sql.toLowerCase());
      transactionActive = false;
      writeUnlocked.resolve();
    }
  });
  database.runAsync.mockImplementation(async () => {
    if (transactionActive) await writeUnlocked.promise;
    events.push('direct-write');
    return { changes: 1, lastInsertRowId: 1 };
  });
  queueAccountConnections(database, transactionDatabase);
  const opened = await openAccountDatabase('agency.passenger');
  transactionDatabase.execAsync.mockClear();

  const transaction = withAccountTransaction(opened, async (connection) => {
    expect(connection).toBe(transactionDatabase);
    events.push('task-start');
    transactionStarted.resolve();
    await finishTransaction.promise;
    events.push('task-finish');
  });
  await transactionStarted.promise;
  let directWriteFinished = false;
  const directWrite = opened.runAsync('UPDATE direct_write SET value = 1').then(() => {
    directWriteFinished = true;
  });
  await Promise.resolve();
  expect(directWriteFinished).toBe(false);

  finishTransaction.resolve();
  await Promise.all([transaction, directWrite]);
  expect(events).toEqual(['begin', 'task-start', 'task-finish', 'commit', 'direct-write']);
  expect(database.execAsync.mock.calls.some(([sql]) => sql === 'ROLLBACK')).toBe(false);
});

test('preserves the task exception and transparently replaces a failed transaction connection', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  const replacementTransactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);
  const opened = await openAccountDatabase('agency.passenger');
  mockOpenDatabaseAsync.mockResolvedValueOnce(replacementTransactionDatabase);
  const originalError = new Error('write failed');
  const rollbackError = new Error('rollback failed');
  transactionDatabase.execAsync.mockImplementation(async (sql) => {
    if (sql === 'ROLLBACK') throw rollbackError;
  });

  const failing = withAccountTransaction(opened, async () => {
    throw originalError;
  });
  const queued = withAccountTransaction(opened, async () => undefined);

  await expect(failing).rejects.toBe(originalError);
  await expect(queued).resolves.toBeUndefined();
  expect(transactionDatabase.execAsync).toHaveBeenCalledWith('ROLLBACK');
  expect(transactionDatabase.closeAsync).toHaveBeenCalledTimes(1);
  expect(replacementTransactionDatabase.execAsync).toHaveBeenCalledWith('BEGIN IMMEDIATE');
  expect(replacementTransactionDatabase.execAsync).toHaveBeenCalledWith('COMMIT');
  expect(mockOpenDatabaseAsync).toHaveBeenLastCalledWith(expect.any(String), {
    useNewConnection: true,
  });
});

test('a failed transaction does not poison later transactions after a successful rollback', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);
  const opened = await openAccountDatabase('agency.passenger');
  const originalError = new Error('write failed');

  await expect(withAccountTransaction(opened, async () => {
    throw originalError;
  })).rejects.toBe(originalError);
  await expect(withAccountTransaction(opened, async () => undefined)).resolves.toBeUndefined();
});

test('waits for an in-flight transaction before closing both native connections', async () => {
  const database = fakeDatabase();
  const transactionDatabase = fakeDatabase();
  queueAccountConnections(database, transactionDatabase);
  const opened = await openAccountDatabase('agency.passenger');
  const transactionStarted = deferred();
  const finishTransaction = deferred();
  const transaction = withAccountTransaction(opened, async () => {
    transactionStarted.resolve();
    await finishTransaction.promise;
  });
  await transactionStarted.promise;

  const closing = closeAccountDatabase();
  await Promise.resolve();
  expect(transactionDatabase.closeAsync).not.toHaveBeenCalled();
  expect(database.closeAsync).not.toHaveBeenCalled();
  await expect(withAccountTransaction(opened, async () => undefined)).rejects.toThrow(
    'offline database is closing',
  );

  finishTransaction.resolve();
  await Promise.all([transaction, closing]);
  expect(transactionDatabase.closeAsync).toHaveBeenCalledTimes(1);
  expect(database.closeAsync).toHaveBeenCalledTimes(1);
});

test('retains account ownership when main native close fails and allows a close retry', async () => {
  const firstDatabase = fakeDatabase();
  const firstTransactionDatabase = fakeDatabase();
  const secondDatabase = fakeDatabase();
  const secondTransactionDatabase = fakeDatabase();
  const closeError = new Error('native close failed');
  firstDatabase.closeAsync
    .mockRejectedValueOnce(closeError)
    .mockResolvedValueOnce(undefined);
  queueAccountConnections(firstDatabase, firstTransactionDatabase);
  queueAccountConnections(secondDatabase, secondTransactionDatabase);

  await openAccountDatabase('agency.passenger-a');
  await expect(closeAccountDatabase()).rejects.toBe(closeError);
  expect(mockHealthMarkers.get('agency.passenger-a')?.state).toBe('dirty');
  await expect(openAccountDatabase('agency.passenger-a')).rejects.toThrow(
    'account database is closing',
  );
  await expect(openAccountDatabase('agency.passenger-b')).rejects.toThrow(
    'A different account database is already open',
  );
  expect(mockOpenDatabaseAsync).toHaveBeenCalledTimes(2);

  await expect(closeAccountDatabase()).resolves.toBeUndefined();
  expect(mockHealthMarkers.get('agency.passenger-a')?.state).toBe('clean');
  await expect(openAccountDatabase('agency.passenger-b')).resolves.toBe(secondDatabase);
  expect(firstTransactionDatabase.closeAsync).toHaveBeenCalledTimes(1);
});

test('fails closed instead of implicitly reusing connections across accounts', async () => {
  const firstDatabase = fakeDatabase();
  const firstTransactionDatabase = fakeDatabase();
  const secondDatabase = fakeDatabase();
  const secondTransactionDatabase = fakeDatabase();
  queueAccountConnections(firstDatabase, firstTransactionDatabase);
  queueAccountConnections(secondDatabase, secondTransactionDatabase);

  await openAccountDatabase('agency.passenger-a');
  await expect(openAccountDatabase('agency.passenger-b')).rejects.toThrow(
    'A different account database is already open',
  );
  expect(mockOpenDatabaseAsync).toHaveBeenCalledTimes(2);

  await closeAccountDatabase();
  await expect(openAccountDatabase('agency.passenger-b')).resolves.toBe(secondDatabase);
});
