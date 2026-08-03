import { z } from 'zod';

import { ApiError, apiRequest, registerRefreshHandler } from '@/core/api/client';
import { PrincipalSchema, TokenResponseSchema, type TokenResponse } from '@/core/api/contracts';
import { demoPrincipal, isDemoPrincipal, seedDemoAccount } from '@/core/demo/demo-data';
import { assertDemoMode, isDemoMode } from '@/core/demo/demo-mode';
import {
  deleteAccountDatabase,
  openAccountDatabase,
  withAccountTransaction,
} from '@/core/storage/database';
import {
  clearLocalCleanupPending,
  clearNamespaceAuthentication,
  clearNamespaceSecrets,
  getActiveNamespace,
  getPendingLocalCleanups,
  getRefreshToken,
  markLocalCleanupPending,
  setActiveNamespace,
  setRefreshToken,
} from '@/core/storage/secure-store';
import { initializeFreshInstallGuard } from '@/core/storage/installation-guard';
import {
  beginVaultNamespacePurge,
  deleteVaultNamespace,
  finishVaultNamespacePurge,
} from '@/core/storage/vault';
import {
  beginRequiredPreparation,
  cancelRequiredPreparation,
} from '@/core/sync/required-preparation-lease';
import { useSelectedTripStore } from '@/features/trips/state/selected-trip-store';

import {
  principalAccountNamespace,
  type MobileRole,
  type MobileSession,
} from './types';
import {
  captureAuthenticationSnapshot,
  invalidateAuthenticationBoundary,
  isAuthenticationEpochCurrent,
  isAuthenticationSnapshotCurrent,
  type AuthenticationSnapshot,
  useSessionStore,
} from './session-store';
import { offlineSessionFromRow, shouldPurgePreviousNamespace } from './offline-session';

function mapSession(tokens: TokenResponse): MobileSession {
  return {
    accessToken: tokens.access_token,
    accessTokenExpiresAt: tokens.access_token_expires_at,
    refreshTokenExpiresAt: tokens.refresh_token_expires_at,
    sessionId: tokens.session_id,
    networkMode: 'online',
    principal: {
      id: tokens.principal.id,
      accountId: tokens.principal.account_id,
      principalType: tokens.principal.principal_type,
      agencyId: tokens.principal.agency_id,
      passengerId: tokens.principal.passenger_id ?? null,
      displayName: tokens.principal.display_name,
      email: tokens.principal.email,
      phoneNumber: tokens.principal.phone_number,
      forcePasswordChange: tokens.principal.force_password_change,
    },
  };
}

async function persistSessionRow(session: MobileSession, namespace: string): Promise<void> {
  const database = await openAccountDatabase(namespace);
  await withAccountTransaction(database, async (transaction) => {
    // A passenger identity can rotate when the same authenticated account
    // changes trips. Keep exactly one principal snapshot for the stable account
    // boundary so an offline restart can never select a stale identity row.
    await transaction.runAsync(
      `DELETE FROM users
        WHERE account_namespace = ? AND account_id = ? AND id <> ?`,
      namespace,
      session.principal.accountId,
      session.principal.id,
    );
    await transaction.runAsync(
      `INSERT INTO users
        (id, account_id, account_namespace, agency_id, principal_type, passenger_id, display_name, email, phone_number, updated_at,
         session_id, access_token_expires_at, refresh_token_expires_at, force_password_change)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         account_id = excluded.account_id,
         account_namespace = excluded.account_namespace,
         agency_id = excluded.agency_id,
         principal_type = excluded.principal_type,
         passenger_id = excluded.passenger_id,
         display_name = excluded.display_name,
         email = excluded.email,
         phone_number = excluded.phone_number,
         updated_at = excluded.updated_at,
         session_id = excluded.session_id,
         access_token_expires_at = excluded.access_token_expires_at,
         refresh_token_expires_at = excluded.refresh_token_expires_at,
         force_password_change = excluded.force_password_change`,
      session.principal.id,
      session.principal.accountId,
      namespace,
      session.principal.agencyId,
      session.principal.principalType,
      session.principal.passengerId ?? null,
      session.principal.displayName,
      session.principal.email,
      session.principal.phoneNumber,
      new Date().toISOString(),
      session.sessionId,
      session.accessTokenExpiresAt,
      session.refreshTokenExpiresAt,
      session.principal.forcePasswordChange ? 1 : 0,
    );
  });
}

