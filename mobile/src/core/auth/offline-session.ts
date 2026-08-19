import { accountNamespace, type MobileSession } from './types';

export type OfflineSessionRow = {
  id: string;
  account_id: string;
  agency_id: string;
  principal_type: MobileSession['principal']['principalType'];
  passenger_id?: string | null;
  display_name: string;
  email: string | null;
  phone_number: string | null;
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
): MobileSession | null {
  if (!row || accountNamespace({ agencyId: row.agency_id, accountId: row.account_id }) !== namespace) return null;
  if (row.principal_type === 'passenger' && !row.passenger_id) return null;
  return {
    accessToken: null,
    accessTokenExpiresAt: row.access_token_expires_at,
    refreshTokenExpiresAt: row.refresh_token_expires_at,
    sessionId: row.session_id,
    networkMode: 'offline',
    principal: {
      id: row.id,
      accountId: row.account_id,
      agencyId: row.agency_id,
      principalType: row.principal_type,
      passengerId: row.passenger_id ?? null,
      displayName: row.display_name,
      email: row.email,
      phoneNumber: row.phone_number,
      forcePasswordChange: Boolean(row.force_password_change),
    },
  };
}
