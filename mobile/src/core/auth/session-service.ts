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
  clearOfflineAuthorizationRecord,
  clearNamespaceAuthentication,
  clearNamespaceSecrets,
  getActiveNamespace,
  getInstallationId,
  getOfflineAuthorizationRecord,
  getPendingLocalCleanups,
  getRefreshToken,
  isUnlockedOnlySecureValueAccessAvailable,
  markLocalCleanupPending,
  setActiveNamespace,
  setOfflineAuthorizationRecord,
  setRefreshToken,
} from '@/core/storage/secure-store';
import { initializeFreshInstallGuard } from '@/core/storage/installation-guard';
import {
  beginVaultNamespacePurge,
  deleteVaultNamespace,
  finishVaultNamespacePurge,
  purgeTemporaryViews,
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
import {
  acceptOnlineOfflineAuthorizationLease,
  authorizeStoredOfflineLease,
  clearOfflineAuthorizationBootAnchor,
  OfflineAuthorizationError,
  type OfflineAuthorizationExpectedIdentity,
} from './offline-authorization';

let offlineAuthorizationExpiryTimer: ReturnType<typeof setTimeout> | null = null;

function clearOfflineAuthorizationExpiryTimer(): void {
  if (offlineAuthorizationExpiryTimer !== null) {
    clearTimeout(offlineAuthorizationExpiryTimer);
    offlineAuthorizationExpiryTimer = null;
  }
}

function armOfflineAuthorizationExpiryTimer(
  session: MobileSession,
  namespace: string,
  remainingMs: number,
): void {
  clearOfflineAuthorizationExpiryTimer();
  const boundedDelay = Math.max(0, Math.min(Math.floor(remainingMs), 2_147_483_647));
  offlineAuthorizationExpiryTimer = setTimeout(() => {
    offlineAuthorizationExpiryTimer = null;
    const current = useSessionStore.getState().session;
    if (
      !current
      || current.networkMode !== 'offline'
      || current.sessionId !== session.sessionId
      || namespaceForSession(current) !== namespace
    ) return;

    invalidateAuthenticationBoundary();
    cancelRequiredPreparation(current.sessionId);
    useSessionStore.getState().clear();
    useSelectedTripStore.getState().clear();
    void clearOfflineAuthorizationRecord(namespace).catch(() => undefined);
  }, boundedDelay);
}

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

function expectedOfflineAuthorizationIdentity(
  session: MobileSession,
  installationId: string,
): OfflineAuthorizationExpectedIdentity {
  return {
    installationId,
    sessionId: session.sessionId,
    principalId: session.principal.id,
    accountId: session.principal.accountId,
    agencyId: session.principal.agencyId,
    principalType: session.principal.principalType,
    passengerId: session.principal.passengerId ?? null,
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
  const installationId = await getInstallationId();
  assertAuthenticationEpoch(authenticationEpoch);
  const offlineAuthorization = acceptOnlineOfflineAuthorizationLease(
    tokens.offline_authorization_lease,
    expectedOfflineAuthorizationIdentity(session, installationId),
  );
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
    await setOfflineAuthorizationRecord(namespace, offlineAuthorization.record);
    assertAuthenticationEpoch(authenticationEpoch);
    await setActiveNamespace(namespace);
    assertAuthenticationEpoch(authenticationEpoch);
    await persistSessionRow(session, namespace);
    assertAuthenticationEpoch(authenticationEpoch);
    beginRequiredPreparation(session.sessionId);
    preparationStarted = true;
    clearOfflineAuthorizationExpiryTimer();
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
  const installationId = await getInstallationId();
  const tokens = await apiRequest('/mobile/auth/passenger/trip/switch', {
    method: 'POST',
    schema: TokenResponseSchema,
    body: { group_id: groupId, installation_id: installationId },
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
  const offlineAuthorization = acceptOnlineOfflineAuthorizationLease(
    tokens.offline_authorization_lease,
    expectedOfflineAuthorizationIdentity(switched, installationId),
  );

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
    await setOfflineAuthorizationRecord(expectedNamespace, offlineAuthorization.record);
    assertAuthenticationEpoch(authenticationEpoch);
    await persistSessionRow(switched, expectedNamespace);
    assertAuthenticationEpoch(authenticationEpoch);
    beginRequiredPreparation(switched.sessionId);
    clearOfflineAuthorizationExpiryTimer();
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
    clearOfflineAuthorizationExpiryTimer();
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
  installationId: string,
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
  const offlineAuthorization = acceptOnlineOfflineAuthorizationLease(
    tokens.offline_authorization_lease,
    expectedOfflineAuthorizationIdentity(session, installationId),
  );
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  if ((await getActiveNamespace()) !== expectedNamespace) return null;
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;

  // Refreshing an existing device session never changes the active namespace.
  // Keeping activation as the final synchronous state change prevents a delayed
  // response from reviving an account after logout or account switching.
  await setRefreshToken(expectedNamespace, tokens.refresh_token);
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  // A headless refresh may run while the device is locked. The rotated refresh
  // token and SQLCipher metadata remain available to bounded background sync,
  // but the new offline lease is deliberately not persisted until a foreground
  // refresh can place it under the unlocked-only policy. The previous signed
  // lease remains independently bounded by its own expiry.
  if (isUnlockedOnlySecureValueAccessAvailable()) {
    await setOfflineAuthorizationRecord(expectedNamespace, offlineAuthorization.record);
    if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  }
  await persistSessionRow(session, expectedNamespace);
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  if ((await getActiveNamespace()) !== expectedNamespace) return null;
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
  clearOfflineAuthorizationExpiryTimer();
  useSessionStore.getState().setSession(session);
  return tokens.access_token;
}

type StoredRefreshOperation = Readonly<{
  snapshot: AuthenticationSnapshot;
  promise: Promise<string | null>;
}>;

let storedRefreshInFlight: StoredRefreshOperation | null = null;

function sameAuthenticationBoundary(
  first: AuthenticationSnapshot,
  second: AuthenticationSnapshot,
): boolean {
  return first.epoch === second.epoch && first.accessToken === second.accessToken;
}

async function performStoredRefresh(
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
  const installationId = await getInstallationId();
  if (!isAuthenticationSnapshotCurrent(snapshot)) return null;

  try {
    const tokens = await apiRequest('/mobile/auth/refresh', {
      method: 'POST',
      authenticated: false,
      retryAuthentication: false,
      schema: TokenResponseSchema,
      body: { refresh_token: refreshToken, installation_id: installationId },
    });
    if (!isAuthenticationSnapshotCurrent(snapshot)) return null;
    return await activateRefreshedSession(
      tokens,
      snapshot,
      namespace,
      expectedSession,
      installationId,
    );
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

async function rotateFromStoredRefresh(
  snapshot: AuthenticationSnapshot,
): Promise<string | null> {
  if (
    storedRefreshInFlight
    && sameAuthenticationBoundary(storedRefreshInFlight.snapshot, snapshot)
  ) {
    return storedRefreshInFlight.promise;
  }

  let operation: StoredRefreshOperation;
  const promise = performStoredRefresh(snapshot).finally(() => {
    if (storedRefreshInFlight === operation) storedRefreshInFlight = null;
  });
  operation = { snapshot, promise };
  storedRefreshInFlight = operation;
  return promise;
}

export type SessionBootstrapOptions = Readonly<{
  /**
   * Restore a still-valid encrypted local identity immediately, then validate
   * its refresh token in the background. Native background tasks retain the
   * default blocking mode because they cannot safely synchronize without an
   * online access token.
   */
  validation?: 'wait' | 'background';
  /**
   * A native background task must not touch the unlocked-only offline lease.
   * It performs a blocking online refresh and uses the background-accessible
   * database/refresh-token tier for metadata reconciliation only.
   */
  execution?: 'foreground' | 'native-background';
}>;

export async function bootstrapSession(
  options: SessionBootstrapOptions = {},
): Promise<void> {
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
      const offline = namespace ? await loadOfflineSession(namespace, true) : null;
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
    // Read and verify the encrypted local identity before touching the network.
    // A valid prior session can render its cached shell immediately; the
    // refresh-token exchange still owns online authorization and can revoke the
    // local session asynchronously.
    const mayRestoreOfflineShell = options.execution !== 'native-background'
      && isUnlockedOnlySecureValueAccessAvailable();
    const offline = namespace && mayRestoreOfflineShell
      ? await loadOfflineSession(namespace)
      : null;
    if (!isAuthenticationSnapshotCurrent(bootstrapSnapshot)) return;
    if (offline) useSessionStore.getState().setSession(offline);

    const validateOnlineSession = async (): Promise<void> => {
      try {
        const token = await rotateFromStoredRefresh(bootstrapSnapshot);
        if (!token && isAuthenticationSnapshotCurrent(bootstrapSnapshot)) {
          invalidateAuthenticationBoundary();
          useSessionStore.getState().clear();
        }
      } catch {
        if (!isAuthenticationSnapshotCurrent(bootstrapSnapshot)) return;
        // A network failure may retain only the already-verified encrypted
        // offline session. If no valid offline identity exists, fail closed.
        if (!offline) {
          invalidateAuthenticationBoundary();
          useSessionStore.getState().clear();
        }
      }
    };

    if (offline && options.validation === 'background') {
      void validateOnlineSession();
      return;
    }
    await validateOnlineSession();
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

async function loadOfflineSession(
  namespace: string,
  allowUnsignedDemoSession = false,
): Promise<MobileSession | null> {
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
  const offlineSession = offlineSessionFromRow(namespace, row);
  if (!offlineSession) return null;

  if (allowUnsignedDemoSession) {
    const refreshExpiryMs = Date.parse(offlineSession.refreshTokenExpiresAt);
    return Number.isFinite(refreshExpiryMs) && refreshExpiryMs > Date.now()
      ? offlineSession
      : null;
  }

  const [record, installationId] = await Promise.all([
    getOfflineAuthorizationRecord(namespace),
    getInstallationId(),
  ]);
  if (!record) return null;
  try {
    const authorization = authorizeStoredOfflineLease(
      record,
      expectedOfflineAuthorizationIdentity(offlineSession, installationId),
    );
    await setOfflineAuthorizationRecord(namespace, authorization.record);
    armOfflineAuthorizationExpiryTimer(
      offlineSession,
      namespace,
      authorization.remainingMs,
    );
    return offlineSession;
  } catch (error) {
    if (!(error instanceof OfflineAuthorizationError)) throw error;
    await clearOfflineAuthorizationRecord(namespace).catch(() => undefined);
    clearOfflineAuthorizationBootAnchor(
      expectedOfflineAuthorizationIdentity(offlineSession, installationId),
    );
    return null;
  }
}

export async function logoutSession(): Promise<void> {
  const activeSession = useSessionStore.getState().session;
  const derivedNamespace = activeSession ? namespaceForSession(activeSession) : null;
  invalidateAuthenticationBoundary();
  clearOfflineAuthorizationExpiryTimer();
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
    } catch {
      // The access-token logout still revokes the server session. Failure to
      // read a stale refresh token must not weaken or block local data purge.
    }
  }
  try {
    if (activeSession?.accessToken && !isDemoMode()) {
      const authorization = { Authorization: `Bearer ${activeSession.accessToken}` };
      // Revoke every provider registration owned by this device session before
      // ending it. The logout endpoint remains authoritative and makes the
      // device session ineligible for delivery even if this best-effort call is
      // interrupted or offline.
      await getInstallationId()
        .then((installationId) => apiRequest('/mobile/push/unregister', {
          method: 'POST',
          schema: z.object({
            unregistered: z.boolean(),
            revoked_count: z.number().int().nonnegative(),
          }).strict(),
          body: { installation_id: installationId },
          authenticated: false,
          retryAuthentication: false,
          headers: authorization,
        }))
        .catch(() => undefined);
      await apiRequest('/mobile/auth/logout', {
        method: 'POST',
        schema: z.null(),
        body: refreshToken ? { refresh_token: refreshToken } : {},
        authenticated: false,
        retryAuthentication: false,
        headers: authorization,
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
    clearOfflineAuthorizationExpiryTimer();
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
    await purgeTemporaryViews();
  } catch (error) {
    cleanupError = error;
  }
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
