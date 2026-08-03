export type MobileRole = 'passenger' | 'client_manager' | 'coordinator';

export type MobilePrincipal = {
  id: string;
  /**
   * Stable account boundary for encrypted storage and cached data.
   * Passenger `id` is the selected trip identity and may rotate after an
   * authorized trip switch; `accountId` remains invariant for the session.
   */
  accountId: string;
  principalType: MobileRole;
  agencyId: string;
  /** Authoritative travel passenger record; required only for passenger sessions. */
  passengerId?: string | null;
  displayName: string;
  email: string | null;
  phoneNumber: string | null;
  forcePasswordChange: boolean;
};

export type MobileSession = {
  accessToken: string | null;
  accessTokenExpiresAt: string;
  refreshTokenExpiresAt: string;
  sessionId: string;
  networkMode: 'online' | 'offline';
  principal: MobilePrincipal;
};

export type AccountNamespace = {
  agencyId: string;
  accountId: string;
};

export function accountNamespace(value: AccountNamespace): string {
  return `${value.agencyId}.${value.accountId}`;
}

export function principalAccountNamespace(
  principal: Pick<MobilePrincipal, 'accountId' | 'agencyId'>,
): string {
  return accountNamespace({ agencyId: principal.agencyId, accountId: principal.accountId });
}
