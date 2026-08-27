import type { TokenResponse } from '@/core/api/contracts';
import { ApiError } from '@/core/api/client';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  activateSession,
  bootstrapSession,
  logoutSession,
  purgeLocalSession,
  switchPassengerTripSession,
} from '../session-service';
import {
  captureAuthenticationSnapshot,
  invalidateAuthenticationBoundary,
  useSessionStore,
} from '../session-store';
import {
  registerSessionLockSettlementHook,
  retryPendingAuthenticationLocks,
} from '../session-lock';
import { accountNamespace } from '../types';

type RegisteredRefreshHandler = (
  snapshot: Readonly<{ epoch: number; accessToken: string | null }>,
) => Promise<string | null>;

const mockSecureState: {
  activeNamespace: string | null;
  pendingCleanups: Set<string>;
  pendingAuthenticationLocks: Set<string>;
  refreshTokens: Map<string, string>;
  offlineAuthorizationRecords: Map<string, {
    formatVersion: 1;
    compactLease: string;
    highWaterServerTimeMs: number;
    anchoredWallClockMs: number;
  }>;
} = {
  activeNamespace: null,
  pendingCleanups: new Set(),
  pendingAuthenticationLocks: new Set(),
  refreshTokens: new Map(),
  offlineAuthorizationRecords: new Map(),
};
let mockRefreshHandler: RegisteredRefreshHandler | null = null;
let mockUnlockedOnlyAccessAvailable = true;

const mockApiRequest = jest.fn();
const mockInitializeFreshInstallGuard = jest.fn(async () => undefined);
const mockSetRefreshToken = jest.fn(async (namespace: string, token: string) => {
  mockSecureState.refreshTokens.set(namespace, token);
});
const mockSetActiveNamespace = jest.fn(async (namespace: string) => {
  mockSecureState.activeNamespace = namespace;
});
const mockGetActiveNamespace = jest.fn(async () => mockSecureState.activeNamespace);
const mockGetInstallationId = jest.fn(async () => 'dddddddd-dddd-4ddd-8ddd-dddddddddddd');
const mockGetRefreshToken = jest.fn(async (namespace: string) =>
  mockSecureState.refreshTokens.get(namespace) ?? null,
);
const mockSetOfflineAuthorizationRecord = jest.fn(async (
  namespace: string,
  record: {
    formatVersion: 1;
    compactLease: string;
    highWaterServerTimeMs: number;
    anchoredWallClockMs: number;
  },
) => {
  mockSecureState.offlineAuthorizationRecords.set(namespace, record);
});
const mockGetOfflineAuthorizationRecord = jest.fn(async (namespace: string) =>
  mockSecureState.offlineAuthorizationRecords.get(namespace) ?? null,
);
const mockClearOfflineAuthorizationRecord = jest.fn(async (namespace: string) => {
  mockSecureState.offlineAuthorizationRecords.delete(namespace);
});
const mockClearNamespaceSecrets = jest.fn(async (namespace: string) => {
  mockSecureState.refreshTokens.delete(namespace);
  mockSecureState.offlineAuthorizationRecords.delete(namespace);
  if (mockSecureState.activeNamespace === namespace) mockSecureState.activeNamespace = null;
});
const mockClearNamespaceAuthentication = jest.fn(async (namespace: string) => {
  mockSecureState.refreshTokens.delete(namespace);
  mockSecureState.offlineAuthorizationRecords.delete(namespace);
  if (mockSecureState.activeNamespace === namespace) mockSecureState.activeNamespace = null;
});
const mockGetPendingLocalCleanups = jest.fn(async () => [...mockSecureState.pendingCleanups]);
const mockMarkLocalCleanupPending = jest.fn(async (namespace: string) => {
  mockSecureState.pendingCleanups.add(namespace);
});
const mockClearLocalCleanupPending = jest.fn(async (namespace: string) => {
  mockSecureState.pendingCleanups.delete(namespace);
});
const mockGetPendingAuthenticationLocks = jest.fn(
  async () => [...mockSecureState.pendingAuthenticationLocks],
);
const mockMarkAuthenticationLockPending = jest.fn(async (namespace: string) => {
  mockSecureState.pendingAuthenticationLocks.add(namespace);
});
const mockClearAuthenticationLockPending = jest.fn(async (namespace: string) => {
  mockSecureState.pendingAuthenticationLocks.delete(namespace);
});
const mockDeleteAccountDatabase = jest.fn(async (_namespace: string) => undefined);
const mockCloseAccountDatabase = jest.fn(async () => undefined);
const mockAssertDurableActionQueueSynchronized = jest.fn(async (_namespace: string) => undefined);
const mockDurableAttendanceRecordCount = jest.fn(async (_namespace: string) => 0);
const mockRecordExplicitAttendanceDiscard = jest.fn();
const mockRecordAuthenticationLockOutcome = jest.fn();
const mockRecordAuthenticationQuarantineDepth = jest.fn();
const mockBeginVaultNamespacePurge = jest.fn(async (_namespace: string) => undefined);
const mockDeleteVaultNamespace = jest.fn(async (_namespace: string) => undefined);
const mockPurgeTemporaryViews = jest.fn(async () => undefined);
const mockFinishVaultNamespacePurge = jest.fn(
  (_namespace: string, _acknowledged: boolean) => undefined,
);
const mockDatabaseRun = jest.fn(async (..._args: unknown[]) => undefined);
const mockOpenAccountDatabase = jest.fn(async (namespace: string) => ({
  __namespace: namespace,
  runAsync: (...args: unknown[]) => mockDatabaseRun(namespace, ...args),
  getFirstAsync: jest.fn<Promise<unknown>, []>(async () => null),
}));

