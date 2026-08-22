import { invalidateAuthenticationBoundary, useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import {
  recordAttendanceLocalScanResult,
  recordAttendanceTerminalRejection,
} from '@/core/observability/attendance-observability';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';

import {
  attendanceSessionQueueStatus,
  attendanceTripQueueStatus,
  enqueueQrScan,
} from '../attendance-queue';
import { publishAttendanceCloseoutCheckpoint } from '../attendance-closeout-checkpoint';
import { ATTENDANCE_QUEUE_POLICY } from '../attendance-policy';
import { trustedAttendanceScanTime } from '../trusted-scan-time';

jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA256' },
  randomUUID: jest.fn(() => '44444444-4444-4444-8444-444444444444'),
  digestStringAsync: jest.fn(async (_algorithm: string, value: string) => (
    value.startsWith('pdatt:') ? 'a'.repeat(64) : 'dedupe-new'
  )),
}));
jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
  withAccountTransaction: jest.fn(),
}));
jest.mock('@/core/observability/attendance-observability', () => ({
  recordAttendanceLocalScanResult: jest.fn(),
  recordAttendanceTerminalRejection: jest.fn(),
}));
jest.mock('../attendance-closeout-checkpoint', () => ({
  publishAttendanceCloseoutCheckpoint: jest.fn(),
}));
jest.mock('../trusted-scan-time', () => ({
  trustedAttendanceScanTime: jest.fn(async () => ({
    timestampMs: Date.now(),
    deviceClockDifferenceMs: 0,
  })),
}));

const mockedOpenDatabase = jest.mocked(openAccountDatabase);
const mockedRecordAttendanceLocalScanResult = jest.mocked(recordAttendanceLocalScanResult);
const mockedRecordAttendanceTerminalRejection = jest.mocked(recordAttendanceTerminalRejection);
const mockedPublishAttendanceCloseoutCheckpoint = jest.mocked(
  publishAttendanceCloseoutCheckpoint,
);
const mockedTransaction = jest.mocked(withAccountTransaction);
const mockedTrustedScanTime = jest.mocked(trustedAttendanceScanTime);

const TRIP_ID = '11111111-1111-4111-8111-111111111111';
const SESSION_ID = '22222222-2222-4222-8222-222222222222';
const EVENT_ID = '44444444-4444-4444-8444-444444444444';
const SIGNED_QR = `pdatt:${'A'.repeat(43)}`;

const COORDINATOR_SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: 'coordinator-one',
    accountId: 'coordinator-one',
    principalType: 'coordinator',
    agencyId: 'agency-coordinator',
    displayName: 'Coordinator One',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

type StoredAction = {
  idempotency_key: string;
  state: 'pending' | 'sending' | 'retryable' | 'needs_review' | 'rejected';
};

function compactSql(sql: string): string {
  return sql.replace(/\s+/g, ' ').trim();
}

function activePayload(sessionId = SESSION_ID): { payload_json: string } {
  return {
    payload_json: JSON.stringify({
      session_id: sessionId,
      signed_qr: SIGNED_QR,
      scanned_at: '2029-01-01T00:00:00.000Z',
      source: 'qr',
    }),
  };
}

class EnqueueDatabase {
  readonly statements: string[] = [];
  insertedPayload: string | null = null;
  invalidateAuthenticationOnInsert = false;
  receipt: { client_event_id: string } | null = null;
  stored: StoredAction | null = null;
  activeRows: { payload_json: string }[] = [];
  statusRows: {
    state: 'pending' | 'sending' | 'retryable' | 'needs_review';
    count: number;
  }[] = [];
  accountCount = 0;
  rosterFence = {
    advertised_roster_version: 7,
    last_server_time: new Date(Date.now() - 2_000).toISOString(),
    role: 'coordinator',
    roster_projection_complete: 1,
    roster_version: 7,
  };
  attendanceEvidence = [{
    attendance_evidence_observed_at: new Date(Date.now() - 2_000).toISOString(),
    attendance_evidence_valid_until: new Date(Date.now() + 60 * 60_000).toISOString(),
    attendance_token_expires_at: new Date(Date.now() + 24 * 60 * 60_000).toISOString(),
    attendance_token_hash: 'a'.repeat(64),
    attendance_token_state: 'active',
    attendance_token_updated_at: new Date(Date.now() - 3_000).toISOString(),
    attendance_token_version: 1,
  }];

  async runAsync(sql: string, ...parameters: unknown[]): Promise<{ changes: number }> {
    const normalized = compactSql(sql);
    this.statements.push(normalized);
    if (normalized.startsWith('INSERT OR IGNORE INTO pending_actions')) {
      if (this.invalidateAuthenticationOnInsert) invalidateAuthenticationBoundary();
      this.insertedPayload = parameters[4] as string;
      this.stored = {
        idempotency_key: parameters[0] as string,
        state: 'pending',
      };
      return { changes: 1 };
    }
    return { changes: 0 };
  }

