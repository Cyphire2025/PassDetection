import { create } from 'zustand';

type CoordinatorTripState = {
  principalId: string | null;
  tripId: string | null;
  activatePrincipal: (principalId: string | null) => void;
  selectTrip: (principalId: string, tripId: string) => void;
  clearSelection: (principalId: string) => void;
};

/**
 * Coordinator trip selection is deliberately account scoped. A stale selection from a
 * previous account is never returned while the new account is being initialized.
 */
export const useCoordinatorTripStore = create<CoordinatorTripState>((set) => ({
  principalId: null,
  tripId: null,
  activatePrincipal: (principalId) =>
    set((state) => (
      state.principalId === principalId
        ? state
        : { principalId, tripId: null }
    )),
  selectTrip: (principalId, tripId) => set({ principalId, tripId }),
  clearSelection: (principalId) =>
    set((state) => (
      state.principalId === principalId
        ? { principalId, tripId: null }
        : state
    )),
}));