jest.mock('@/core/api/client', () => {
  class MockApiError extends Error {
    readonly status: number;
    readonly code: string;
    readonly retryAfterSeconds: number | null;

    constructor(
      mockMessage: string,
      mockStatus: number,
      mockCode: string,
      mockRetryAfterSeconds: number | null,
    ) {
      super(mockMessage);
      this.status = mockStatus;
      this.code = mockCode;
      this.retryAfterSeconds = mockRetryAfterSeconds;
    }
  }

  return {
    ApiError: MockApiError,
    apiRequest: (...args: unknown[]) => mockApiRequest(...args),
    registerRefreshHandler: jest.fn((handler: RegisteredRefreshHandler) => {
      mockRefreshHandler = handler;
      return () => {
        if (mockRefreshHandler === handler) mockRefreshHandler = null;
      };
    }),
  };
});

jest.mock('@/core/demo/demo-mode', () => ({
  assertDemoMode: jest.fn(),
  isDemoMode: () => false,
}));

jest.mock('@/core/demo/demo-data', () => ({
  demoPrincipal: jest.fn(),
  isDemoPrincipal: () => false,
  seedDemoAccount: jest.fn(async () => undefined),
}));

jest.mock('@/core/storage/installation-guard', () => ({
  initializeFreshInstallGuard: () => mockInitializeFreshInstallGuard(),
}));

jest.mock('@/core/storage/secure-store', () => ({
  clearAuthenticationLockPending: (...args: [string]) => (
    mockClearAuthenticationLockPending(...args)
  ),
  getActiveNamespace: () => mockGetActiveNamespace(),
  getInstallationId: () => mockGetInstallationId(),
  getRefreshToken: (namespace: string) => mockGetRefreshToken(namespace),
  setRefreshToken: (...args: [string, string]) => mockSetRefreshToken(...args),
  setOfflineAuthorizationRecord: (...args: [string, {
    formatVersion: 1;
    compactLease: string;
    highWaterServerTimeMs: number;
    anchoredWallClockMs: number;
  }]) => mockSetOfflineAuthorizationRecord(...args),
  getOfflineAuthorizationRecord: (namespace: string) => (
    mockGetOfflineAuthorizationRecord(namespace)
  ),
  clearOfflineAuthorizationRecord: (namespace: string) => (
    mockClearOfflineAuthorizationRecord(namespace)
  ),
  setActiveNamespace: (...args: [string]) => mockSetActiveNamespace(...args),
  getPendingLocalCleanups: () => mockGetPendingLocalCleanups(),
  getPendingAuthenticationLocks: () => mockGetPendingAuthenticationLocks(),
  markAuthenticationLockPending: (...args: [string]) => (
    mockMarkAuthenticationLockPending(...args)
  ),
  markLocalCleanupPending: (...args: [string]) => mockMarkLocalCleanupPending(...args),
  clearLocalCleanupPending: (...args: [string]) => mockClearLocalCleanupPending(...args),
  clearNamespaceAuthentication: (...args: [string]) => (
    mockClearNamespaceAuthentication(...args)
  ),
  clearNamespaceSecrets: (...args: [string]) => mockClearNamespaceSecrets(...args),
  isUnlockedOnlySecureValueAccessAvailable: () => mockUnlockedOnlyAccessAvailable,
}));

jest.mock('@/core/storage/pending-action-safety', () => ({
  assertDurableActionQueueSynchronized: (namespace: string) => (
    mockAssertDurableActionQueueSynchronized(namespace)
  ),
  durableAttendanceRecordCount: (namespace: string) => (
    mockDurableAttendanceRecordCount(namespace)
  ),
}));

jest.mock('@/core/observability/attendance-observability', () => ({
  recordExplicitAttendanceDiscard: (count: number) => mockRecordExplicitAttendanceDiscard(count),
}));

jest.mock('@/core/observability/authentication-observability', () => ({
  recordAuthenticationLockOutcome: (outcome: 'success' | 'failure') => (
    mockRecordAuthenticationLockOutcome(outcome)
  ),
  recordAuthenticationQuarantineDepth: (count: number) => (
    mockRecordAuthenticationQuarantineDepth(count)
  ),
}));

