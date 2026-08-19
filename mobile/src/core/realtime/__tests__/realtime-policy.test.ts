import {
  fullJitterReconnectDelayMs,
  parseRealtimeServerFrame,
  SyncHintCoalescer,
} from '../realtime-policy';

const tripId = '123e4567-e89b-42d3-a456-426614174000';

describe('realtime policy', () => {
  afterEach(() => jest.useRealTimers());

  it('accepts only bounded PII-free server contracts', () => {
    expect(parseRealtimeServerFrame(JSON.stringify({
      type: 'sync_hint',
      trip_id: tripId,
      cursor: 17,
      invalidation: 'documents',
    }))).toEqual({
      type: 'sync_hint',
      trip_id: tripId,
      cursor: 17,
      invalidation: 'documents',
    });
    expect(parseRealtimeServerFrame(JSON.stringify({
      type: 'sync_hint',
      trip_id: tripId,
      cursor: 17,
      invalidation: 'documents',
      passenger_name: 'private',
    }))).toBeNull();
    expect(parseRealtimeServerFrame('x'.repeat(1025))).toBeNull();
  });

  it('uses bounded full-jitter exponential reconnect delays', () => {
    expect(fullJitterReconnectDelayMs(0, () => 0)).toBe(0);
    expect(fullJitterReconnectDelayMs(0, () => 1)).toBe(500);
    expect(fullJitterReconnectDelayMs(1, () => 1)).toBe(1000);
    expect(fullJitterReconnectDelayMs(20, () => 1)).toBe(30_000);
    expect(fullJitterReconnectDelayMs(20, () => Number.NaN)).toBe(30_000);
  });

  it('coalesces duplicate and reordered hints without trusting their cursor', () => {
    jest.useFakeTimers();
    const trips: string[] = [];
    const full = jest.fn();
    const coalescer = new SyncHintCoalescer({
      onTrip: (value) => trips.push(value),
      onFull: full,
    });
    for (const cursor of [12, 8, 12, 15]) {
      coalescer.enqueue({
        type: 'sync_hint',
        trip_id: tripId,
        cursor,
        invalidation: 'itinerary',
      });
    }

    jest.advanceTimersByTime(249);
    expect(trips).toEqual([]);
    jest.advanceTimersByTime(1);
    expect(trips).toEqual([tripId]);
    expect(full).not.toHaveBeenCalled();
    coalescer.dispose();
  });

  it('falls back to one full reconciliation on bounded coalescer overflow', () => {
    jest.useFakeTimers();
    const onTrip = jest.fn();
    const onFull = jest.fn();
    const coalescer = new SyncHintCoalescer({
      onTrip,
      onFull,
      maximumPendingTrips: 2,
    });
    for (const suffix of ['4000', '4001', '4002']) {
      coalescer.enqueue({
        type: 'sync_hint',
        trip_id: `123e4567-e89b-42d3-a456-42661417${suffix}`,
        cursor: 1,
        invalidation: 'all',
      });
    }
    jest.runOnlyPendingTimers();
    expect(onTrip).not.toHaveBeenCalled();
    expect(onFull).toHaveBeenCalledTimes(1);
    coalescer.dispose();
  });
});
