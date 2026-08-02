import { create } from 'zustand';

import type { MobileSession } from './types';

type SessionState = {
  status: 'booting' | 'anonymous' | 'authenticated' | 'locked';
  session: MobileSession | null;
  setSession: (session: MobileSession) => void;
  setLocked: () => void;
  unlock: () => void;
  clear: () => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  status: 'booting',
  session: null,
  setSession: (session) => set({ status: 'authenticated', session }),
  setLocked: () =>
    set((state) => ({
      status: state.session ? 'locked' : 'anonymous',
    })),
  unlock: () =>
    set((state) => ({ status: state.session ? 'authenticated' : 'anonymous' })),
  clear: () => set({ status: 'anonymous', session: null }),
}));

export function currentAccessToken(): string | null {
  return useSessionStore.getState().session?.accessToken ?? null;
}
