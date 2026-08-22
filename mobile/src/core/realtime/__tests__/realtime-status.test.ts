import { setMobileRealtimeStatus, useRealtimeStatusStore } from '../realtime-status';

beforeEach(() => {
  useRealtimeStatusStore.setState({ changedAt: 0, status: 'idle' });
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('records only low-cardinality transport state and ignores duplicate transitions', () => {
  jest.spyOn(Date, 'now').mockReturnValueOnce(1_000).mockReturnValueOnce(2_000);

  setMobileRealtimeStatus('connected');
  expect(useRealtimeStatusStore.getState()).toMatchObject({
    changedAt: 1_000,
    status: 'connected',
  });

  setMobileRealtimeStatus('connected');
  expect(useRealtimeStatusStore.getState().changedAt).toBe(1_000);

  setMobileRealtimeStatus('reconnecting');
  expect(useRealtimeStatusStore.getState()).toMatchObject({
    changedAt: 2_000,
    status: 'reconnecting',
  });
  expect(JSON.stringify(useRealtimeStatusStore.getState())).not.toMatch(/token|passenger|qr/i);
});
