import {
  acknowledgeVaultEvictionTombstones,
  detachVaultQuotaCandidates,
  markOfflineFileOpened,
  MAX_VAULT_QUOTA_CANDIDATES,
  queryVaultEvictionTombstones,
  queryVaultQuotaCandidates,
} from '../vault-quota-database';

const ACCOUNT = 'agency.account-a';
const TRIP = '11111111-1111-4111-8111-111111111111';
const DOCUMENT = '22222222-2222-4222-8222-222222222222';
const CHECKSUM = 'a'.repeat(64);

function candidate() {
  return {
    encryptedUri: 'file:///vault/document.1.gcv',
    namespace: ACCOUNT,
    tripId: TRIP,
    documentId: DOCUMENT,
    version: 1,
    checksumSha256: CHECKSUM,
    encryptedSizeBytes: 1_024,
    retentionClass: 'evictable' as const,
    downloadedAtMs: Date.parse('2030-01-01T00:00:00.000Z'),
    lastOpenedAtMs: Date.parse('2030-02-01T00:00:00.000Z'),
    protectedFromEviction: false,
  };
}

describe('vault quota registration store', () => {
  test('returns a bounded LRU catalog that excludes every protected/current trip in SQL', async () => {
    const database = {
      getAllAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => [{
        encrypted_path: candidate().encryptedUri,
        account_namespace: ACCOUNT,
        trip_id: TRIP,
        document_id: DOCUMENT,
        version: 1,
        checksum_sha256: CHECKSUM,
        encrypted_size_bytes: 1_024,
        downloaded_at: '2030-01-01T00:00:00.000Z',
        last_opened_at: '2030-02-01T00:00:00.000Z',
      }]),
    };
    const rows = await queryVaultQuotaCandidates(
      database as never,
      ACCOUNT,
      ['current-trip', 'background-download-trip', 'current-trip'],
    );

    expect(rows).toEqual([candidate()]);
    const [sql, ...parameters] = database.getAllAsync.mock.calls[0]!;
    expect(sql).toContain("retention_class = 'evictable'");
    expect(sql).toContain('trip_id NOT IN (?, ?)');
    expect(sql).toContain('ORDER BY COALESCE(last_opened_at, downloaded_at)');
    expect(sql).toContain(`LIMIT ${MAX_VAULT_QUOTA_CANDIDATES}`);
    expect(parameters).toEqual([ACCOUNT, 'current-trip', 'background-download-trip']);
  });

  test('fails closed instead of evicting when persisted LRU metadata is malformed', async () => {
    const database = {
      getAllAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => [{
        encrypted_path: candidate().encryptedUri,
        account_namespace: ACCOUNT,
        trip_id: TRIP,
        document_id: DOCUMENT,
        version: 1,
        checksum_sha256: CHECKSUM,
        encrypted_size_bytes: 1_024,
        downloaded_at: 'not-a-date',
        last_opened_at: null,
      }]),
    };
    await expect(queryVaultQuotaCandidates(database as never, ACCOUNT, [])).rejects.toThrow(
      'download timestamp is invalid',
    );
  });

  test('writes a durable tombstone before detaching each exact evictable registration', async () => {
    const database = {
      runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
        changes: 1,
        lastInsertRowId: 0,
      })),
    };
    await detachVaultQuotaCandidates(
      database as never,
      ACCOUNT,
      [candidate()],
      '2030-03-01T00:00:00.000Z',
    );

    expect(database.runAsync).toHaveBeenCalledTimes(2);
    expect(database.runAsync.mock.calls[0]?.[0]).toContain(
      'INSERT INTO vault_eviction_tombstones',
    );
    expect(database.runAsync.mock.calls[1]?.[0]).toContain('DELETE FROM offline_files');
    expect(database.runAsync.mock.calls[1]?.[0]).toContain("retention_class = 'evictable'");
  });

  test('rejects a stale detach so its enclosing transaction can roll back the tombstone', async () => {
    const database = {
      runAsync: jest.fn()
        .mockResolvedValueOnce({ changes: 1, lastInsertRowId: 0 })
        .mockResolvedValueOnce({ changes: 0, lastInsertRowId: 0 }),
    };
    await expect(detachVaultQuotaCandidates(
      database as never,
      ACCOUNT,
      [candidate()],
      '2030-03-01T00:00:00.000Z',
    )).rejects.toThrow('changed before it could be detached');
  });

  test('recovers tombstones idempotently and records successful decrypt access separately', async () => {
    const database = {
      getAllAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => [{
        encrypted_path: candidate().encryptedUri,
        account_namespace: ACCOUNT,
        trip_id: TRIP,
        document_id: DOCUMENT,
        version: 1,
        checksum_sha256: CHECKSUM,
        encrypted_size_bytes: 1_024,
        downloaded_at: '2030-01-01T00:00:00.000Z',
        last_opened_at: null,
        attempt_count: 2,
      }]),
      runAsync: jest.fn(async (_sql: string, ..._parameters: unknown[]) => ({
        changes: 1,
        lastInsertRowId: 0,
      })),
    };
    const tombstones = await queryVaultEvictionTombstones(database as never, ACCOUNT);
    expect(tombstones[0]).toMatchObject({ attemptCount: 2, retentionClass: 'evictable' });

    await acknowledgeVaultEvictionTombstones(database as never, ACCOUNT, tombstones);
    await markOfflineFileOpened(database as never, {
      namespace: ACCOUNT,
      tripId: TRIP,
      documentId: DOCUMENT,
      version: 1,
      openedAtIso: '2030-03-01T00:00:00.000Z',
    });
    expect(database.runAsync.mock.calls[0]?.[0]).toContain(
      'DELETE FROM vault_eviction_tombstones',
    );
    expect(database.runAsync.mock.calls[1]?.[0]).toContain(
      'UPDATE offline_files SET last_opened_at',
    );
  });
});
