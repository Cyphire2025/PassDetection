import type { TokenResponse } from '@/core/api/contracts';
import { ApiError } from '@/core/api/client';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  activateSession,
  bootstrapSession,
  logoutSession,
  switchPassengerTripSession,
} from '../session-service';
import {
  captureAuthenticationSnapshot,
  invalidateAuthenticationBoundary,
  useSessionStore,
} from '../session-store';
import { accountNamespace } from '../types';

type RegisteredRefreshHandler = (
  snapshot: Readonly<{ epoch: number; accessToken: string | null }>,
) => Promise<string | null>;

const mockSecureState: {
  activeNamespace: string | null;
  pendingCleanups: Set<string>;
  refreshTokens: Map<string, string>;
} = {
  activeNamespace: null,
  pendingCleanups: new Set(),
  refreshTokens: new Map(),
};
let mockRefreshHandler: RegisteredRefreshHandler | null = null;

const mockApiRequest = jest.fn();
const mockInitializeFreshInstallGuard = jest.fn(async () => undefined);
const mockSetRefreshToken = jest.fn(async (namespace: string, token: string) => {
  mockSecureState.refreshTokens.set(namespace, token);
});
const mockSetActiveNamespace = jest.fn(async (namespace: string) => {
  mockSecureState.activeNamespace = namespace;
});
const mockGetActiveNamespace = jest.fn(async () => mockSecureState.activeNamespace);
const mockGetRefreshToken = jest.fn(async (namespace: string) =>
  mockSecureState.refreshTokens.get(namespace) ?? null,
);
const mockClearNamespaceSecrets = jest.fn(async (namespace: string) => {
  mockSecureState.refreshTokens.delete(namespace);
  if (mockSecureState.activeNamespace === namespace) mockSecureState.activeNamespace = null;
});
const mockClearNamespaceAuthentication = jest.fn(async (namespace: string) => {
  mockSecureState.refreshTokens.delete(namespace);
  if (mockSecureState.activeNamespace === namespace) mockSecureState.activeNamespace = null;
});
const mockGetPendingLocalCleanups = jest.fn(async () => [...mockSecureState.pendingCleanups]);
const mockMarkLocalCleanupPending = jest.fn(async (namespace: string) => {
  mockSecureState.pendingCleanups.add(namespace);
});
const mockClearLocalCleanupPending = jest.fn(async (namespace: string) => {
  mockSecureState.pendingCleanups.delete(namespace);
});
const mockDeleteAccountDatabase = jest.fn(async (_namespace: string) => undefined);
const mockBeginVaultNamespacePurge = jest.fn(async (_namespace: string) => undefined);
const mockDeleteVaultNamespace = jest.fn(async (_namespace: string) => undefined);
const mockFinishVaultNamespacePurge = jest.fn(
  (_namespace: string, _acknowledged: boolean) => undefined,
);
const mockDatabaseRun = jest.fn(async (..._args: unknown[]) => undefined);
const mockOpenAccountDatabase = jest.fn(async (namespace: string) => ({
  __namespace: namespace,
  runAsync: (...args: unknown[]) => mockDatabaseRun(namespace, ...args),
  getFirstAsync: jest.fn(async () => null),
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
  getActiveNamespace: () => mockGetActiveNamespace(),
  getRefreshToken: (namespace: string) => mockGetRefreshToken(namespace),
  setRefreshToken: (...args: [string, string]) => mockSetRefreshToken(...args),
  setActiveNamespace: (...args: [string]) => mockSetActiveNamespace(...args),
  getPendingLocalCleanups: () => mockGetPendingLocalCleanups(),
  markLocalCleanupPending: (...args: [string]) => mockMarkLocalCleanupPending(...args),
  clearLocalCleanupPending: (...args: [string]) => mockClearLocalCleanupPending(...args),
  clearNamespaceAuthentication: (...args: [string]) => (
    mockClearNamespaceAuthentication(...args)
  ),
  clearNamespaceSecrets: (...args: [string]) => mockClearNamespaceSecrets(...args),
}));

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: (namespace: string) => mockOpenAccountDatabase(namespace),
  withAccountTransaction: jest.fn(async (
    database: { __namespace: string; runAsync: (...args: unknown[]) => Promise<void> },
    task: (transaction: { runAsync: (...args: unknown[]) => Promise<void> }) => Promise<void>,
  ) => task({
    runAsync: (...args: unknown[]) => mockDatabaseRun(database.__namespace, ...args),
  })),
  deleteAccountDatabase: (...args: [string]) => mockDeleteAccountDatabase(...args),
}));