export async function refreshSessionPrincipal(): Promise<MobileSession | null> {
  const requestSession = useSessionStore.getState().session;
  if (!requestSession || !requestSession.accessToken) return requestSession;
  const principal = await apiRequest('/mobile/me', { schema: PrincipalSchema });
  // A 401 response can rotate the access token while this request is in flight. Re-read the
  // active session so profile enrichment never restores a stale token. A concurrent account,
  // role or device-session switch is a security-boundary change and must fail closed.
  const current = useSessionStore.getState().session;
  if (
    !current ||
    current.sessionId !== requestSession.sessionId ||
    current.principal.id !== requestSession.principal.id ||
    current.principal.accountId !== requestSession.principal.accountId ||
    current.principal.agencyId !== requestSession.principal.agencyId ||
    current.principal.principalType !== requestSession.principal.principalType
  ) {
    throw new Error('The active mobile session changed while confirming this account.');
  }
  if (
    principal.id !== current.principal.id ||
    principal.account_id !== current.principal.accountId ||
    principal.agency_id !== current.principal.agencyId ||
    principal.principal_type !== current.principal.principalType ||
    (
      current.principal.principalType === 'passenger'
      && current.principal.passengerId != null
      && principal.passenger_id !== current.principal.passengerId
    )
  ) {
    throw new Error('The refreshed mobile identity did not match this session.');
  }
  const updated: MobileSession = {
    ...current,
    principal: {
      id: principal.id,
      accountId: principal.account_id,
      principalType: principal.principal_type,
      agencyId: principal.agency_id,
      passengerId: principal.passenger_id ?? null,
      displayName: principal.display_name,
      email: principal.email,
      phoneNumber: principal.phone_number,
      forcePasswordChange: principal.force_password_change,
    },
  };
  const profileUnchanged =
    updated.principal.displayName === current.principal.displayName &&
    updated.principal.email === current.principal.email &&
    updated.principal.phoneNumber === current.principal.phoneNumber &&
    updated.principal.passengerId === current.principal.passengerId &&
    updated.principal.forcePasswordChange === current.principal.forcePasswordChange;
  if (profileUnchanged) return current;

  const namespace = principalAccountNamespace(updated.principal);
  await persistSessionRow(updated, namespace);
  useSessionStore.getState().setSession(updated);
  return updated;
}

function assertAuthenticationEpoch(epoch: number): void {
  if (!isAuthenticationEpochCurrent(epoch)) {
    throw new Error('The active mobile authentication context changed.');
  }
}

function namespaceForSession(session: MobileSession): string {
  return principalAccountNamespace(session.principal);
}

async function retryPendingCleanupForNamespace(namespace: string): Promise<void> {
  if ((await getPendingLocalCleanups()).includes(namespace)) {
    await purgeLocalSession(namespace);
  }
}

async function retryPendingLocalCleanups(): Promise<Set<string>> {
  for (const namespace of await getPendingLocalCleanups()) {
    // A failed cleanup remains durably marked and authentication was already
    // revoked. Do not block an unrelated account from reaching the login shell.
    await purgeLocalSession(namespace).catch(() => undefined);
  }
  return new Set(await getPendingLocalCleanups());
}

