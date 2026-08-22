import { create } from 'zustand';

import type { RealtimeConnectionState } from './realtime-client';

export type MobileRealtimeStatus = RealtimeConnectionState | 'disabled';

type RealtimeStatusStore = Readonly<{
  changedAt: number;
  status: MobileRealtimeStatus;
  setStatus: (status: MobileRealtimeStatus) => void;
}>;

export const useRealtimeStatusStore = create<RealtimeStatusStore>((set) => ({
  changedAt: 0,
  status: 'idle',
  setStatus: (status) => set((current) => (
    current.status === status
      ? current
      : { ...current, changedAt: Date.now(), status }
  )),
}));

export function setMobileRealtimeStatus(status: MobileRealtimeStatus): void {
  useRealtimeStatusStore.getState().setStatus(status);
}