jest.mock('../offline-authorization', () => {
  class MockOfflineAuthorizationError extends Error {}
  const record = (compactLease: string) => ({
    formatVersion: 1 as const,
    compactLease,
    highWaterServerTimeMs: 1_900_000_000_000,
    anchoredWallClockMs: 1_800_000_000_000,
  });
  return {
    OfflineAuthorizationError: MockOfflineAuthorizationError,
    acceptOnlineOfflineAuthorizationLease: (compactLease: string) => ({
      claims: {},
      record: record(compactLease),
      trustedServerTimeMs: 1_900_000_000_000,
      remainingMs: 43_200_000,
    }),
    authorizeStoredOfflineLease: (storedRecord: ReturnType<typeof record>) => ({
      claims: {},
      record: storedRecord,
      trustedServerTimeMs: 1_900_000_000_000,
      remainingMs: 43_200_000,
    }),
    clearOfflineAuthorizationBootAnchor: jest.fn(),
  };
});

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: (namespace: string) => mockOpenAccountDatabase(namespace),
  withAccountTransaction: jest.fn(async (
    database: { __namespace: string; runAsync: (...args: unknown[]) => Promise<void> },
    task: (transaction: { runAsync: (...args: unknown[]) => Promise<void> }) => Promise<void>,
  ) => task({
    runAsync: (...args: unknown[]) => mockDatabaseRun(database.__namespace, ...args),
  })),
  deleteAccountDatabase: (...args: [string]) => mockDeleteAccountDatabase(...args),
  closeAccountDatabase: () => mockCloseAccountDatabase(),
}));

jest.mock('@/core/storage/vault', () => ({
  beginVaultNamespacePurge: (...args: [string]) => mockBeginVaultNamespacePurge(...args),
  deleteVaultNamespace: (...args: [string]) => mockDeleteVaultNamespace(...args),
  finishVaultNamespacePurge: (...args: [string, boolean]) => (
    mockFinishVaultNamespacePurge(...args)
  ),
  purgeTemporaryViews: () => mockPurgeTemporaryViews(),
}));

const agencyA = '11111111-1111-4111-8111-111111111111';
const passengerA = '22222222-2222-4222-8222-222222222222';
const passengerASecondTrip = '44444444-4444-4444-8444-444444444444';
const sessionA = '33333333-3333-4333-8333-333333333333';
const agencyB = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const passengerB = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const sessionB = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const namespaceA = accountNamespace({ agencyId: agencyA, accountId: passengerA });
const namespaceB = accountNamespace({ agencyId: agencyB, accountId: passengerB });