async function activateBoundarySession(
  tokens: TokenResponse,
  authenticationEpoch: number,
): Promise<MobileSession> {
  const session = mapSession(tokens);
  const namespace = namespaceForSession(session);
  let preparationStarted = false;

  assertAuthenticationEpoch(authenticationEpoch);
  await retryPendingCleanupForNamespace(namespace);
  assertAuthenticationEpoch(authenticationEpoch);
  const previousNamespace = await getActiveNamespace();
  assertAuthenticationEpoch(authenticationEpoch);
  if (shouldPurgePreviousNamespace(previousNamespace, namespace)) {
    await purgeLocalSession(previousNamespace);
    assertAuthenticationEpoch(authenticationEpoch);
  }

  try {
    await setRefreshToken(namespace, tokens.refresh_token);
    assertAuthenticationEpoch(authenticationEpoch);
    await setActiveNamespace(namespace);
    assertAuthenticationEpoch(authenticationEpoch);
    await persistSessionRow(session, namespace);
    assertAuthenticationEpoch(authenticationEpoch);
    beginRequiredPreparation(session.sessionId);
    preparationStarted = true;
    useSessionStore.getState().setSession(session);
    return session;
  } catch (error) {
    if (preparationStarted) cancelRequiredPreparation(session.sessionId);
    // A failed first local commit must not leave a refresh token pointing at a
    // half-created database. The next launch starts from a clean namespace and
    // the server-issued session expires/revokes independently.
    if (isAuthenticationEpochCurrent(authenticationEpoch)) {
      await purgeLocalSession(namespace).catch(() => undefined);
    }
    throw error;
  }
}

export async function activateSession(tokens: TokenResponse): Promise<MobileSession> {
  const authenticationEpoch = invalidateAuthenticationBoundary();
  return activateBoundarySession(tokens, authenticationEpoch);
}

export async function switchPassengerTripSession(groupId: string): Promise<MobileSession> {
  if (!z.string().uuid().safeParse(groupId).success) {
    throw new Error('The selected trip identity is invalid.');
  }
  const before = useSessionStore.getState().session;
  if (
    !before ||
    before.networkMode !== 'online' ||
    before.principal.principalType !== 'passenger'
  ) {
    throw new Error('An online passenger session is required to switch trips.');
  }
  const expectedNamespace = namespaceForSession(before);
  const tokens = await apiRequest('/mobile/auth/passenger/trip/switch', {
    method: 'POST',
    schema: TokenResponseSchema,
    body: { group_id: groupId },
  });

  // The API client already rejects an explicit logout/account-boundary change
  // while the request is in flight. Re-read the session to also accept a normal
  // refresh rotation, while denying a competing role/device/account switch.
  const current = useSessionStore.getState().session;
  if (
    !current ||
    current.sessionId !== before.sessionId ||
    current.principal.accountId !== before.principal.accountId ||
    current.principal.agencyId !== before.principal.agencyId ||
    current.principal.principalType !== 'passenger' ||
    namespaceForSession(current) !== expectedNamespace
  ) {
    throw new Error('The active mobile session changed while switching trips.');
  }

  const switched = mapSession(tokens);
  if (
    switched.sessionId !== current.sessionId ||
    switched.principal.accountId !== current.principal.accountId ||
    switched.principal.agencyId !== current.principal.agencyId ||
    switched.principal.principalType !== 'passenger' ||
    namespaceForSession(switched) !== expectedNamespace
  ) {
    throw new Error('The switched passenger identity did not match this account.');
  }

  const authenticationEpoch = invalidateAuthenticationBoundary();
  try {
    assertAuthenticationEpoch(authenticationEpoch);
    if ((await getActiveNamespace()) !== expectedNamespace) {
      throw new Error('The active account changed while switching trips.');
    }
    assertAuthenticationEpoch(authenticationEpoch);
    // Store the newly rotated refresh token before exposing the server-selected
    // identity. A crash can recover by refreshing this same stable account.
    await setRefreshToken(expectedNamespace, tokens.refresh_token);
    assertAuthenticationEpoch(authenticationEpoch);
    await persistSessionRow(switched, expectedNamespace);
    assertAuthenticationEpoch(authenticationEpoch);
    beginRequiredPreparation(switched.sessionId);
    useSessionStore.getState().setSession(switched);
    return switched;
  } catch (error) {
    if (isAuthenticationEpochCurrent(authenticationEpoch)) {
      cancelRequiredPreparation(switched.sessionId);
      useSessionStore.getState().clear();
      useSelectedTripStore.getState().clear();
    }
    throw error;
  }
}