jest.mock('@/core/storage/vault', () => ({
  beginVaultNamespacePurge: (...args: [string]) => mockBeginVaultNamespacePurge(...args),
  deleteVaultNamespace: (...args: [string]) => mockDeleteVaultNamespace(...args),
  finishVaultNamespacePurge: (...args: [string, boolean]) => (
    mockFinishVaultNamespacePurge(...args)
  ),
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

beforeEach(async () => {
  invalidateAuthenticationBoundary();
  useSessionStore.getState().clear();
  useSelectedTripStore.getState().clear();
  mockSecureState.activeNamespace = null;
  mockSecureState.pendingCleanups.clear();
  mockSecureState.refreshTokens.clear();
  mockRefreshHandler = null;
  mockApiRequest.mockReset();
  mockInitializeFreshInstallGuard.mockReset();
  mockInitializeFreshInstallGuard.mockResolvedValue(undefined);
  mockApiRequest.mockImplementation(async (path: string) => {
    if (path === '/mobile/auth/logout') return null;
    throw new Error(`Unexpected API request: ${path}`);
  });
  mockSetRefreshToken.mockClear();
  mockSetActiveNamespace.mockClear();
  mockGetActiveNamespace.mockReset();
  mockGetActiveNamespace.mockImplementation(async () => mockSecureState.activeNamespace);
  mockGetRefreshToken.mockReset();
  mockGetRefreshToken.mockImplementation(async (namespace: string) =>
    mockSecureState.refreshTokens.get(namespace) ?? null,
  );
  mockClearNamespaceSecrets.mockClear();
  mockClearNamespaceAuthentication.mockClear();
  mockGetPendingLocalCleanups.mockClear();
  mockMarkLocalCleanupPending.mockClear();
  mockClearLocalCleanupPending.mockClear();
  mockDeleteAccountDatabase.mockClear();
  mockBeginVaultNamespacePurge.mockClear();
  mockBeginVaultNamespacePurge.mockResolvedValue(undefined);
  mockDeleteVaultNamespace.mockClear();
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
  expect(mockClearNamespaceSecrets).toHaveBeenCalledWith(namespaceA);
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

test('logout waits for namespace writes before deleting the database, vault and keys', async () => {
  await activateSession(initialA);
  const oldWriteFinished = deferred<void>();
  const fenceStarted = deferred<void>();
  mockBeginVaultNamespacePurge.mockImplementationOnce(async () => {
    fenceStarted.resolve();
    await oldWriteFinished.promise;
  });

  const logout = logoutSession();
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

test('logout clears credentials and stays fenced when database and vault deletion fail', async () => {
  await activateSession(initialA);
  mockDeleteAccountDatabase.mockRejectedValueOnce(new Error('database delete failed'));
  mockDeleteVaultNamespace.mockRejectedValueOnce(new Error('vault delete failed'));

  await expect(logoutSession()).rejects.toThrow('database delete failed');

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

test('a failed logout cleanup is retried durably after restart before the account can reopen', async () => {
  await activateSession(initialA);
  mockDeleteAccountDatabase.mockRejectedValueOnce(new Error('database delete failed'));

  await expect(logoutSession()).rejects.toThrow('database delete failed');
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

test('logout clears authentication immediately and does not depend on the active namespace lookup', async () => {
  await activateSession(initialA);
  useSelectedTripStore.getState().selectTrip('55555555-5555-4555-8555-555555555555');
  mockGetActiveNamespace.mockClear();
  mockGetActiveNamespace.mockRejectedValueOnce(new Error('keychain read failed'));

  const logout = logoutSession();
  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
  expect(useSelectedTripStore.getState().tripId).toBeNull();
  await expect(logout).resolves.toBeUndefined();

  expect(mockGetActiveNamespace).not.toHaveBeenCalled();
  expect(mockDeleteAccountDatabase).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).toHaveBeenCalledWith(namespaceA);
});

test('logout remains anonymous and purges local data when refresh-token lookup fails', async () => {
  await activateSession(initialA);
  useSelectedTripStore.getState().selectTrip('55555555-5555-4555-8555-555555555555');
  mockGetRefreshToken.mockRejectedValueOnce(new Error('refresh token read failed'));

  const logout = logoutSession();
  expect(useSessionStore.getState()).toMatchObject({ status: 'anonymous', session: null });
  expect(useSelectedTripStore.getState().tripId).toBeNull();
  await expect(logout).rejects.toThrow('refresh token read failed');

  expect(mockApiRequest).toHaveBeenCalledWith(
    '/mobile/auth/logout',
    expect.objectContaining({
      authenticated: false,
      retryAuthentication: false,
      headers: { Authorization: `Bearer ${initialA.access_token}` },
    }),
  );
  expect(mockDeleteAccountDatabase).toHaveBeenCalledWith(namespaceA);
  expect(mockDeleteVaultNamespace).toHaveBeenCalledWith(namespaceA);
  expect(mockClearNamespaceSecrets).toHaveBeenCalledWith(namespaceA);
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
});

test('an authorized passenger trip switch rotates identity without purging the stable account', async () => {
  await activateSession(initialA);
  mockClearNamespaceSecrets.mockClear();
  mockDeleteAccountDatabase.mockClear();
  mockDeleteVaultNamespace.mockClear();
  mockApiRequest.mockImplementation(async (path: string, options?: { body?: unknown }) => {
    if (path === '/mobile/auth/passenger/trip/switch') {
      expect(options?.body).toEqual({ group_id: '55555555-5555-4555-8555-555555555555' });
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