function tokenResponse(input: {
  agencyId: string;
  principalId: string;
  accountId?: string;
  sessionId: string;
  marker: string;
}): TokenResponse {
  return {
    access_token: `access-${input.marker}-`.padEnd(48, input.marker),
    refresh_token: `refresh-${input.marker}-`.padEnd(48, input.marker),
    token_type: 'bearer',
    access_token_expires_at: '2026-08-03T12:00:00.000Z',
    refresh_token_expires_at: '2026-09-03T12:00:00.000Z',
    session_id: input.sessionId,
    offline_authorization_lease: `header.payload.signature-${input.marker}`.padEnd(300, input.marker),
    principal: {
      id: input.principalId,
      account_id: input.accountId ?? input.principalId,
      principal_type: 'passenger',
      agency_id: input.agencyId,
      display_name: `Passenger ${input.marker}`,
      email: null,
      phone_number: '+919876543210',
      force_password_change: false,
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const initialA = tokenResponse({
  agencyId: agencyA,
  principalId: passengerA,
  sessionId: sessionA,
  marker: 'a',
});
const rotatedA = tokenResponse({
  agencyId: agencyA,
  principalId: passengerA,
  sessionId: sessionA,
  marker: 'r',
});
const switchedA = tokenResponse({
  agencyId: agencyA,
  principalId: passengerASecondTrip,
  accountId: passengerA,
  sessionId: sessionA,
  marker: 's',
});
const initialB = tokenResponse({
  agencyId: agencyB,
  principalId: passengerB,
  sessionId: sessionB,
  marker: 'b',
});

function offlineRow(tokens: TokenResponse) {
  return {
    id: tokens.principal.id,
    account_id: tokens.principal.account_id,
    agency_id: tokens.principal.agency_id,
    principal_type: tokens.principal.principal_type,
    passenger_id: tokens.principal.passenger_id ?? tokens.principal.id,
    display_name: tokens.principal.display_name,
    email: tokens.principal.email,
    phone_number: tokens.principal.phone_number,
    session_id: tokens.session_id,
    access_token_expires_at: tokens.access_token_expires_at,
    refresh_token_expires_at: tokens.refresh_token_expires_at,
    force_password_change: tokens.principal.force_password_change ? 1 : 0,
  };
}

beforeEach(async () => {
  invalidateAuthenticationBoundary();
  useSessionStore.getState().clear();
  useSelectedTripStore.getState().clear();
  mockSecureState.activeNamespace = null;
  mockSecureState.pendingCleanups.clear();
  mockSecureState.pendingAuthenticationLocks.clear();
  mockSecureState.refreshTokens.clear();
  mockSecureState.offlineAuthorizationRecords.clear();
  mockRefreshHandler = null;
  mockUnlockedOnlyAccessAvailable = true;
  mockApiRequest.mockReset();
  mockInitializeFreshInstallGuard.mockReset();
  mockInitializeFreshInstallGuard.mockResolvedValue(undefined);
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/logout') return null;
    if (path === '/mobile/push/unregister') return { unregistered: true, revoked_count: 1 };
    throw new Error(`Unexpected API request: ${path}`);
  });
  mockSetRefreshToken.mockClear();
  mockSetActiveNamespace.mockClear();
  mockGetActiveNamespace.mockReset();
  mockGetActiveNamespace.mockImplementation(async () => mockSecureState.activeNamespace);
  mockGetInstallationId.mockReset();
  mockGetInstallationId.mockResolvedValue('dddddddd-dddd-4ddd-8ddd-dddddddddddd');
  mockGetRefreshToken.mockReset();
  mockGetRefreshToken.mockImplementation(async (namespace: string) =>
    mockSecureState.refreshTokens.get(namespace) ?? null,
  );
  mockSetOfflineAuthorizationRecord.mockClear();
  mockGetOfflineAuthorizationRecord.mockClear();
  mockGetOfflineAuthorizationRecord.mockImplementation(async (namespace: string) =>
    mockSecureState.offlineAuthorizationRecords.get(namespace) ?? null,
  );
  mockClearOfflineAuthorizationRecord.mockClear();
  mockClearNamespaceSecrets.mockClear();
  mockClearNamespaceAuthentication.mockClear();
  mockGetPendingLocalCleanups.mockClear();
  mockMarkLocalCleanupPending.mockClear();
  mockClearLocalCleanupPending.mockClear();
  mockGetPendingAuthenticationLocks.mockClear();
  mockMarkAuthenticationLockPending.mockClear();
  mockClearAuthenticationLockPending.mockClear();
  mockDeleteAccountDatabase.mockClear();
  mockCloseAccountDatabase.mockClear();
  mockAssertDurableActionQueueSynchronized.mockReset();
  mockAssertDurableActionQueueSynchronized.mockResolvedValue(undefined);
  mockDurableAttendanceRecordCount.mockReset();
  mockDurableAttendanceRecordCount.mockResolvedValue(0);
  mockRecordExplicitAttendanceDiscard.mockReset();
  mockRecordAuthenticationLockOutcome.mockReset();
  mockRecordAuthenticationQuarantineDepth.mockReset();
  mockBeginVaultNamespacePurge.mockClear();
  mockBeginVaultNamespacePurge.mockResolvedValue(undefined);
  mockDeleteVaultNamespace.mockClear();
  mockPurgeTemporaryViews.mockClear();
  mockFinishVaultNamespacePurge.mockClear();
  mockDatabaseRun.mockClear();
  mockOpenAccountDatabase.mockReset();
  mockOpenAccountDatabase.mockImplementation(async (namespace: string) => ({
    __namespace: namespace,
    runAsync: (...args: unknown[]) => mockDatabaseRun(namespace, ...args),
    getFirstAsync: jest.fn(async () => null),
  }));
  await bootstrapSession();
  expect(mockRefreshHandler).not.toBeNull();
});

test('a top-level SecureStore bootstrap rejection cannot leave the session booting', async () => {
  useSessionStore.getState().beginBootstrap();
  mockInitializeFreshInstallGuard.mockRejectedValueOnce(new Error('SecureStore unavailable'));

  await expect(bootstrapSession()).rejects.toThrow('SecureStore unavailable');

  expect(useSessionStore.getState()).toMatchObject({
    status: 'anonymous',
    session: null,
    bootstrapErrorCode: 'SESSION_BOOTSTRAP_FAILED',
  });
  expect(useSelectedTripStore.getState().tripId).toBeNull();
});

test('an offline database bootstrap rejection becomes an explicit retryable error state', async () => {
  useSessionStore.getState().beginBootstrap();
  mockSecureState.activeNamespace = namespaceA;
  mockSecureState.refreshTokens.set(namespaceA, 'stored-refresh-token');
  mockSecureState.offlineAuthorizationRecords.set(namespaceA, {
    formatVersion: 1,
    compactLease: initialA.offline_authorization_lease,
    highWaterServerTimeMs: 1_900_000_000_000,
    anchoredWallClockMs: 1_800_000_000_000,
  });
  mockApiRequest.mockRejectedValueOnce(new TypeError('network unavailable'));
  mockOpenAccountDatabase.mockRejectedValueOnce(new Error('NativeDatabase.execAsync rejected'));

  await expect(bootstrapSession()).rejects.toThrow('NativeDatabase.execAsync rejected');

  expect(useSessionStore.getState()).toMatchObject({
    status: 'anonymous',
    session: null,
    bootstrapErrorCode: 'SESSION_BOOTSTRAP_FAILED',
  });
  expect(useSelectedTripStore.getState().tripId).toBeNull();
});

test('cache-first bootstrap publishes a valid local identity before online validation finishes', async () => {
  const refreshResponse = deferred<TokenResponse>();
  const refreshStarted = deferred<void>();
  mockSecureState.activeNamespace = namespaceA;
  mockSecureState.refreshTokens.set(namespaceA, 'stored-refresh-token');
  mockSecureState.offlineAuthorizationRecords.set(namespaceA, {
    formatVersion: 1,
    compactLease: initialA.offline_authorization_lease,
    highWaterServerTimeMs: 1_900_000_000_000,
    anchoredWallClockMs: 1_800_000_000_000,
  });
  mockOpenAccountDatabase.mockImplementation(async (namespace: string) => ({
    __namespace: namespace,
    runAsync: (...args: unknown[]) => mockDatabaseRun(namespace, ...args),
    getFirstAsync: jest.fn(async () => offlineRow(initialA)),
  }));
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/refresh') {
      refreshStarted.resolve();
      return refreshResponse.promise;
    }
    throw new Error(`Unexpected API request: ${path}`);
  });

  await expect(bootstrapSession({ validation: 'background' })).resolves.toBeUndefined();
  await refreshStarted.promise;
  expect(useSessionStore.getState().session).toMatchObject({
    networkMode: 'offline',
    sessionId: sessionA,
    principal: { accountId: passengerA },
  });

  // A screen request that asks the registered refresh handler while bootstrap
  // validation is active must join the same token exchange.
  const joinedRefresh = mockRefreshHandler!(captureAuthenticationSnapshot());
  expect(mockApiRequest).toHaveBeenCalledTimes(1);
  refreshResponse.resolve(rotatedA);
  await expect(joinedRefresh).resolves.toBe(rotatedA.access_token);
  expect(useSessionStore.getState().session).toMatchObject({
    networkMode: 'online',
    accessToken: rotatedA.access_token,
  });
});

