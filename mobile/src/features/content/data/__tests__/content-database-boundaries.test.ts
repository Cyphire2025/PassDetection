import type { DocumentMetadata } from '../../api/content-contracts';
import {
  mapDocumentRow,
  queryDocument,
  replaceDocumentsInTransaction,
} from '../document-database';
import {
  queryPersonalQr,
  replaceAnnouncementsInTransaction,
} from '../content-resource-database';

const document: DocumentMetadata = {
  id: '22222222-2222-4222-8222-222222222222',
  trip_id: '11111111-1111-4111-8111-111111111111',
  passenger_id: '33333333-3333-4333-8333-333333333333',
  scope: 'personal',
  category: 'passport',
  display_name: 'Passport',
  content_type: 'application/pdf',
  size_bytes: 1024,
  version: 3,
  checksum_sha256: 'a'.repeat(64),
  offline_available: true,
  metadata_state: 'ready',
  updated_at: '2030-01-01T00:00:00.000Z',
  revoked_at: null,
};

describe('document database boundary', () => {
  it('maps SQLite flags and hides incomplete pending metadata', () => {
    const readyRow = {
      ...document,
      size_bytes: 1024,
      checksum_sha256: 'a'.repeat(64),
      offline_available: 1,
      offline: 1,
      offlineVersion: 3,
    };
    expect(mapDocumentRow(readyRow)).toMatchObject({
      size_bytes: 1024,
      checksum_sha256: 'a'.repeat(64),
      offline_available: true,
      offline: true,
      offlineVersion: 3,
    });
    expect(mapDocumentRow({
      ...readyRow,
      metadata_state: 'pending',
      offline_available: 0,
      offline: 0,
      offlineVersion: null,
    })).toMatchObject({
      size_bytes: null,
      checksum_sha256: null,
      offline_available: false,
      offline: false,
      offlineVersion: null,
    });
    expect(readyRow.offline_available).toBe(1);
  });

  it('keeps account, trip, passenger, and document parameters in lookup order', async () => {
    const database = {
      getFirstAsync: jest.fn(async (_statement: string, ..._parameters: unknown[]) => ({
        ...document,
        size_bytes: 1024,
        checksum_sha256: 'a'.repeat(64),
        offline_available: 1,
        offline: 1,
        offlineVersion: 3,
        access_expires_at: '2030-02-01T00:00:00.000Z',
        last_server_time: '2030-01-01T00:00:00.000Z',
      })),
    };

    await expect(queryDocument(database as never, {
      namespace: 'agency.account',
      tripId: document.trip_id,
      documentId: document.id,
      ownership: {
        sql: "AND (d.scope = 'common' OR (d.scope = 'personal' AND d.passenger_id = ?))",
        parameters: [document.passenger_id!],
      },
    })).resolves.toMatchObject({
      document: { id: document.id, offline: true },
      accessExpiresAt: '2030-02-01T00:00:00.000Z',
      lastServerTime: '2030-01-01T00:00:00.000Z',
    });

    const [statement, ...parameters] = database.getFirstAsync.mock.calls[0]!;
    expect(statement).toContain('d.account_namespace = ?');
    expect(statement).toContain('d.trip_id = ?');
    expect(statement).toContain("d.scope = 'personal' AND d.passenger_id = ?");
    expect(parameters).toEqual([
      'agency.account',
      document.trip_id,
      document.passenger_id,
      document.id,
    ]);
  });

  it('replaces one document as a single ordered account-scoped batch', async () => {
    const transaction = {
      runAsync: jest.fn(async (_statement: string, ..._parameters: unknown[]) => ({
        changes: 1,
        lastInsertRowId: 0,
      })),
    };
    const assertActive = jest.fn();

    await replaceDocumentsInTransaction(transaction as never, {
      namespace: 'agency.account',
      tripId: document.trip_id,
      scope: 'personal',
      documents: [document],
      nowIso: '2030-01-01T00:01:00.000Z',
      assertActive,
    });

    expect(transaction.runAsync).toHaveBeenCalledTimes(4);
    expect(transaction.runAsync.mock.calls.map(([sql]) => sql)).toEqual([
      expect.stringContaining('INSERT INTO document_metadata'),
      expect.stringContaining('INSERT INTO offline_document_jobs'),
      expect.stringContaining('DELETE FROM document_metadata'),
      expect.stringContaining('DELETE FROM offline_files'),
    ]);
    expect(transaction.runAsync.mock.calls[2]?.slice(1)).toEqual([
      'agency.account',
      document.trip_id,
      'personal',
      document.id,
    ]);
    expect(transaction.runAsync.mock.calls[3]?.slice(1)).toEqual([
      'agency.account',
      document.trip_id,
    ]);
    expect(assertActive).toHaveBeenCalledTimes(3);
  });
});

describe('content resource database boundary', () => {
  it('preserves read announcements while replacing the bounded trip batch', async () => {
    const transaction = {
      getAllAsync: jest.fn(async (_statement: string, ..._parameters: unknown[]) => (
        [{ id: 'announcement-a' }]
      )),
      runAsync: jest.fn(async (_statement: string, ..._parameters: unknown[]) => ({
        changes: 1,
        lastInsertRowId: 0,
      })),
    };
    const announcements = [
      {
        id: 'announcement-a',
        trip_id: document.trip_id,
        version: 1,
        title: 'A',
        message: 'Already read',
        priority: 'normal' as const,
        published_at: '2030-01-01T00:00:00.000Z',
        available_until: null,
        is_read: false,
      },
      {
        id: 'announcement-b',
        trip_id: document.trip_id,
        version: 1,
        title: 'B',
        message: 'Server read',
        priority: 'important' as const,
        published_at: '2030-01-01T00:01:00.000Z',
        available_until: null,
        is_read: true,
      },
    ];

    await replaceAnnouncementsInTransaction(transaction as never, {
      namespace: 'agency.account',
      tripId: document.trip_id,
      announcements,
    });

    expect(transaction.runAsync).toHaveBeenCalledTimes(3);
    expect(transaction.runAsync.mock.calls[0]?.[0]).toContain('DELETE FROM announcements');
    expect(transaction.runAsync.mock.calls[1]?.at(-1)).toBe(1);
    expect(transaction.runAsync.mock.calls[2]?.at(-1)).toBe(1);
  });

  it('uses one clock boundary for both QR validity predicates', async () => {
    const database = {
      getFirstAsync: jest.fn(async (_statement: string, ..._parameters: unknown[]) => ({
        id: 'qr-id',
        passenger_id: document.passenger_id,
        signed_payload: 'signed-payload-value',
        version: 2,
        valid_from: null,
        valid_until: null,
        offline_allowed: 1,
        updated_at: '2030-01-01T00:00:00.000Z',
      })),
    };
    const nowIso = '2030-01-01T00:02:00.000Z';

    await expect(queryPersonalQr(
      database as never,
      'agency.account',
      document.trip_id,
      nowIso,
    )).resolves.toMatchObject({
      trip_id: document.trip_id,
      offline_allowed: true,
    });

    expect(database.getFirstAsync.mock.calls[0]?.slice(1)).toEqual([
      'agency.account',
      document.trip_id,
      nowIso,
      nowIso,
    ]);
  });
});
