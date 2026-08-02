import { create } from 'zustand';

import type { MobileSession } from './types';

type SessionState = {
  status: 'booting' | 'anonymous' | 'authenticated';
  session: MobileSession | null;
  setSession: (session: MobileSession) => void;
  clear: () => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  status: 'booting',
  session: null,
  setSession: (session) => set({ status: 'authenticated', session }),
  clear: () => set({ status: 'anonymous', session: null }),
}));

export function currentAccessToken(): string | null {
  return useSessionStore.getState().session?.accessToken ?? null;
}