test('cache-first bootstrap refuses an encrypted identity without a signed authorization lease', async () => {
  mockSecureState.activeNamespace = namespaceA;
  mockSecureState.refreshTokens.set(namespaceA, 'stored-refresh-token');
  mockOpenAccountDatabase.mockImplementation(async (namespace: string) => ({
    __namespace: namespace,
    runAsync: (...args: unknown[]) => mockDatabaseRun(namespace, ...args),
    getFirstAsync: jest.fn(async () => offlineRow(initialA)),
  }));
  mockApiRequest.mockRejectedValueOnce(new TypeError('network unavailable'));

  await expect(bootstrapSession({ validation: 'background' })).resolves.toBeUndefined();

  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
});

test('native background bootstrap skips unlocked-only lease access but still refreshes metadata', async () => {
  mockSecureState.activeNamespace = namespaceA;
  mockSecureState.refreshTokens.set(namespaceA, 'stored-refresh-token');
  mockSecureState.offlineAuthorizationRecords.set(namespaceA, {
    formatVersion: 1,
    compactLease: initialA.offline_authorization_lease,
    highWaterServerTimeMs: 1_900_000_000_000,
    anchoredWallClockMs: 1_800_000_000_000,
  });
  mockUnlockedOnlyAccessAvailable = false;
  mockGetOfflineAuthorizationRecord.mockClear();
  mockSetOfflineAuthorizationRecord.mockClear();
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/refresh') return rotatedA;
    throw new Error(`Unexpected API request: ${path}`);
  });

  await expect(bootstrapSession({ execution: 'native-background' })).resolves.toBeUndefined();

  expect(mockGetOfflineAuthorizationRecord).not.toHaveBeenCalled();
  expect(mockSetOfflineAuthorizationRecord).not.toHaveBeenCalled();
  expect(mockSecureState.refreshTokens.get(namespaceA)).toBe(rotatedA.refresh_token);
  expect(useSessionStore.getState().session).toMatchObject({
    networkMode: 'online',
    accessToken: rotatedA.access_token,
    sessionId: sessionA,
  });
});

test('a delayed refresh cannot reactivate an account after switching accounts', async () => {
  await activateSession(initialA);
  const refreshResponse = deferred<TokenResponse>();
  const refreshStarted = deferred<void>();
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/refresh') {
      refreshStarted.resolve();
      return refreshResponse.promise;
    }
    throw new Error(`Unexpected API request: ${path}`);
  });

  const staleRefresh = mockRefreshHandler!(captureAuthenticationSnapshot());
  await refreshStarted.promise;
  await activateSession(initialB);
  refreshResponse.resolve(rotatedA);

  await expect(staleRefresh).resolves.toBeNull();
  expect(useSessionStore.getState().session).toMatchObject({
    accessToken: initialB.access_token,
    sessionId: initialB.session_id,
    principal: { id: passengerB, agencyId: agencyB },
  });
  expect(mockSecureState.activeNamespace).toBe(namespaceB);
  expect(mockSecureState.refreshTokens.get(namespaceB)).toBe(initialB.refresh_token);
  expect(mockSetRefreshToken).not.toHaveBeenCalledWith(namespaceA, rotatedA.refresh_token);
  expect(mockClearNamespaceAuthentication).toHaveBeenCalledWith(namespaceA);
  expect(mockCloseAccountDatabase).toHaveBeenCalled();
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceB);
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalledWith(namespaceB);
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalledWith(namespaceB);
});

test('a delayed refresh cannot recreate a session after logout', async () => {
  await activateSession(initialA);
  const refreshResponse = deferred<TokenResponse>();
  const refreshStarted = deferred<void>();
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/refresh') {
      refreshStarted.resolve();
      return refreshResponse.promise;
    }
    if (path === '/mobile/auth/logout') return null;
    throw new Error(`Unexpected API request: ${path}`);
  });

  const staleRefresh = mockRefreshHandler!(captureAuthenticationSnapshot());
  await refreshStarted.promise;
  await logoutSession();
  refreshResponse.resolve(rotatedA);

  await expect(staleRefresh).resolves.toBeNull();
  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
  expect(mockSecureState.activeNamespace).toBeNull();
  expect(mockSecureState.refreshTokens.has(namespaceA)).toBe(false);
  expect(mockSetRefreshToken).not.toHaveBeenCalledWith(namespaceA, rotatedA.refresh_token);
});