export async function activateDemoSession(role: MobileRole): Promise<MobileSession> {
  assertDemoMode();
  const authenticationEpoch = invalidateAuthenticationBoundary();
  const principal = demoPrincipal(role);
  const namespace = principalAccountNamespace(principal);
  assertAuthenticationEpoch(authenticationEpoch);
  await retryPendingCleanupForNamespace(namespace);
  assertAuthenticationEpoch(authenticationEpoch);
  const previousNamespace = await getActiveNamespace();
  assertAuthenticationEpoch(authenticationEpoch);
  if (shouldPurgePreviousNamespace(previousNamespace, namespace)) {
    await purgeLocalSession(previousNamespace);
    assertAuthenticationEpoch(authenticationEpoch);
  }

  const now = Date.now();
  const session: MobileSession = {
    accessToken: null,
    accessTokenExpiresAt: new Date(now + 24 * 60 * 60_000).toISOString(),
    refreshTokenExpiresAt: new Date(now + 30 * 24 * 60 * 60_000).toISOString(),
    sessionId: `local-demo-${role}`,
    networkMode: 'offline',
    principal,
  };
  let preparationStarted = false;

  try {
    await setActiveNamespace(namespace);
    assertAuthenticationEpoch(authenticationEpoch);
    await persistSessionRow(session, namespace);
    assertAuthenticationEpoch(authenticationEpoch);
    const database = await openAccountDatabase(namespace);
    assertAuthenticationEpoch(authenticationEpoch);
    await seedDemoAccount(database, { namespace, principal });
    assertAuthenticationEpoch(authenticationEpoch);
    beginRequiredPreparation(session.sessionId);
    preparationStarted = true;
    useSessionStore.getState().setSession(session);
    return session;
  } catch (error) {
    if (preparationStarted) cancelRequiredPreparation(session.sessionId);
    if (isAuthenticationEpochCurrent(authenticationEpoch)) {
      await purgeLocalSession(namespace).catch(() => undefined);
    }
    throw error;
  }
}

async function activateRefreshedSession(
  tokens: TokenResponse,
  snapshot: AuthenticationSnapshot,
  expectedNamespace: string,
  expectedSession: MobileSession | null,
): Promise<string | null> {
  const session = mapSession(tokens);
  if (
    namespaceForSession(session) !== expectedNamespace ||
    (expectedSession !== null &&
      (session.sessionId !== expectedSession.sessionId ||
        session.principal.principalType !== expectedSession.principal.principalType))
  ) {
    throw new Error('The refreshed mobile identity did not match this session.');
  }
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  if ((await getActiveNamespace()) !== expectedNamespace) return null;
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;

  // Refreshing an existing device session never changes the active namespace.
  // Keeping activation as the final synchronous state change prevents a delayed
  // response from reviving an account after logout or account switching.
  await setRefreshToken(expectedNamespace, tokens.refresh_token);
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  await persistSessionRow(session, expectedNamespace);
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  if ((await getActiveNamespace()) !== expectedNamespace) return null;
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  useSessionStore.getState().setSession(session);
  return tokens.access_token;
}

async function rotateFromStoredRefresh(
  snapshot: AuthenticationSnapshot,
): Promise<string | null> {
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  const namespace = await getActiveNamespace();
  if (!namespace) return null;
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  const expectedSession = useSessionStore.getState().session;
  if (expectedSession && namespaceForSession(expectedSession) !== namespace) return null;
  const refreshToken = await getRefreshToken(namespace);
  if (!refreshToken) return null;
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;

  try {
    const tokens = await apiRequest('/mobile/auth/refresh', {
      method: 'POST',
      authenticated: false,
      retryAuthentication: false,
      schema: TokenResponseSchema,
      body: { refresh_token: refreshToken },
    });
    if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
    return await activateRefreshedSession(tokens, snapshot, namespace, expectedSession);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
      const invalidationEpoch = invalidateAuthenticationBoundary();
      if ((await getActiveNamespace()) === namespace && isAuthenticationEpochCurrent(invalidationEpoch)) {
        await purgeLocalSession(namespace);
      }
      return null;
    }
    throw error;
  }
}

