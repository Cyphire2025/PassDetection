import { create } from 'zustand';

import type { MobileSession } from './types';

export type AuthenticationSnapshot = Readonly<{
  epoch: number;
  accessToken: string | null;
}>;

// This value deliberately lives outside persisted Zustand state. It represents the
// lifetime of the currently active authentication boundary, not server data. Any
// explicit login, account switch, password-session replacement, or logout advances
// it synchronously so already-running network work can fail closed before committing.
let authenticationEpoch = 0;

type SessionState = {
  status: 'booting' | 'anonymous' | 'authenticated';
  session: MobileSession | null;
  bootstrapErrorCode: 'SESSION_BOOTSTRAP_FAILED' | null;
  beginBootstrap: () => void;
  failBootstrap: () => void;
  setSession: (session: MobileSession) => void;
  clear: () => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  status: 'booting',
  session: null,
  bootstrapErrorCode: null,
  beginBootstrap: () => set({
    status: 'booting',
    session: null,
    bootstrapErrorCode: null,
  }),
  failBootstrap: () => set({
    status: 'anonymous',
    session: null,
    bootstrapErrorCode: 'SESSION_BOOTSTRAP_FAILED',
  }),
  setSession: (session) => set({
    status: 'authenticated',
    session,
    bootstrapErrorCode: null,
  }),
  clear: () => set({
    status: 'anonymous',
    session: null,
    bootstrapErrorCode: null,
  }),
}));

export function currentAccessToken(): string | null {
  return useSessionStore.getState().session?.accessToken ?? null;
}

export function captureAuthenticationSnapshot(): AuthenticationSnapshot {
  return {
    epoch: authenticationEpoch,
    accessToken: currentAccessToken(),
  };
}

export function isAuthenticationEpochCurrent(epoch: number): boolean {
  return authenticationEpoch === epoch;
}

export function isAuthenticationSnapshotCurrent(snapshot: AuthenticationSnapshot): boolean {
  return isAuthenticationEpochCurrent(snapshot.epoch) && currentAccessToken() === snapshot.accessToken;
}

export function invalidateAuthenticationBoundary(): number {
  authenticationEpoch += 1;
  return authenticationEpoch;
}
