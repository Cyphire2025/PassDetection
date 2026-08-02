import { create } from 'zustand';

type SelectedTripState = {
  tripId: string | null;
  selectTrip: (tripId: string) => void;
  clear: () => void;
};

export const useSelectedTripStore = create<SelectedTripState>((set) => ({
  tripId: null,
  selectTrip: (tripId) => set({ tripId }),
  clear: () => set({ tripId: null }),
}));
