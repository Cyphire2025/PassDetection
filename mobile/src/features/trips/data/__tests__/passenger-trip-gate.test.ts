import { passengerTripGateDecision } from '../passenger-trip-gate';

describe('passenger trip gate', () => {
  const base = {
    isSelectorRoute: false,
    isError: false,
    selectionResolved: true,
    tripCount: 2,
    selectedTripId: '11111111-1111-4111-8111-111111111111',
  };

  it('keeps cached tabs hidden until remembered selection resolves', () => {
    expect(passengerTripGateDecision({ ...base, selectionResolved: false })).toBe('loading');
  });

  it('opens the remembered trip without a false empty state', () => {
    expect(passengerTripGateDecision(base)).toBe('allow');
  });

  it('sends multiple trips without a valid remembered choice to selection', () => {
    expect(passengerTripGateDecision({ ...base, selectedTripId: null })).toBe('select');
  });

  it('auto-opened single trips and selector/error routes remain accessible', () => {
    expect(passengerTripGateDecision({ ...base, tripCount: 1, selectedTripId: null })).toBe('allow');
    expect(passengerTripGateDecision({ ...base, isSelectorRoute: true, selectedTripId: null })).toBe('allow');
    expect(passengerTripGateDecision({ ...base, isError: true, selectedTripId: null })).toBe('allow');
  });
});
