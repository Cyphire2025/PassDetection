import { create } from 'zustand';

export type PushRegistrationStatus =
  | 'registering' | 'registered' | 'permission_denied' | 'unsupported_device'
  | 'offline' | 'build_unconfigured' | 'token_unavailable' | 'registration_failed';

// Ephemeral, account/session-scoped diagnostics. Never retain a push token or
// provider response, and never show an earlier account's registration result.
export const usePushRegistrationState = create<{
  scope: string | null;
  status: PushRegistrationStatus | null;
  update: (scope: string, status: PushRegistrationStatus) => void;
}>((set) => ({
  scope: null,
  status: null,
  update: (scope, status) => set({ scope, status }),
}));
