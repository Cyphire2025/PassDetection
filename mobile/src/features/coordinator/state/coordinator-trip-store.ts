import { create } from 'zustand';

type CoordinatorTripState = {
  accountKey: string | null;
  tripId: string | null;
  activateAccount: (accountKey: string | null) => void;
  selectTrip: (accountKey: string, tripId: string) => void;
  clearSelection: (accountKey: string) => void;
};

/**
 * Coordinator trip selection is deliberately account scoped. A stale selection from a
 * previous account is never returned while the new account is being initialized.
 */
export const useCoordinatorTripStore = create<CoordinatorTripState>((set) => ({
  accountKey: null,
  tripId: null,
  activateAccount: (accountKey) =>
    set((state) => (
      state.accountKey === accountKey
        ? state
        : { accountKey, tripId: null }
    )),
  selectTrip: (accountKey, tripId) => set({ accountKey, tripId }),
  clearSelection: (accountKey) =>
    set((state) => (
      state.accountKey === accountKey
        ? { accountKey, tripId: null }
        : state
    )),
}));
