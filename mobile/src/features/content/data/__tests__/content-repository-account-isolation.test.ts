import { ApiError, apiRequest } from '@/core/api/client';
import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import {
  discardEncryptedOfflineFile,
  downloadAndEncryptDocument,
  finalizeEncryptedOfflineFile,
  inspectRegisteredOfflineFile,
  reconcileTripVault,
  removeRegisteredOfflineFile,
} from '@/core/storage/vault';
import { captureSyncContext } from '@/core/sync/sync-context';

import type { DocumentMetadata } from '../../api/content-contracts';
import {
  cacheDocument,
  getDocument,
  localDocuments,
  prefetchPassengerOfflineDocuments,
  refreshQr,
} from '../content-repository';

jest.mock('@/core/api/client', () => {
  const actual = jest.requireActual('@/core/api/client');
  return { ...actual, apiRequest: jest.fn() };
});
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));
jest.mock('@/core/storage/vault', () => ({
  discardEncryptedOfflineFile: jest.fn(),
  deleteVaultQuotaEvictionCandidates: jest.fn(async () => undefined),
  downloadAndEncryptDocument: jest.fn(),
  finalizeEncryptedOfflineFile: jest.fn(),
  inspectRegisteredOfflineFile: jest.fn(async () => ({ status: 'valid' })),
  removeRegisteredOfflineFile: jest.fn(async () => undefined),
  isLocalOfflineCiphertextError: jest.fn((error: unknown) => (
    typeof error === 'object' && error !== null && 'code' in error
    && error.code === 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT'
  )),
  LocalOfflineCiphertextError: class LocalOfflineCiphertextError extends Error {
    readonly code = 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT';
  },
  reconcileTripVault: jest.fn(async () => undefined),
}));

const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedTransaction = jest.mocked(withAccountTransaction);
const mockedApiRequest = jest.mocked(apiRequest);
const mockedDownload = jest.mocked(downloadAndEncryptDocument);
const mockedDiscard = jest.mocked(discardEncryptedOfflineFile);
const mockedFinalize = jest.mocked(finalizeEncryptedOfflineFile);
const mockedInspectRegisteredFile = jest.mocked(inspectRegisteredOfflineFile);
const mockedReconcile = jest.mocked(reconcileTripVault);
const mockedRemoveRegisteredFile = jest.mocked(removeRegisteredOfflineFile);
const PASSENGER_RECORD_A = '33333333-3333-4333-8333-333333333333';
const PASSENGER_RECORD_B = '44444444-4444-4444-8444-444444444444';

function session(account: 'a' | 'b'): MobileSession {
  return {
    accessToken: `access-${account}`,
    accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
    refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
    sessionId: `session-${account}`,
    networkMode: 'online',
    principal: {
      id: `principal-${account}`,
      accountId: `principal-${account}`,
      principalType: 'passenger',
      agencyId: `agency-${account}`,
      passengerId: account === 'a' ? PASSENGER_RECORD_A : PASSENGER_RECORD_B,
      displayName: `Account ${account}`,
      email: null,
      phoneNumber: null,
      forcePasswordChange: false,
    },
  };
}

async function waitForCall(mock: jest.Mock): Promise<void> {
  for (let index = 0; index < 20; index += 1) {
    if (mock.mock.calls.length > 0) return;
    await Promise.resolve();
  }
  throw new Error('The expected asynchronous boundary was not reached.');
}

const document: DocumentMetadata = {
  id: '22222222-2222-4222-8222-222222222222',
  trip_id: '11111111-1111-4111-8111-111111111111',
  passenger_id: PASSENGER_RECORD_A,
  scope: 'personal',
  category: 'passport',
  display_name: 'Passport',
  content_type: 'application/pdf',
  size_bytes: 1024,
  version: 1,
  checksum_sha256: 'a'.repeat(64),
  offline_available: true,
  metadata_state: 'ready',
  updated_at: '2030-01-01T00:00:00.000Z',
  revoked_at: null,
};

