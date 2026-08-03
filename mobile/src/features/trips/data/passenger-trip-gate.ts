export type PassengerTripGateDecision = 'allow' | 'loading' | 'select';

export function passengerTripGateDecision(input: {
  isSelectorRoute: boolean;
  isError: boolean;
  selectionResolved: boolean;
  tripCount: number;
  selectedTripId: string | null;
}): PassengerTripGateDecision {
  if (input.isSelectorRoute || input.isError) return 'allow';
  if (!input.selectionResolved) return 'loading';
  if (input.tripCount > 1 && !input.selectedTripId) return 'select';
  return 'allow';
}