export async function bootstrapSession(): Promise<void> {
  try {
    await initializeFreshInstallGuard();
    const pendingCleanups = await retryPendingLocalCleanups();
    const activeNamespace = await getActiveNamespace();
    if (activeNamespace && pendingCleanups.has(activeNamespace)) {
      // A durable logout tombstone always outranks stored refresh/offline
      // state. Best-effort credential deletion is repeated here, but even a
      // second keychain failure must never restore the account.
      await clearNamespaceAuthentication(activeNamespace).catch(() => undefined);
      invalidateAuthenticationBoundary();
      useSelectedTripStore.getState().clear();
      useSessionStore.getState().clear();
      throw new Error('Previous account cleanup is still pending.');
    }
    const bootstrapSnapshot = captureAuthenticationSnapshot();
    if (isDemoMode()) {
      registerRefreshHandler(async () => null);
      const namespace = activeNamespace;
      if (!isAuthenticationSnapshotCurrent(bootstrapSnapshot)) return;
      const offline = namespace ? await loadOfflineSession(namespace) : null;
      if (!isAuthenticationSnapshotCurrent(bootstrapSnapshot)) return;
      if (offline && isDemoPrincipal(offline.principal)) {
        useSessionStore.getState().setSession(offline);
      } else {
        if (namespace) await purgeLocalSession(namespace).catch(() => undefined);
        if (isAuthenticationSnapshotCurrent(bootstrapSnapshot)) {
          invalidateAuthenticationBoundary();
          useSessionStore.getState().clear();
        }
      }
      return;
    }
    registerRefreshHandler(rotateFromStoredRefresh);

    const namespace = activeNamespace;
    if (!isAuthenticationSnapshotCurrent(bootstrapSnapshot)) return;
    try {
      const token = await rotateFromStoredRefresh(bootstrapSnapshot);
      if (!token && isAuthenticationSnapshotCurrent(bootstrapSnapshot)) {
        invalidateAuthenticationBoundary();
        useSessionStore.getState().clear();
      }
    } catch {
      if (!isAuthenticationSnapshotCurrent(bootstrapSnapshot)) return;
      // A network failure may use a verified encrypted offline session. If the
      // native database itself is unavailable, propagate to the outer
      // bootstrap boundary so the app offers an explicit retry instead of
      // silently pretending that no account exists.
      const offline = namespace ? await loadOfflineSession(namespace) : null;
      if (!isAuthenticationSnapshotCurrent(bootstrapSnapshot)) return;
      if (offline) {
        useSessionStore.getState().setSession(offline);
      } else {
        invalidateAuthenticationBoundary();
        useSessionStore.getState().clear();
      }
    }
  } catch (error) {
    // A native bootstrap failure before the offline fallback is available must
    // never strand the router in `booting`. Preserve a valid already-active
    // foreground session, but fail closed for an unresolved/anonymous boundary.
    if (useSessionStore.getState().status !== 'authenticated') {
      invalidateAuthenticationBoundary();
      useSelectedTripStore.getState().clear();
      useSessionStore.getState().failBootstrap();
    }
    throw error;
  }
}

async function loadOfflineSession(namespace: string): Promise<MobileSession | null> {
  const database = await openAccountDatabase(namespace);
  const row = await database.getFirstAsync<{
    id: string;
    account_id: string;
    agency_id: string;
    principal_type: MobileSession['principal']['principalType'];
    passenger_id: string | null;
    display_name: string;
    email: string | null;
    phone_number: string | null;
    session_id: string;
    access_token_expires_at: string;
    refresh_token_expires_at: string;
    force_password_change: number;
  }>(
    `SELECT id, account_id, agency_id, principal_type, passenger_id, display_name, email, phone_number, session_id,
            access_token_expires_at, refresh_token_expires_at, force_password_change
       FROM users WHERE account_namespace = ? LIMIT 1`,
    namespace,
  );
  return offlineSessionFromRow(namespace, row, Date.now());
}

