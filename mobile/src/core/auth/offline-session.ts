import { accountNamespace, type MobileSession } from './types';

export type OfflineSessionRow = {
  id: string;
  agency_id: string;
  principal_type: MobileSession['principal']['principalType'];
  display_name: string;
  session_id: string;
  access_token_expires_at: string;
  refresh_token_expires_at: string;
  force_password_change: number;
};

export function shouldPurgePreviousNamespace(previous: string | null, next: string): previous is string {
  return previous !== null && previous !== next;
}

export function offlineSessionFromRow(
  namespace: string,
  row: OfflineSessionRow | null,
  nowMs: number,
): MobileSession | null {
  if (!row || accountNamespace({ agencyId: row.agency_id, principalId: row.id }) !== namespace) return null;
  const refreshExpiry = Date.parse(row.refresh_token_expires_at);
  if (!Number.isFinite(refreshExpiry) || refreshExpiry <= nowMs) return null;
  return {
    accessToken: null,
    accessTokenExpiresAt: row.access_token_expires_at,
    refreshTokenExpiresAt: row.refresh_token_expires_at,
    sessionId: row.session_id,
    networkMode: 'offline',
    principal: {
      id: row.id,
      agencyId: row.agency_id,
      principalType: row.principal_type,
      displayName: row.display_name,
      forcePasswordChange: Boolean(row.force_password_change),
    },
  };
}