describe('document vault synchronization isolation', () => {
  afterEach(() => {
    jest.clearAllMocks();
    useSessionStore.getState().clear();
  });

  it('removes Account A encrypted output and never commits it after switching to Account B', async () => {
    let resolveDownload!: (value: Awaited<ReturnType<typeof downloadAndEncryptDocument>>) => void;
    const database = {
      getFirstAsync: jest
        .fn()
        .mockResolvedValueOnce({
          id: document.id,
          account_namespace: 'agency-a.principal-a',
          trip_id: document.trip_id,
          scope: document.scope,
          category: document.category,
          content_type: document.content_type,
          size_bytes: document.size_bytes,
          version: document.version,
          checksum_sha256: document.checksum_sha256,
          offline_available: 1,
          metadata_state: 'ready',
        })
        .mockResolvedValueOnce(null),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDownload.mockReturnValueOnce(new Promise((resolve) => {
      resolveDownload = resolve;
    }));

    useSessionStore.getState().setSession(session('a'));
    const lease = captureSyncContext();
    const caching = cacheDocument(document, lease.context);
    await waitForCall(mockedDownload as jest.Mock);

    useSessionStore.getState().setSession(session('b'));
    const encrypted = {
      uri: 'private://agency-a/encrypted-passport.bin',
      checksumSha256: 'a'.repeat(64),
      contentType: 'application/pdf',
      plaintextSizeBytes: 1024,
      encryptedSizeBytes: 1088,
      writeLeaseId: 'lease-a',
    };
    resolveDownload(encrypted);

    await expect(caching).rejects.toMatchObject({ code: 'SYNC_CONTEXT_CHANGED' });
    expect(mockedTransaction).not.toHaveBeenCalled();
    expect(mockedDiscard).toHaveBeenCalledWith(encrypted, undefined);
    expect(mockedOpenDatabase).toHaveBeenCalledWith('agency-a.principal-a');
    expect(mockedOpenDatabase).not.toHaveBeenCalledWith('agency-b.principal-b');
    lease.release();
  });

  it('preserves the registered ciphertext when replacement registration rolls back', async () => {
    const previousUri = 'private://agency-a/trip/registered-old.gcv';
    const encrypted = {
      uri: 'private://agency-a/trip/candidate-new.gcv',
      checksumSha256: 'a'.repeat(64),
      contentType: 'application/pdf',
      plaintextSizeBytes: 1024,
      encryptedSizeBytes: 1088,
      writeLeaseId: 'candidate-lease',
    };
    const database = {
      getFirstAsync: jest
        .fn()
        .mockResolvedValueOnce({
          id: document.id,
          account_namespace: 'agency-a.principal-a',
          trip_id: document.trip_id,
          scope: document.scope,
          category: document.category,
          content_type: document.content_type,
          size_bytes: document.size_bytes,
          version: document.version,
          checksum_sha256: document.checksum_sha256,
          offline_available: 1,
          metadata_state: 'ready',
        })
        .mockResolvedValueOnce({
          version: document.version - 1,
          checksum_sha256: 'b'.repeat(64),
          encrypted_path: previousUri,
        }),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDownload.mockResolvedValue(encrypted);
    mockedTransaction.mockRejectedValue(new Error('transaction rolled back'));
    useSessionStore.getState().setSession(session('a'));

    await expect(cacheDocument(document)).rejects.toThrow('transaction rolled back');

    expect(mockedDiscard).toHaveBeenCalledWith(encrypted, previousUri);
    expect(mockedFinalize).not.toHaveBeenCalled();
    expect(mockedReconcile).not.toHaveBeenCalled();
  });

  it('repairs a missing registered file and publishes it before orphan reconciliation', async () => {
    const missingRegisteredUri = 'private://agency-a/trip/registered-new.gcv';
    const encrypted = {
      uri: missingRegisteredUri,
      checksumSha256: 'a'.repeat(64),
      contentType: 'application/pdf',
      plaintextSizeBytes: 1024,
      encryptedSizeBytes: 1088,
      writeLeaseId: 'committed-lease',
    };
    const transactionDatabase = {
      runAsync: jest.fn().mockResolvedValue({ changes: 1 }),
    };
    const database = {
      getFirstAsync: jest
        .fn()
        .mockResolvedValueOnce({
          id: document.id,
          account_namespace: 'agency-a.principal-a',
          trip_id: document.trip_id,
          scope: document.scope,
          category: document.category,
          content_type: document.content_type,
          size_bytes: document.size_bytes,
          version: document.version,
          checksum_sha256: document.checksum_sha256,
          offline_available: 1,
          metadata_state: 'ready',
        })
        .mockResolvedValueOnce({
          version: document.version,
          checksum_sha256: document.checksum_sha256,
          encrypted_path: missingRegisteredUri,
        }),
      getAllAsync: jest.fn().mockResolvedValue([{ encrypted_path: encrypted.uri }]),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedInspectRegisteredFile.mockResolvedValueOnce({ status: 'missing' });
    mockedDownload.mockResolvedValue(encrypted);
    mockedTransaction.mockImplementation(async (_database, task) => {
      await task(transactionDatabase as never);
    });
    useSessionStore.getState().setSession(session('a'));

    await cacheDocument(document);

    expect(mockedInspectRegisteredFile).toHaveBeenCalledWith(
      expect.objectContaining({
        namespace: 'agency-a.principal-a',
        tripId: document.trip_id,
        documentId: document.id,
        encryptedUri: missingRegisteredUri,
      }),
      undefined,
    );
    expect(mockedFinalize).toHaveBeenCalledWith(encrypted);
    expect(mockedReconcile).toHaveBeenCalledWith(
      'agency-a.principal-a',
      document.trip_id,
      [encrypted.uri],
    );
    expect(mockedFinalize.mock.invocationCallOrder[0]!).toBeLessThan(
      mockedReconcile.mock.invocationCallOrder[0]!,
    );
    expect(mockedDiscard).not.toHaveBeenCalled();
    const registrationCall = transactionDatabase.runAsync.mock.calls.find(
      ([sql]) => String(sql).includes('INSERT INTO offline_files'),
    );
    expect(registrationCall).toBeDefined();
    expect(registrationCall![registrationCall!.length - 1]).toBe('evictable');
  });

  it.each(['bit-flipped', 'truncated'])(
    'unregisters, requeues, and redownloads a %s registered ciphertext',
    async () => {
    const corruptUri = `private://agency-a/trip/${document.id}.${document.version}.${document.checksum_sha256}.gcv`;
    const encrypted = {
      uri: corruptUri,
      checksumSha256: document.checksum_sha256!,
      contentType: document.content_type,
      plaintextSizeBytes: document.size_bytes!,
      encryptedSizeBytes: 1088,
      writeLeaseId: 'repair-lease',
    };
    const transactionDatabase = {
      runAsync: jest.fn().mockResolvedValue({ changes: 1 }),
    };
    const database = {
      getFirstAsync: jest
        .fn()
        .mockResolvedValueOnce({
          id: document.id,
          account_namespace: 'agency-a.principal-a',
          trip_id: document.trip_id,
          scope: document.scope,
          category: document.category,
          content_type: document.content_type,
          size_bytes: document.size_bytes,
          version: document.version,
          checksum_sha256: document.checksum_sha256,
          offline_available: 1,
          metadata_state: 'ready',
        })
        .mockResolvedValueOnce({
          version: document.version,
          checksum_sha256: document.checksum_sha256,
          encrypted_path: corruptUri,
        }),
      getAllAsync: jest.fn().mockResolvedValue([{ encrypted_path: corruptUri }]),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedInspectRegisteredFile.mockResolvedValueOnce({ status: 'corrupt' });
    mockedDownload.mockResolvedValue(encrypted);
    mockedTransaction.mockImplementation(async (_database, task) => {
      await task(transactionDatabase as never);
    });
    useSessionStore.getState().setSession(session('a'));

    await cacheDocument(document);

    expect(transactionDatabase.runAsync).toHaveBeenCalledWith(
      expect.stringContaining('DELETE FROM offline_files'),
      document.id,
      'agency-a.principal-a',
      document.trip_id,
      document.version,
      document.checksum_sha256,
      corruptUri,
    );
    expect(transactionDatabase.runAsync).toHaveBeenCalledWith(
      expect.stringContaining('INSERT INTO offline_document_jobs'),
      document.id,
      'agency-a.principal-a',
      document.trip_id,
      document.version,
      'LOCAL_CIPHERTEXT_CORRUPT',
      expect.any(String),
      expect.any(String),
    );
    expect(mockedRemoveRegisteredFile).toHaveBeenCalledWith(expect.objectContaining({
      encryptedUri: corruptUri,
      checksumSha256: document.checksum_sha256,
    }));
    expect(mockedDownload).toHaveBeenCalledTimes(1);
    expect(mockedRemoveRegisteredFile.mock.invocationCallOrder[0]!).toBeLessThan(
      mockedDownload.mock.invocationCallOrder[0]!,
    );
      expect(mockedFinalize).toHaveBeenCalledWith(encrypted);
    },
  );

  it('binds passenger document lookup to account, selected trip, and authoritative passenger record', async () => {
    const database = { getFirstAsync: jest.fn().mockResolvedValue(null) };
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));

    await expect(getDocument(document.trip_id, document.id)).resolves.toBeNull();

    const [statement, ...parameters] = database.getFirstAsync.mock.calls[0]!;
    expect(statement).toContain('d.account_namespace = ?');
    expect(statement).toContain('d.trip_id = ?');
    expect(statement).toContain("d.scope = 'personal' AND d.passenger_id = ?");
    expect(statement).toContain('f.trip_id = d.trip_id');
    expect(parameters).toEqual([
      'agency-a.principal-a',
      document.trip_id,
      PASSENGER_RECORD_A,
      document.id,
    ]);
  });

  it('fails closed when a rolling deployment has not supplied the passenger record boundary', async () => {
    const legacy = session('a');
    legacy.principal.passengerId = null;
    useSessionStore.getState().setSession(legacy);

    await expect(getDocument(document.trip_id, document.id)).rejects.toThrow(
      'passenger ownership boundary is unavailable',
    );
    expect(mockedOpenDatabase).toHaveBeenCalledWith('agency-a.principal-a');
  });

  it('filters cached document lists by the selected passenger record', async () => {
    const database = {
      getAllAsync: jest.fn().mockResolvedValue([]),
      getFirstAsync: jest.fn().mockResolvedValue(null),
      runAsync: jest.fn(),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));

    await expect(localDocuments(document.trip_id, undefined, 'personal')).resolves.toEqual([]);

    const [statement, ...parameters] = database.getAllAsync.mock.calls[0]!;
    expect(statement).toContain("d.scope = 'personal' AND d.passenger_id = ?");
    expect(parameters).toEqual([
      'agency-a.principal-a',
      document.trip_id,
      PASSENGER_RECORD_A,
      'personal',
    ]);
  });

  it('rejects a cached personal document owned by another passenger before download', async () => {
    useSessionStore.getState().setSession(session('a'));

    await expect(cacheDocument({ ...document, passenger_id: PASSENGER_RECORD_B })).rejects.toThrow(
      'does not belong to the active passenger',
    );
    expect(mockedDownload).not.toHaveBeenCalled();
  });

  it('removes a document and encrypted registration after authoritative download withdrawal', async () => {
    const transactionDatabase = {
      runAsync: jest.fn().mockResolvedValue({ changes: 1, lastInsertRowId: 0 }),
    };
    const database = {
      getFirstAsync: jest
        .fn()
        .mockResolvedValueOnce({
          id: document.id,
          account_namespace: 'agency-a.principal-a',
          trip_id: document.trip_id,
          scope: document.scope,
          category: document.category,
          content_type: document.content_type,
          size_bytes: document.size_bytes,
          version: document.version,
          checksum_sha256: document.checksum_sha256,
          offline_available: 1,
          metadata_state: 'ready',
        })
        .mockResolvedValueOnce(null),
      getAllAsync: jest.fn().mockResolvedValue([]),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedDownload.mockRejectedValueOnce(
      new ApiError('Document was deleted.', 404, 'NOT_FOUND', null),
    );
    mockedTransaction.mockImplementation(async (_database, task) => {
      await task(transactionDatabase as never);
    });
    useSessionStore.getState().setSession(session('a'));

    await expect(cacheDocument(document, undefined, undefined, 'required')).rejects.toThrow(
      'no longer available for the selected trip',
    );

    expect(transactionDatabase.runAsync).toHaveBeenCalledWith(
      expect.stringContaining('DELETE FROM document_metadata'),
      'agency-a.principal-a',
      document.trip_id,
      document.id,
      document.version,
      PASSENGER_RECORD_A,
    );
    expect(mockedReconcile).toHaveBeenCalledWith(
      'agency-a.principal-a',
      document.trip_id,
      [],
    );
  });

  it('clears a stale QR only for an explicit domain absence, never for a missing route', async () => {
    const transactionDatabase = {
      runAsync: jest.fn().mockResolvedValue({ changes: 1, lastInsertRowId: 0 }),
    };
    const database = {};
    mockedOpenDatabase.mockResolvedValue(database as never);
    mockedTransaction.mockImplementation(async (_database, task) => {
      await task(transactionDatabase as never);
    });
    mockedApiRequest.mockRejectedValueOnce(
      new ApiError('Passenger QR was not found.', 404, 'NOT_FOUND', null),
    );
    useSessionStore.getState().setSession(session('a'));

    await expect(refreshQr(document.trip_id)).resolves.toEqual({ qr: null, offline: false });
    expect(transactionDatabase.runAsync).toHaveBeenCalledWith(
      'DELETE FROM qr_metadata WHERE account_namespace = ? AND trip_id = ?',
      'agency-a.principal-a',
      document.trip_id,
    );

    transactionDatabase.runAsync.mockClear();
    const missingRoute = new ApiError('Not Found', 404, 'HTTP_404', null);
    mockedApiRequest.mockRejectedValueOnce(missingRoute);
    await expect(refreshQr(document.trip_id)).rejects.toBe(missingRoute);
    expect(transactionDatabase.runAsync).not.toHaveBeenCalled();
  });

  it('never resolves personal documents for a client manager account', async () => {
    const manager = session('a');
    manager.principal.principalType = 'client_manager';
    const database = { getFirstAsync: jest.fn().mockResolvedValue(null) };
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(manager);

    await expect(getDocument(document.trip_id, document.id)).resolves.toBeNull();

    const [statement, ...parameters] = database.getFirstAsync.mock.calls[0]!;
    expect(statement).toContain("d.scope = 'common'");
    expect(statement).not.toContain("d.scope = 'personal'");
    expect(parameters).toEqual([
      'agency-a.principal-a',
      document.trip_id,
      document.id,
    ]);
  });

  it('fails closed for an expired trip even when its encrypted document is still cached', async () => {
    const database = {
      getFirstAsync: jest.fn().mockResolvedValue({
        ...document,
        offline: 1,
        offlineVersion: document.version,
        access_expires_at: '2020-01-01T00:00:00.000Z',
        last_server_time: '2020-01-01T00:00:00.000Z',
      }),
    };
    mockedOpenDatabase.mockResolvedValue(database as never);
    useSessionStore.getState().setSession(session('a'));

    await expect(getDocument(document.trip_id, document.id)).resolves.toBeNull();
    expect(database.getFirstAsync).toHaveBeenCalledWith(
      expect.stringContaining('JOIN trips trip'),
      'agency-a.principal-a',
      document.trip_id,
      PASSENGER_RECORD_A,
      document.id,
    );
  });

  it('persists a failed blob as a delayed job and does not retry it before it is due', async () => {
    jest.useFakeTimers();
    try {
      const retryRow = {
        ...document,
        size_bytes: document.size_bytes ?? 0,
        checksum_sha256: document.checksum_sha256 ?? '',
        offline_available: 1,
        offline: 0,
        offlineVersion: null,
        retryAttemptCount: 0,
      };
      const database = {
        getAllAsync: jest.fn()
          .mockResolvedValueOnce([retryRow])
          .mockResolvedValueOnce([]),
        getFirstAsync: jest.fn(async (sql: string) => {
          if (sql.includes('FROM document_metadata')) {
            return {
              id: document.id,
              account_namespace: 'agency-a.principal-a',
              trip_id: document.trip_id,
              scope: document.scope,
              category: document.category,
              content_type: document.content_type,
              size_bytes: document.size_bytes,
              version: document.version,
              checksum_sha256: document.checksum_sha256,
              offline_available: 1,
              metadata_state: 'ready',
            };
          }
          if (sql.includes('FROM offline_files')) return null;
          return null;
        }),
        runAsync: jest.fn(async () => ({ changes: 1, lastInsertRowId: 0 })),
      };
      mockedOpenDatabase.mockResolvedValue(database as never);
      mockedDownload.mockRejectedValue(new TypeError('network request failed'));
      useSessionStore.getState().setSession(session('a'));

      const first = prefetchPassengerOfflineDocuments(document.trip_id);
      await jest.runAllTimersAsync();
      await expect(first).resolves.toMatchObject({ total: 1, completed: 0, failed: 1 });

      expect(mockedDownload).toHaveBeenCalledTimes(3);
      expect(database.runAsync).toHaveBeenCalledWith(
        expect.stringContaining('UPDATE offline_document_jobs'),
        'retryable',
        expect.any(String),
        'DOCUMENT_TRANSFER_RETRY',
        expect.any(String),
        document.id,
        'agency-a.principal-a',
        document.trip_id,
        document.version,
      );

      const downloadCalls = mockedDownload.mock.calls.length;
      await expect(prefetchPassengerOfflineDocuments(document.trip_id)).resolves.toMatchObject({
        total: 0,
        completed: 0,
        failed: 0,
      });
      expect(mockedDownload).toHaveBeenCalledTimes(downloadCalls);
      expect(database.getAllAsync).toHaveBeenCalledWith(
        expect.stringContaining("job.state IN ('pending', 'retryable')"),
        'agency-a.principal-a',
        document.trip_id,
        0,
        expect.any(String),
        'personal',
        'common',
        PASSENGER_RECORD_A,
      );
    } finally {
      jest.useRealTimers();
    }
  });
});