test('explicit account purge waits for namespace writes before deleting the database, vault and keys', async () => {
  await activateSession(initialA);
  const oldWriteFinished = deferred<void>();
  const fenceStarted = deferred<void>();
  mockBeginVaultNamespacePurge.mockImplementationOnce(async () => {
    fenceStarted.resolve();
    await oldWriteFinished.promise;
  });

  const logout = purgeLocalSession(namespaceA);
  await fenceStarted.promise;
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalled();
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalled();
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalled();

  oldWriteFinished.resolve();
  await logout;

  expect(mockDeleteAccountDatabase).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).toHaveBeenCalledWith(namespaceA);
  expect(mockFinishVaultNamespacePurge).toHaveBeenCalledWith(namespaceA, true);
  expect(mockBeginVaultNamespacePurge.mock.invocationCallOrder[0]!).toBeLessThan(
    mockDeleteAccountDatabase.mock.invocationCallOrder[0]!,
  );
  expect(mockClearNamespaceSecrets.mock.invocationCallOrder[0]!).toBeLessThan(
    mockFinishVaultNamespacePurge.mock.invocationCallOrder[0]!,
  );
});

test('explicit account purge clears credentials and stays fenced when deletion fails', async () => {
  await activateSession(initialA);
  mockDeleteAccountDatabase.mockRejectedValueOnce(new Error('database delete failed'));
  mockDeleteVaultNamespace.mockRejectedValueOnce(new Error('vault delete failed'));

  await expect(purgeLocalSession(namespaceA)).rejects.toThrow('database delete failed');

  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
  expect(mockDeleteAccountDatabase).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceAuthentication).toHaveBeenCalledWith(namespaceA);
  expect(mockSecureState.activeNamespace).toBeNull();
  expect(mockSecureState.refreshTokens.has(namespaceA)).toBe(false);
  expect(mockSecureState.pendingCleanups.has(namespaceA)).toBe(true);
  expect(mockFinishVaultNamespacePurge).toHaveBeenCalledWith(namespaceA, false);
});

test('a failed explicit account purge is retried after restart before the account can reopen', async () => {
  await activateSession(initialA);
  mockDeleteAccountDatabase.mockRejectedValueOnce(new Error('database delete failed'));

  await expect(purgeLocalSession(namespaceA)).rejects.toThrow('database delete failed');
  expect(mockSecureState.activeNamespace).toBeNull();
  expect(mockSecureState.pendingCleanups.has(namespaceA)).toBe(true);
  expect(mockClearNamespaceAuthentication).toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceA);

  // Simulate a new process bootstrap: process-local hook refs are gone, while
  // the global SecureStore cleanup marker remains.
  mockClearNamespaceAuthentication.mockClear();
  mockClearNamespaceSecrets.mockClear();
  mockDeleteAccountDatabase.mockClear();
  mockDeleteVaultNamespace.mockClear();
  await bootstrapSession();

  expect(mockDeleteAccountDatabase).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).toHaveBeenCalledWith(namespaceA);
  expect(mockSecureState.pendingCleanups.has(namespaceA)).toBe(false);

  await expect(activateSession(initialA)).resolves.toMatchObject({
    principal: { accountId: passengerA },
  });
});

test('bootstrap never restores an active namespace that remains pending cleanup', async () => {
  useSessionStore.getState().beginBootstrap();
  mockSecureState.activeNamespace = namespaceA;
  mockSecureState.refreshTokens.set(namespaceA, 'stale-refresh-token');
  mockSecureState.pendingCleanups.add(namespaceA);
  mockDeleteAccountDatabase.mockRejectedValueOnce(new Error('database still busy'));
  mockClearNamespaceAuthentication
    .mockRejectedValueOnce(new Error('keychain unavailable'))
    .mockRejectedValueOnce(new Error('keychain unavailable'));

  await expect(bootstrapSession()).rejects.toThrow('Previous account cleanup is still pending.');

  expect(mockApiRequest).not.toHaveBeenCalledWith(
    '/mobile/auth/refresh',
    expect.anything(),
  );
  expect(useSessionStore.getState()).toMatchObject({
    status: 'anonymous',
    session: null,
    bootstrapErrorCode: 'SESSION_BOOTSTRAP_FAILED',
  });
  expect(useSelectedTripStore.getState().tripId).toBeNull();
});

