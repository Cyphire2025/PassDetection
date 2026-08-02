export type MobileRole = 'passenger' | 'client_manager' | 'coordinator';

export type MobilePrincipal = {
  id: string;
  principalType: MobileRole;
  agencyId: string;
  displayName: string;
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
  principalId: string;
};

export function accountNamespace(value: AccountNamespace): string {
  return `${value.agencyId}.${value.principalId}`;
}
