import { z } from 'zod';

import { ApiError, apiRequest, registerRefreshHandler } from '@/core/api/client';
import { TokenResponseSchema, type TokenResponse } from '@/core/api/contracts';
import { demoPrincipal, isDemoPrincipal, seedDemoAccount } from '@/core/demo/demo-data';
import { assertDemoMode, isDemoMode } from '@/core/demo/demo-mode';
import { deleteAccountDatabase, openAccountDatabase } from '@/core/storage/database';
import {
  clearNamespaceSecrets,
  getActiveNamespace,
  getRefreshToken,
  initializeFreshInstallGuard,
  setActiveNamespace,
  setRefreshToken,
} from '@/core/storage/secure-store';
import { deleteVaultNamespace } from '@/core/storage/vault';

import { accountNamespace, type MobileRole, type MobileSession } from './types';
import { useSessionStore } from './session-store';
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
      principalType: tokens.principal.principal_type,
      agencyId: tokens.principal.agency_id,
      displayName: tokens.principal.display_name,
      forcePasswordChange: tokens.principal.force_password_change,
    },
  };
}

async function persistSessionRow(session: MobileSession, namespace: string): Promise<void> {
  const database = await openAccountDatabase(namespace);
  await database.runAsync(
    `INSERT INTO users
      (id, account_namespace, agency_id, principal_type, display_name, updated_at,
       session_id, access_token_expires_at, refresh_token_expires_at, force_password_change)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET
       account_namespace = excluded.account_namespace,
       agency_id = excluded.agency_id,
       principal_type = excluded.principal_type,
       display_name = excluded.display_name,
       updated_at = excluded.updated_at,
       session_id = excluded.session_id,
       access_token_expires_at = excluded.access_token_expires_at,
       refresh_token_expires_at = excluded.refresh_token_expires_at,
       force_password_change = excluded.force_password_change`,
    session.principal.id,
    namespace,
    session.principal.agencyId,
    session.principal.principalType,
    session.principal.displayName,
    new Date().toISOString(),
    session.sessionId,
    session.accessTokenExpiresAt,
    session.refreshTokenExpiresAt,
    session.principal.forcePasswordChange ? 1 : 0,
  );
}

export async function activateSession(tokens: TokenResponse): Promise<MobileSession> {
  const session = mapSession(tokens);
  const namespace = accountNamespace({
    agencyId: session.principal.agencyId,
    principalId: session.principal.id,
  });

  const previousNamespace = await getActiveNamespace();
  if (shouldPurgePreviousNamespace(previousNamespace, namespace)) {
    await purgeLocalSession(previousNamespace);
  }

  await setRefreshToken(namespace, tokens.refresh_token);
  await setActiveNamespace(namespace);
  await persistSessionRow(session, namespace);
  useSessionStore.getState().setSession(session);
  return session;
}

export async function activateDemoSession(role: MobileRole): Promise<MobileSession> {
  assertDemoMode();
  const principal = demoPrincipal(role);
  const namespace = accountNamespace({
    agencyId: principal.agencyId,
    principalId: principal.id,
  });
  const previousNamespace = await getActiveNamespace();
  if (shouldPurgePreviousNamespace(previousNamespace, namespace)) {
    await purgeLocalSession(previousNamespace);
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

  try {
    await setActiveNamespace(namespace);
    await persistSessionRow(session, namespace);
    const database = await openAccountDatabase(namespace);
    await seedDemoAccount(database, { namespace, principal });
    useSessionStore.getState().setSession(session);
    return session;
  } catch (error) {
    await purgeLocalSession(namespace).catch(() => undefined);
    throw error;
  }
}

async function rotateFromStoredRefresh(): Promise<string | null> {
  const namespace = await getActiveNamespace();
  if (!namespace) return null;
  const refreshToken = await getRefreshToken(namespace);
  if (!refreshToken) return null;

  try {
    const tokens = await apiRequest('/mobile/auth/refresh', {
      method: 'POST',
      authenticated: false,
      retryAuthentication: false,
      schema: TokenResponseSchema,
      body: { refresh_token: refreshToken },
    });
    await activateSession(tokens);
    return tokens.access_token;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      await purgeLocalSession(namespace);
      return null;
    }
    throw error;
  }
}

export async function bootstrapSession(): Promise<void> {
  await initializeFreshInstallGuard();
  if (isDemoMode()) {
    registerRefreshHandler(async () => null);
    const namespace = await getActiveNamespace();
    const offline = namespace ? await loadOfflineSession(namespace).catch(() => null) : null;
    if (offline && isDemoPrincipal(offline.principal)) {
      useSessionStore.getState().setSession(offline);
    } else {
      if (namespace) await purgeLocalSession(namespace).catch(() => undefined);
      useSessionStore.getState().clear();
    }
    return;
  }
  registerRefreshHandler(rotateFromStoredRefresh);

  const namespace = await getActiveNamespace();
  try {
    const token = await rotateFromStoredRefresh();
    if (!token) useSessionStore.getState().clear();
  } catch {
    const offline = namespace ? await loadOfflineSession(namespace).catch(() => null) : null;
    if (offline) {
      useSessionStore.getState().setSession(offline);
      useSessionStore.getState().setLocked();
    } else {
      useSessionStore.getState().clear();
    }
  }
}

async function loadOfflineSession(namespace: string): Promise<MobileSession | null> {
  const database = await openAccountDatabase(namespace);
  const row = await database.getFirstAsync<{
    id: string;
    agency_id: string;
    principal_type: MobileSession['principal']['principalType'];
    display_name: string;
    session_id: string;
    access_token_expires_at: string;
    refresh_token_expires_at: string;
    force_password_change: number;
  }>(
    `SELECT id, agency_id, principal_type, display_name, session_id,
            access_token_expires_at, refresh_token_expires_at, force_password_change
       FROM users WHERE account_namespace = ? LIMIT 1`,
    namespace,
  );
  return offlineSessionFromRow(namespace, row, Date.now());
}

export async function logoutSession(): Promise<void> {
  const namespace = await getActiveNamespace();
  const refreshToken = namespace ? await getRefreshToken(namespace) : null;
  try {
    if (useSessionStore.getState().session && !isDemoMode()) {
      await apiRequest('/mobile/auth/logout', {
        method: 'POST',
        schema: z.null(),
        body: refreshToken ? { refresh_token: refreshToken } : {},
      });
    }
  } catch {
    // Local revocation is mandatory even when the network is unavailable. The server-side
    // token will expire and can also be revoked from the dashboard.
  } finally {
    if (namespace) await purgeLocalSession(namespace);
    else useSessionStore.getState().clear();
  }
}

export async function purgeLocalSession(namespace: string): Promise<void> {
  useSessionStore.getState().clear();
  await deleteAccountDatabase(namespace).catch(() => undefined);
  await deleteVaultNamespace(namespace).catch(() => undefined);
  await clearNamespaceSecrets(namespace);
}