test('logout locks and preserves the authenticated namespace after verifying the queue', async () => {
  await activateSession(initialA);
  useSelectedTripStore.getState().selectTrip('55555555-5555-4555-8555-555555555555');
  mockGetActiveNamespace.mockClear();
  mockGetActiveNamespace.mockRejectedValueOnce(new Error('keychain read failed'));

  const logout = logoutSession();
  await expect(logout).resolves.toBeUndefined();
  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
  expect(useSelectedTripStore.getState().tripId).toBeNull();

  expect(mockGetActiveNamespace).not.toHaveBeenCalled();
  expect(mockApiRequest).toHaveBeenCalledWith(
    '/mobile/push/unregister',
    expect.objectContaining({
      body: { installation_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' },
      authenticated: false,
      retryAuthentication: false,
      headers: { Authorization: `Bearer ${initialA.access_token}` },
    }),
  );
  expect(mockPurgeTemporaryViews).toHaveBeenCalledTimes(1);
  expect(mockCloseAccountDatabase).toHaveBeenCalledTimes(1);
  expect(mockClearNamespaceAuthentication).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceA);
  expect(mockMarkAuthenticationLockPending).toHaveBeenCalledWith(namespaceA);
  expect(mockClearAuthenticationLockPending).toHaveBeenCalledWith(namespaceA);
  expect(mockRecordAuthenticationLockOutcome).toHaveBeenLastCalledWith('success');
});

test('logout awaits native feature settlement before closing the account database', async () => {
  await activateSession(initialA);
  const settlement = deferred<void>();
  const hookStarted = deferred<void>();
  const hook = jest.fn(async (namespace: string) => {
    expect(namespace).toBe(namespaceA);
    hookStarted.resolve();
    await settlement.promise;
  });
  const unregister = registerSessionLockSettlementHook('test-native-transfer', hook);
  mockCloseAccountDatabase.mockClear();
  mockPurgeTemporaryViews.mockClear();

  try {
    const logout = logoutSession();
    await hookStarted.promise;
    expect(hook).toHaveBeenCalledTimes(1);
    expect(mockCloseAccountDatabase).not.toHaveBeenCalled();
    expect(mockPurgeTemporaryViews).not.toHaveBeenCalled();

    settlement.resolve();
    await expect(logout).resolves.toBeUndefined();
    expect(mockCloseAccountDatabase).toHaveBeenCalledTimes(1);
    expect(mockPurgeTemporaryViews).toHaveBeenCalledTimes(1);
  } finally {
    unregister();
  }
});

test('reports only aggregate authentication quarantine state after a failed lock retry', async () => {
  mockSecureState.pendingAuthenticationLocks.add(namespaceA);
  mockClearNamespaceAuthentication.mockRejectedValueOnce(new Error('keychain unavailable'));

  await expect(retryPendingAuthenticationLocks()).resolves.toEqual(new Set([namespaceA]));

  expect(mockRecordAuthenticationLockOutcome).toHaveBeenCalledWith('failure');
  expect(mockRecordAuthenticationQuarantineDepth).toHaveBeenCalledWith(1);
});

test('logout remains anonymous and preserves encrypted data when refresh-token lookup fails', async () => {
  await activateSession(initialA);
  useSelectedTripStore.getState().selectTrip('55555555-5555-4555-8555-555555555555');
  mockGetRefreshToken.mockRejectedValueOnce(new Error('refresh token read failed'));

  const logout = logoutSession();
  await expect(logout).resolves.toBeUndefined();
  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
  expect(useSelectedTripStore.getState().tripId).toBeNull();

  expect(mockApiRequest).toHaveBeenCalledWith(
    '/mobile/auth/logout',
    expect.objectContaining({
      authenticated: false,
      retryAuthentication: false,
      headers: { Authorization: `Bearer ${initialA.access_token}` },
    }),
  );
  expect(mockPurgeTemporaryViews).toHaveBeenCalledTimes(1);
  expect(mockCloseAccountDatabase).toHaveBeenCalledTimes(1);
  expect(mockClearNamespaceAuthentication).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceA);
});

test('logout fails closed before revocation when the durable queue is not synchronized', async () => {
  await activateSession(initialA);
  mockAssertDurableActionQueueSynchronized.mockRejectedValueOnce(
    new Error('unsynchronized local actions'),
  );

  await expect(logoutSession()).rejects.toThrow('unsynchronized local actions');

  expect(useSessionStore.getState()).toMatchObject({
    status: 'authenticated',
    session: { sessionId: sessionA },
  });
  expect(mockApiRequest).not.toHaveBeenCalledWith('/mobile/auth/logout', expect.anything());
  expect(mockClearNamespaceAuthentication).not.toHaveBeenCalled();
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalled();
});

test('explicitly confirmed discard locks the encrypted namespace without deleting queue evidence', async () => {
  await activateSession(initialA);
  mockAssertDurableActionQueueSynchronized.mockRejectedValueOnce(
    new Error('queue must not be inspected after explicit confirmation'),
  );

  await expect(logoutSession({ discardUnsynchronizedActions: true })).resolves.toBeUndefined();

  expect(mockAssertDurableActionQueueSynchronized).not.toHaveBeenCalled();
  expect(mockDurableAttendanceRecordCount).not.toHaveBeenCalled();
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceAuthentication).toHaveBeenCalledWith(namespaceA);
  expect(mockRecordExplicitAttendanceDiscard).toHaveBeenCalledWith(0);
});

