import {
  compareAndSetOfflineAuthorizationRecord,
  getInstallationId,
  getOfflineAuthorizationRecord,
  type OfflineAuthorizationRecord,
} from '@/core/storage/secure-store';

import {
  authorizeStoredOfflineLease,
  OfflineAuthorizationError,
} from '../offline-authorization';
import { offlineAuthorizationReadiness } from '../offline-authorization-readiness';
import {
  invalidateAuthenticationBoundary,
  useSessionStore,
} from '../session-store';
import type { MobileSession } from '../types';

jest.mock('@/core/storage/secure-store', () => ({
  compareAndSetOfflineAuthorizationRecord: jest.fn(),
  getInstallationId: jest.fn(),
  getOfflineAuthorizationRecord: jest.fn(),
}));
jest.mock('../offline-authorization', () => {
  const actual = jest.requireActual('../offline-authorization');
  return {
    ...actual,
    authorizeStoredOfflineLease: jest.fn(),
  };
});

const SESSION: MobileSession = {
  accessToken: 'access-token',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: '33333333-3333-4333-8333-333333333333',
  networkMode: 'online',
  principal: {
    id: '44444444-4444-4444-8444-444444444444',
    accountId: '22222222-2222-4222-8222-222222222222',
    principalType: 'coordinator',
    agencyId: '11111111-1111-4111-8111-111111111111',
    displayName: 'Coordinator One',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};
const NAMESPACE = `${SESSION.principal.agencyId}.${SESSION.principal.accountId}`;
const RECORD: OfflineAuthorizationRecord = {
  formatVersion: 1,
  compactLease: `header.payload.${'s'.repeat(260)}`,
  highWaterServerTimeMs: 1_900_000_000_000,
  anchoredWallClockMs: 1_800_000_000_000,
};
const ADVANCED_RECORD: OfflineAuthorizationRecord = {
  ...RECORD,
  highWaterServerTimeMs: RECORD.highWaterServerTimeMs + 30_000,
  anchoredWallClockMs: RECORD.anchoredWallClockMs + 30_000,
};

const mockedGetRecord = jest.mocked(getOfflineAuthorizationRecord);
const mockedGetInstallationId = jest.mocked(getInstallationId);
const mockedCompareAndSet = jest.mocked(compareAndSetOfflineAuthorizationRecord);
const mockedAuthorize = jest.mocked(authorizeStoredOfflineLease);

beforeEach(() => {
  jest.clearAllMocks();
  invalidateAuthenticationBoundary();
  useSessionStore.getState().setSession(SESSION);
  mockedGetRecord.mockResolvedValue(RECORD);
  mockedGetInstallationId.mockResolvedValue('55555555-5555-4555-8555-555555555555');
  mockedCompareAndSet.mockResolvedValue(true);
  mockedAuthorize.mockReturnValue({
    claims: {} as never,
    record: ADVANCED_RECORD,
    trustedServerTimeMs: ADVANCED_RECORD.highWaterServerTimeMs,
    remainingMs: 3_600_000,
  });
});

afterEach(() => {
  invalidateAuthenticationBoundary();
  useSessionStore.getState().clear();
});

test('durably advances the verified clock high-water before reporting readiness', async () => {
  await expect(offlineAuthorizationReadiness()).resolves.toEqual({
    trustedServerTimeMs: ADVANCED_RECORD.highWaterServerTimeMs,
    remainingMs: 3_600_000,
  });
  expect(mockedAuthorize).toHaveBeenCalledWith(
    RECORD,
    expect.objectContaining({
      installationId: '55555555-5555-4555-8555-555555555555',
      sessionId: SESSION.sessionId,
      principalId: SESSION.principal.id,
      accountId: SESSION.principal.accountId,
      agencyId: SESSION.principal.agencyId,
      principalType: 'coordinator',
    }),
  );
  expect(mockedCompareAndSet).toHaveBeenCalledWith(
    NAMESPACE,
    RECORD,
    ADVANCED_RECORD,
  );
});

test('fails closed when refresh or logout replaced the verified lease record', async () => {
  mockedCompareAndSet.mockResolvedValue(false);

  await expect(offlineAuthorizationReadiness()).rejects.toMatchObject<Partial<OfflineAuthorizationError>>({
    code: 'clock_unavailable',
  });
});

test('does not persist after the authentication boundary changes during verification', async () => {
  mockedAuthorize.mockImplementation(() => {
    invalidateAuthenticationBoundary();
    return {
      claims: {} as never,
      record: ADVANCED_RECORD,
      trustedServerTimeMs: ADVANCED_RECORD.highWaterServerTimeMs,
      remainingMs: 3_600_000,
    };
  });

  await expect(offlineAuthorizationReadiness()).rejects.toMatchObject<Partial<OfflineAuthorizationError>>({
    code: 'clock_unavailable',
  });
  expect(mockedCompareAndSet).not.toHaveBeenCalled();
});

test('normalizes protected-storage failures to clock unavailable', async () => {
  mockedCompareAndSet.mockRejectedValue(new Error('private path and keystore details'));

  await expect(offlineAuthorizationReadiness()).rejects.toMatchObject<Partial<OfflineAuthorizationError>>({
    code: 'clock_unavailable',
  });
});