  async getFirstAsync<T>(sql: string): Promise<T | null> {
    const normalized = compactSql(sql);
    if (normalized.includes('FROM trips trip')) return this.rosterFence as T;
    if (normalized.includes('FROM attendance_scan_receipts')) return this.receipt as T | null;
    if (normalized.includes('COUNT(*) AS count')) {
      const count = normalized.includes('trip_id = ?')
        ? this.activeRows.length
        : this.accountCount;
      return { count } as T;
    }
    if (normalized.includes('FROM pending_actions')) return this.stored as T | null;
    throw new Error(`Unexpected query: ${normalized}`);
  }

  async getAllAsync<T>(sql: string): Promise<T[]> {
    const normalized = compactSql(sql);
    if (normalized.includes('FROM coordinator_passengers')) {
      return this.attendanceEvidence as T[];
    }
    if (normalized.includes('SELECT state, COUNT(*) AS count')) {
      return this.statusRows as T[];
    }
    if (normalized.includes('SELECT payload_json FROM pending_actions')) {
      return this.activeRows as T[];
    }
    throw new Error(`Unexpected query: ${normalized}`);
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  mockedPublishAttendanceCloseoutCheckpoint.mockResolvedValue({} as never);
  mockedTrustedScanTime.mockResolvedValue({
    timestampMs: Date.now(),
    deviceClockDifferenceMs: 0,
  });
  useSessionStore.getState().setSession(COORDINATOR_SESSION);
  mockedTransaction.mockImplementation(async (database, task) => {
    await task(database);
  });
});

afterEach(() => {
  useSessionStore.getState().clear();
});

test('atomically stores a valid scan and runs bounded attendance maintenance', async () => {
  const database = new EnqueueDatabase();
  mockedOpenDatabase.mockResolvedValue(database as never);
  const trustedNow = Date.now();
  mockedTrustedScanTime.mockResolvedValueOnce({
    timestampMs: trustedNow,
    deviceClockDifferenceMs: 45_000,
  });

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR, { assignedCount: 100 }))
    .resolves.toEqual({ status: 'queued', idempotencyKey: EVENT_ID, duplicate: false });

  expect(mockedTransaction).toHaveBeenCalledTimes(1);
  expect(database.statements.some((sql) => sql.includes("last_error_code = 'LOCAL_QUEUE_EXPIRED'")))
    .toBe(true);
  expect(database.statements.some(
    (sql) => sql.includes(`LIMIT -1 OFFSET ${ATTENDANCE_QUEUE_POLICY.maxRejectedPerTrip}`),
  )).toBe(true);
  expect(database.statements.some(
    (sql) => sql.includes(`LIMIT -1 OFFSET ${ATTENDANCE_QUEUE_POLICY.maxReceiptsPerTrip}`),
  )).toBe(true);
  expect(JSON.parse(database.insertedPayload ?? '{}')).toMatchObject({
    scanned_at: new Date(trustedNow).toISOString(),
    signed_qr: SIGNED_QR,
  });
  expect(mockedRecordAttendanceLocalScanResult).toHaveBeenCalledWith('queued');
  expect(mockedRecordAttendanceTerminalRejection).toHaveBeenCalledWith(
    'LOCAL_QUEUE_EXPIRED',
    0,
  );
  expect(mockedPublishAttendanceCloseoutCheckpoint).toHaveBeenCalledWith(
    TRIP_ID,
    SESSION_ID,
  );
});

test('republishes only after the durable commit and isolates reporting failure', async () => {
  const database = new EnqueueDatabase();
  mockedOpenDatabase.mockResolvedValue(database as never);
  let committed = false;
  mockedTransaction.mockImplementationOnce(async (transactionDatabase, task) => {
    await task(transactionDatabase);
    committed = true;
  });
  mockedPublishAttendanceCloseoutCheckpoint.mockImplementationOnce(async () => {
    expect(committed).toBe(true);
    throw new Error('offline');
  });

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).resolves.toEqual({
    status: 'queued',
    idempotencyKey: EVENT_ID,
    duplicate: false,
  });
  expect(mockedPublishAttendanceCloseoutCheckpoint).toHaveBeenCalledWith(
    TRIP_ID,
    SESSION_ID,
  );
});

test('fails closed before storage when the signed trusted clock is unavailable', async () => {
  mockedTrustedScanTime.mockRejectedValueOnce(Object.assign(new Error('clock rollback'), {
    code: 'clock_rollback',
  }));

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).rejects.toMatchObject({
    code: 'clock_rollback',
  });
  expect(mockedTransaction).not.toHaveBeenCalled();
});

test('fails closed if the authenticated account boundary changes during clock verification', async () => {
  mockedTrustedScanTime.mockImplementationOnce(async () => {
    invalidateAuthenticationBoundary();
    return { timestampMs: Date.now(), deviceClockDifferenceMs: 0 };
  });

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).rejects.toMatchObject({
    code: 'AUTH_CONTEXT_CHANGED',
  });
  expect(mockedTransaction).not.toHaveBeenCalled();
});