test('explicit discard no longer depends on destructive count-only queue deletion', async () => {
  await activateSession(initialA);

  await expect(logoutSession({ discardUnsynchronizedActions: true })).resolves.toBeUndefined();

  expect(useSessionStore.getState()).toMatchObject({
    status: 'anonymous',
    session: null,
  });
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalled();
  expect(mockDurableAttendanceRecordCount).not.toHaveBeenCalled();
  expect(mockRecordExplicitAttendanceDiscard).toHaveBeenCalledWith(0);
});

test('the same account can reopen its preserved encrypted database after ordinary logout', async () => {
  await activateSession(initialA);
  await logoutSession();
  mockOpenAccountDatabase.mockClear();
  mockDeleteAccountDatabase.mockClear();
  mockDeleteVaultNamespace.mockClear();

  await expect(activateSession(rotatedA)).resolves.toMatchObject({
    sessionId: sessionA,
    principal: { accountId: passengerA },
  });

  expect(mockOpenAccountDatabase).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalled();
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalled();
});

test('a current hard refresh rejection locks encrypted data instead of deleting its queue', async () => {
  await activateSession(initialA);
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/refresh') {
      throw new ApiError('Refresh rejected', 401, 'AUTHENTICATION_ERROR', null);
    }
    throw new Error(`Unexpected API request: ${path}`);
  });

  await expect(mockRefreshHandler!(captureAuthenticationSnapshot())).resolves.toBeNull();

  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
  expect(mockClearNamespaceAuthentication).toHaveBeenCalledWith(namespaceA);
  expect(mockCloseAccountDatabase).toHaveBeenCalled();
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceA);
});

test('a stale rejected refresh cannot purge the newly selected account', async () => {
  await activateSession(initialA);
  const refreshResponse = deferred<TokenResponse>();
  const refreshStarted = deferred<void>();
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/refresh') {
      refreshStarted.resolve();
      return refreshResponse.promise;
    }
    throw new Error(`Unexpected API request: ${path}`);
  });

  const staleRefresh = mockRefreshHandler!(captureAuthenticationSnapshot());
  await refreshStarted.promise;
  await activateSession(initialB);
  refreshResponse.reject(new ApiError('Refresh rejected', 401, 'AUTHENTICATION_ERROR', null));

  await expect(staleRefresh).resolves.toBeNull();
  expect(useSessionStore.getState().session?.principal.id).toBe(passengerB);
  expect(mockSecureState.activeNamespace).toBe(namespaceB);
  expect(mockSecureState.refreshTokens.get(namespaceB)).toBe(initialB.refresh_token);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalledWith(namespaceB);
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalledWith(namespaceB);
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalledWith(namespaceB);
});

test('a refresh inside the same authentication boundary still rotates normally', async () => {
  await activateSession(initialA);
  const refreshResponse = deferred<TokenResponse>();
  const refreshStarted = deferred<void>();
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/refresh') {
      refreshStarted.resolve();
      return refreshResponse.promise;
    }
    throw new Error(`Unexpected API request: ${path}`);
  });

  const refresh = mockRefreshHandler!(captureAuthenticationSnapshot());
  await refreshStarted.promise;
  refreshResponse.resolve(rotatedA);

  await expect(refresh).resolves.toBe(rotatedA.access_token);
  expect(useSessionStore.getState().session).toMatchObject({
    accessToken: rotatedA.access_token,
    sessionId: sessionA,
    principal: { id: passengerA, agencyId: agencyA },
  });
  expect(mockSecureState.activeNamespace).toBe(namespaceA);
  expect(mockSecureState.refreshTokens.get(namespaceA)).toBe(rotatedA.refresh_token);
  expect(mockApiRequest).toHaveBeenCalledWith(
    '/mobile/auth/refresh',
    expect.objectContaining({
      body: {
        refresh_token: initialA.refresh_token,
        installation_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      },
    }),
  );
});

test('an authorized passenger trip switch rotates identity without purging the stable account', async () => {
  await activateSession(initialA);
  mockClearNamespaceSecrets.mockClear();
  mockDeleteAccountDatabase.mockClear();
  mockDeleteVaultNamespace.mockClear();
  mockApiRequest.mockImplementation(async (path: string, options?: { body?: unknown }) => {
    if (path === '/mobile/auth/passenger/trip/switch') {
      expect(options?.body).toEqual({
        group_id: '55555555-5555-4555-8555-555555555555',
        installation_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      });
      return switchedA;
    }
    throw new Error(`Unexpected API request: ${path}`);
  });

  await expect(
    switchPassengerTripSession('55555555-5555-4555-8555-555555555555'),
  ).resolves.toMatchObject({
    sessionId: sessionA,
    principal: { id: passengerASecondTrip, accountId: passengerA, agencyId: agencyA },
  });
  expect(mockSecureState.activeNamespace).toBe(namespaceA);
  expect(mockSecureState.refreshTokens.get(namespaceA)).toBe(switchedA.refresh_token);
  expect(mockClearNamespaceSecrets).not.toHaveBeenCalled();
  expect(mockDeleteAccountDatabase).not.toHaveBeenCalled();
  expect(mockDeleteVaultNamespace).not.toHaveBeenCalled();
  expect(mockDatabaseRun).toHaveBeenCalledWith(
    namespaceA,
    expect.stringContaining('DELETE FROM users'),
    namespaceA,
    passengerA,
    passengerASecondTrip,
  );
});