export async function logoutSession(): Promise<void> {
  const activeSession = useSessionStore.getState().session;
  const derivedNamespace = activeSession ? namespaceForSession(activeSession) : null;
  invalidateAuthenticationBoundary();
  if (activeSession?.sessionId) cancelRequiredPreparation(activeSession.sessionId);
  // Authentication must disappear synchronously before any SecureStore or
  // network operation that can reject or stall.
  useSessionStore.getState().clear();
  useSelectedTripStore.getState().clear();

  let cleanupError: unknown;
  let storedNamespace: string | null = null;
  if (!derivedNamespace) {
    try {
      storedNamespace = await getActiveNamespace();
    } catch (error) {
      cleanupError = error;
    }
  }
  // The authenticated principal is the stable ownership boundary. A stale or
  // concurrently changed SecureStore marker must never redirect this cleanup.
  const namespace = derivedNamespace ?? storedNamespace;
  let refreshToken: string | null = null;
  if (namespace) {
    try {
      refreshToken = await getRefreshToken(namespace);
    } catch (error) {
      cleanupError ??= error;
    }
  }
  try {
    if (activeSession?.accessToken && !isDemoMode()) {
      await apiRequest('/mobile/auth/logout', {
        method: 'POST',
        schema: z.null(),
        body: refreshToken ? { refresh_token: refreshToken } : {},
        authenticated: false,
        retryAuthentication: false,
        headers: { Authorization: `Bearer ${activeSession.accessToken}` },
      });
    }
  } catch {
    // Local revocation is mandatory even when the network is unavailable. The server-side
    // token will expire and can also be revoked from the dashboard.
  }
  if (namespace) {
    try {
      await purgeLocalSession(namespace);
    } catch (error) {
      cleanupError ??= error;
    }
  }
  if (cleanupError) throw cleanupError;
}

export async function purgeLocalSession(namespace: string): Promise<void> {
  const activeSession = useSessionStore.getState().session;
  if (activeSession && namespaceForSession(activeSession) === namespace) {
    useSessionStore.getState().clear();
    useSelectedTripStore.getState().clear();
  } else if (!activeSession) {
    useSelectedTripStore.getState().clear();
  }
  let markerError: unknown;
  try {
    await markLocalCleanupPending(namespace);
  } catch (error) {
    markerError = error;
  }

  let fenceStarted = false;
  let databaseDeleted = false;
  let vaultDeleted = false;
  let secretsCleared = false;
  let cleanupError: unknown;
  try {
    await beginVaultNamespacePurge(namespace);
    fenceStarted = true;
  } catch (error) {
    cleanupError = error;
  }

  if (fenceStarted) {
    try {
      await deleteAccountDatabase(namespace);
      databaseDeleted = true;
    } catch (error) {
      cleanupError ??= error;
    }
    try {
      await deleteVaultNamespace(namespace);
      vaultDeleted = true;
    } catch (error) {
      cleanupError ??= error;
    }
  }

  if (databaseDeleted && vaultDeleted) {
    try {
      await clearNamespaceSecrets(namespace);
      secretsCleared = true;
    } catch (error) {
      cleanupError ??= error;
    }
  } else {
    try {
      // Revoke authentication immediately but retain the database/vault keys.
      // The durable cleanup marker can then retry after process death without
      // turning recoverable ciphertext into an unreadable orphan.
      await clearNamespaceAuthentication(namespace);
    } catch (error) {
      cleanupError ??= error;
    }
  }

  const acknowledged = databaseDeleted && vaultDeleted && secretsCleared;
  if (acknowledged) {
    try {
      await clearLocalCleanupPending(namespace);
    } catch (error) {
      cleanupError ??= error;
    }
  }
  if (fenceStarted) finishVaultNamespacePurge(namespace, acknowledged);
  if (cleanupError) throw cleanupError;
  if (markerError && !acknowledged) throw markerError;
}