test('rejects the transaction if authentication changes during the native insert', async () => {
  const database = new EnqueueDatabase();
  database.invalidateAuthenticationOnInsert = true;
  mockedOpenDatabase.mockResolvedValue(database as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).rejects.toMatchObject({
    code: 'AUTH_CONTEXT_CHANGED',
  });
  expect(mockedTransaction).toHaveBeenCalledTimes(1);
});

test('suppresses immediate replay while the same token is already queued', async () => {
  const database = new EnqueueDatabase();
  database.stored = { idempotency_key: 'existing-event', state: 'retryable' };
  mockedOpenDatabase.mockResolvedValue(database as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).resolves.toEqual({
    status: 'already_queued',
    idempotencyKey: 'existing-event',
    duplicate: true,
  });
  expect(database.statements.some((sql) => sql.startsWith('INSERT OR IGNORE'))).toBe(false);
  expect(mockedRecordAttendanceLocalScanResult).toHaveBeenCalledWith('already_queued');
});

test('distinguishes server-confirmed replay from a locally rejected audit item', async () => {
  const confirmedDatabase = new EnqueueDatabase();
  confirmedDatabase.receipt = { client_event_id: 'confirmed-event' };
  mockedOpenDatabase.mockResolvedValueOnce(confirmedDatabase as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).resolves.toEqual({
    status: 'already_confirmed',
    idempotencyKey: 'confirmed-event',
    duplicate: true,
  });

  const rejectedDatabase = new EnqueueDatabase();
  rejectedDatabase.stored = { idempotency_key: 'rejected-event', state: 'rejected' };
  mockedOpenDatabase.mockResolvedValueOnce(rejectedDatabase as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).resolves.toEqual({
    status: 'previously_rejected',
    idempotencyKey: 'rejected-event',
    duplicate: true,
  });

  const reviewDatabase = new EnqueueDatabase();
  reviewDatabase.stored = { idempotency_key: 'review-event', state: 'needs_review' };
  mockedOpenDatabase.mockResolvedValueOnce(reviewDatabase as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).resolves.toEqual({
    status: 'needs_review',
    idempotencyKey: 'review-event',
    duplicate: true,
  });
});

test('fails closed before inserting when assigned-population capacity is reached', async () => {
  const database = new EnqueueDatabase();
  database.activeRows = Array.from(
    { length: ATTENDANCE_QUEUE_POLICY.minActivePerSession },
    () => activePayload(),
  );
  mockedOpenDatabase.mockResolvedValue(database as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR, { assignedCount: 5 }))
    .resolves.toEqual({
      status: 'capacity_reached',
      capacity: 'session',
      idempotencyKey: null,
      duplicate: false,
    });
  expect(database.statements.some((sql) => sql.startsWith('INSERT OR IGNORE'))).toBe(false);
});

test('fails closed before inserting a forged token absent from the active trip roster', async () => {
  const database = new EnqueueDatabase();
  database.attendanceEvidence = [];
  mockedOpenDatabase.mockResolvedValue(database as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).rejects.toMatchObject({
    code: 'QR_NOT_IN_ACTIVE_ROSTER',
  });
  expect(database.statements.some((sql) => sql.startsWith('INSERT OR IGNORE'))).toBe(false);
  expect(mockedRecordAttendanceLocalScanResult).not.toHaveBeenCalled();
});

test('fails closed when the complete roster fence is stale', async () => {
  const database = new EnqueueDatabase();
  database.rosterFence.advertised_roster_version = 8;
  mockedOpenDatabase.mockResolvedValue(database as never);

  await expect(enqueueQrScan(TRIP_ID, SESSION_ID, SIGNED_QR)).rejects.toMatchObject({
    code: 'ROSTER_EVIDENCE_UNAVAILABLE',
  });
  expect(database.statements.some((sql) => sql.startsWith('INSERT OR IGNORE'))).toBe(false);
});

test('restores durable active and needs-review counts for the selected activity', async () => {
  const database = new EnqueueDatabase();
  database.statusRows = [
    { state: 'pending', count: 2 },
    { state: 'sending', count: 1 },
    { state: 'retryable', count: 3 },
    { state: 'needs_review', count: 4 },
  ];
  mockedOpenDatabase.mockResolvedValue(database as never);

  await expect(attendanceSessionQueueStatus(TRIP_ID, SESSION_ID)).resolves.toEqual({
    pending: 2,
    sending: 1,
    retryable: 3,
    needsReview: 4,
    awaitingConfirmation: 6,
  });

  await expect(attendanceTripQueueStatus(TRIP_ID)).resolves.toEqual({
    pending: 2,
    sending: 1,
    retryable: 3,
    needsReview: 4,
    awaitingConfirmation: 6,
  });
});
