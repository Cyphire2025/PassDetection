import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react-native';
import type { PropsWithChildren } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';
import { parseIanaTimeZone } from '@/core/localization/time-zone';
import type { Trip } from '@/features/trips/model/trip';

import { JourneyDestinationSchema, type JourneyDestination } from '../../model/journey-destination';
import { useJourneyRoute, useJourneyRouteRefresh } from '../use-journey-route';

const mockApiRequest = jest.fn();
let mockDemoMode = false;
jest.mock('@/core/api/client', () => ({ apiRequest: (...args: unknown[]) => mockApiRequest(...args) }));
jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => mockDemoMode }));

const session = (accountId = 'account-a'): MobileSession => ({
  accessToken: `fixture-${accountId}`, accessTokenExpiresAt: '2030-01-01T00:00:00Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00Z', sessionId: `session-${accountId}`, networkMode: 'online',
  principal: { id: `passenger-${accountId}`, accountId, agencyId: 'agency-a', principalType: 'passenger',
    passengerId: `record-${accountId}`, displayName: 'Fixture', email: null, phoneNumber: null, forcePasswordChange: false },
});
const trip = (destination: string | null = 'Singapore', id = 'trip-a'): Trip => ({
  id, destination, name: 'Assigned group', travelDate: '2030-01-01', returnDate: '2030-01-07',
  timeZone: parseIanaTimeZone('Asia/Singapore'), role: 'passenger', accessGeneration: 1,
  accessExpiresAt: null, itineraryVersion: 1, commonDocumentVersion: 1, announcementVersion: 1,
  updatedAt: '2029-12-01T00:00:00Z',
});
const lookup = (label = 'Singapore', latitude = 1.35, longitude = 103.82,
  placeType: 'city' | 'country' | 'state' | 'region' = 'city'): JourneyDestination => ({
  status: 'resolved',
  destination: { label, country: label, country_code: 'sg', latitude, longitude, place_type: placeType },
  attribution: 'Fixture geocoder', attribution_url: 'https://www.openstreetmap.org/copyright',
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const clients: QueryClient[] = [];
function harness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  clients.push(client);
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, wrapper };
}

describe('useJourneyRoute account-scoped destination lookup', () => {
  beforeEach(() => {
    mockDemoMode = false;
    mockApiRequest.mockReset().mockResolvedValue(lookup());
    useSessionStore.getState().setSession(session());
  });
  afterEach(async () => {
    await cleanup();
    clients.splice(0).forEach((client) => client.clear());
    useSessionStore.getState().clear();
    jest.useRealTimers();
  });

  it('uses the offline demo catalog without making any authenticated or public lookup', async () => {
    mockDemoMode = true;
    const { result, rerender } = await renderHook<ReturnType<typeof useJourneyRoute>, { selected: Trip }>(({ selected }) => useJourneyRoute(selected, true),
      { initialProps: { selected: trip() }, wrapper: harness().wrapper });
    expect(result.current.status).toBe('resolved');
    expect(result.current.route?.destination.city).toBe('Singapore');
    expect(mockApiRequest).not.toHaveBeenCalled();
    await rerender({ selected: trip('Unknown demonstration destination') });
    expect(result.current.route).toBeNull();
    expect(result.current.status).toBe('not_found');
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it('requests only the assigned trip endpoint through the normal API boundary with a schema and abort signal', async () => {
    const { result } = await renderHook(() => useJourneyRoute(trip('Singapore', 'group /α'), true),
      { wrapper: harness().wrapper });
    await waitFor(() => expect(result.current.status).toBe('resolved'));
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
    expect(mockApiRequest).toHaveBeenCalledWith('/mobile/trips/group%20%2F%CE%B1/journey-destination', {
      schema: JourneyDestinationSchema, signal: expect.any(AbortSignal), timeoutMs: 12_000,
    });
    expect(result.current.route?.destination).toMatchObject({ city: 'Singapore', latitude: 1.35, longitude: 103.82 });
  });

  it.each(['inactive', 'anonymous', 'missing destination'] as const)('does not start lookup when %s', async (reason) => {
    if (reason === 'anonymous') useSessionStore.getState().clear();
    const { result } = await renderHook(() => useJourneyRoute(trip(reason === 'missing destination' ? null : 'Singapore'),
      reason !== 'inactive'), { wrapper: harness().wrapper });
    expect(result.current.route).toBeNull();
    expect(mockApiRequest).not.toHaveBeenCalled();
  });

  it.each([
    ['country', 'Australia', -25.27, 133.77],
    ['state', 'Queensland', -20.91, 142.70],
  ] as const)('preserves a received %s geographic place without guessing a city', async (type, label, latitude, longitude) => {
    mockApiRequest.mockResolvedValue(lookup(label, latitude, longitude, type));
    const { result } = await renderHook(() => useJourneyRoute(trip(label), true), { wrapper: harness().wrapper });
    await waitFor(() => expect(result.current.status).toBe('resolved'));
    expect(result.current.route?.destination).toMatchObject({ city: label, placeType: type, latitude, longitude });
    expect(result.current.route?.destination.city).not.toBe('Sydney');
    expect(result.current.route?.destination.city).not.toBe('Brisbane');
    expect(result.current.route?.kind).toBe('illustrative');
  });

  it.each(['unavailable', 'ambiguous', 'not_found', 'not_configured'] as const)('leaves the route empty for %s, even for a locally recognized destination', async (status) => {
    mockApiRequest.mockResolvedValue({ ...lookup(), status, destination: null });
    const { result } = await renderHook(() => useJourneyRoute(trip('Singapore'), true), { wrapper: harness().wrapper });
    await waitFor(() => expect(result.current.status).toBe(status));
    expect(result.current.route).toBeNull();
  });

  it('leaves the route empty after a request failure and does not retry or invent a local production route', async () => {
    mockApiRequest.mockRejectedValue(new Error('Fixture provider outage'));
    const { result } = await renderHook(() => useJourneyRoute(trip('Australia'), true), { wrapper: harness().wrapper });
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(result.current.route).toBeNull();
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
  });

  it.each(['trip', 'destination', 'account'] as const)('clears the visible route while a changed %s receives its own query result', async (boundary) => {
    const next = deferred<JourneyDestination>();
    mockApiRequest.mockResolvedValueOnce(lookup()).mockImplementationOnce(() => next.promise);
    const { client, wrapper } = harness();
    const { result, rerender } = await renderHook<ReturnType<typeof useJourneyRoute>, { selected: Trip }>(({ selected }) => useJourneyRoute(selected, true),
      { initialProps: { selected: trip() }, wrapper });
    await waitFor(() => expect(result.current.route?.destination.city).toBe('Singapore'));
    const selected = boundary === 'trip' ? trip('Dubai', 'trip-b') : boundary === 'destination' ? trip('Dubai') : trip();
    if (boundary === 'account') await act(async () => useSessionStore.getState().setSession(session('account-b')));
    else await rerender({ selected });
    await waitFor(() => expect(mockApiRequest).toHaveBeenCalledTimes(2));
    expect(result.current.route).toBeNull();
    expect(result.current.status).toBe('resolving');
    const expectedKey = ['journey-destination', boundary === 'account' ? 'agency-a.account-b' : 'agency-a.account-a',
      selected.id, selected.destination];
    expect(client.getQueryCache().find({ queryKey: expectedKey, exact: true })).toBeDefined();
    await act(async () => next.resolve(lookup('Dubai', 25.2, 55.27)));
    await waitFor(() => expect(result.current.route?.destination.city).toBe('Dubai'));
  });

  it('aborts a previous account lookup and rejects its late result after switching accounts', async () => {
    const previous = deferred<JourneyDestination>();
    const next = deferred<JourneyDestination>();
    mockApiRequest.mockImplementationOnce(() => previous.promise).mockImplementationOnce(() => next.promise);
    const { client, wrapper } = harness();
    const { result } = await renderHook(() => useJourneyRoute(trip(), true), { wrapper });
    await waitFor(() => expect(mockApiRequest).toHaveBeenCalledTimes(1));
    const previousSignal = mockApiRequest.mock.calls[0]![1].signal as AbortSignal;
    await act(async () => useSessionStore.getState().setSession(session('account-b')));
    await waitFor(() => expect(mockApiRequest).toHaveBeenCalledTimes(2));
    expect(previousSignal.aborted).toBe(true);
    await act(async () => previous.resolve(lookup('Old account destination')));
    expect(result.current.route).toBeNull();
    expect(client.getQueryData(['journey-destination', 'agency-a.account-a', 'trip-a', 'Singapore'])).toBeUndefined();
    await act(async () => next.resolve(lookup('Current account destination')));
    await waitFor(() => expect(result.current.route?.destination.city).toBe('Current account destination'));
  });

  it('aborts a pending destination lookup and cannot replace the changed destination with its late result', async () => {
    const previous = deferred<JourneyDestination>();
    const next = deferred<JourneyDestination>();
    mockApiRequest.mockImplementationOnce(() => previous.promise).mockImplementationOnce(() => next.promise);
    const { client, wrapper } = harness();
    const { result, rerender } = await renderHook<ReturnType<typeof useJourneyRoute>, { selected: Trip }>(
      ({ selected }) => useJourneyRoute(selected, true), { initialProps: { selected: trip() }, wrapper },
    );
    await waitFor(() => expect(mockApiRequest).toHaveBeenCalledTimes(1));
    const previousSignal = mockApiRequest.mock.calls[0]![1].signal as AbortSignal;
    await rerender({ selected: trip('London') });
    await waitFor(() => expect(mockApiRequest).toHaveBeenCalledTimes(2));
    expect(previousSignal.aborted).toBe(true);
    expect(result.current.route).toBeNull();
    await act(async () => next.resolve(lookup('London', 51.51, -0.13)));
    await waitFor(() => expect(result.current.route?.destination.city).toBe('London'));
    await act(async () => previous.resolve(lookup()));
    expect(result.current.route?.destination.city).toBe('London');
    expect(client.getQueryData(['journey-destination', 'agency-a.account-a', 'trip-a', 'Singapore'])).toBeUndefined();
  });

  it('explicitly refreshes an unchanged ambiguous destination without invalidating other account or destination keys', async () => {
    mockApiRequest.mockResolvedValueOnce({ ...lookup(), status: 'ambiguous', destination: null })
      .mockResolvedValueOnce(lookup('London', 51.51, -0.13));
    const { client, wrapper } = harness();
    const otherAccountKey = ['journey-destination', 'agency-a.account-b', 'trip-a', 'London'];
    const otherDestinationKey = ['journey-destination', 'agency-a.account-a', 'trip-a', 'Singapore'];
    client.setQueryData(otherAccountKey, lookup('London', 51.51, -0.13));
    client.setQueryData(otherDestinationKey, lookup());
    const { result } = await renderHook(() => ({
      ...useJourneyRoute(trip('London'), true),
      refresh: useJourneyRouteRefresh(trip('London')),
    }), { wrapper });
    await waitFor(() => expect(result.current.status).toBe('ambiguous'));
    expect(result.current.route).toBeNull();
    await act(async () => result.current.refresh());
    await waitFor(() => expect(result.current.route?.destination.city).toBe('London'));
    expect(mockApiRequest).toHaveBeenCalledTimes(2);
    expect(client.getQueryState(otherAccountKey)?.isInvalidated).toBe(false);
    expect(client.getQueryState(otherDestinationKey)?.isInvalidated).toBe(false);
  });

  it('defers an explicit refresh until an inactive card becomes visible again', async () => {
    mockApiRequest.mockResolvedValueOnce({ ...lookup(), status: 'ambiguous', destination: null })
      .mockResolvedValueOnce(lookup('London', 51.51, -0.13));
    const { result, rerender } = await renderHook(({ active }: { active: boolean }) => ({
      ...useJourneyRoute(trip('London'), active),
      refresh: useJourneyRouteRefresh(trip('London')),
    }), { initialProps: { active: true }, wrapper: harness().wrapper });
    await waitFor(() => expect(result.current.status).toBe('ambiguous'));
    await rerender({ active: false });
    await act(async () => result.current.refresh());
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
    await rerender({ active: true });
    await waitFor(() => expect(result.current.route?.destination.city).toBe('London'));
    expect(mockApiRequest).toHaveBeenCalledTimes(2);
  });

  it('honors provider retry delay and stops after the initial temporary response plus two retries', async () => {
    jest.useFakeTimers();
    mockApiRequest.mockResolvedValue({ ...lookup(), status: 'unavailable', destination: null, retry_after_seconds: 12 });
    const { result } = await renderHook(() => useJourneyRoute(trip(), true), { wrapper: harness().wrapper });
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
    await act(async () => { await jest.advanceTimersByTimeAsync(11_000); });
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
    await act(async () => { await jest.advanceTimersByTimeAsync(1_100); });
    expect(mockApiRequest).toHaveBeenCalledTimes(2);
    await act(async () => { await jest.advanceTimersByTimeAsync(11_000); });
    expect(mockApiRequest).toHaveBeenCalledTimes(2);
    await act(async () => { await jest.advanceTimersByTimeAsync(1_100); });
    expect(mockApiRequest).toHaveBeenCalledTimes(3);
    await act(async () => { await jest.advanceTimersByTimeAsync(120_000); });
    expect(mockApiRequest).toHaveBeenCalledTimes(3);
    expect(result.current.route).toBeNull();
  });

  it('applies a five-second minimum retry interval and stops polling immediately after resolution', async () => {
    jest.useFakeTimers();
    mockApiRequest.mockResolvedValueOnce({ ...lookup(), status: 'unavailable', destination: null, retry_after_seconds: 0 })
      .mockResolvedValueOnce(lookup());
    const { result } = await renderHook(() => useJourneyRoute(trip(), true), { wrapper: harness().wrapper });
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    await act(async () => { await jest.advanceTimersByTimeAsync(4_800); });
    expect(mockApiRequest).toHaveBeenCalledTimes(1);
    await act(async () => { await jest.advanceTimersByTimeAsync(300); });
    expect(mockApiRequest).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe('resolved');
    await act(async () => { await jest.advanceTimersByTimeAsync(120_000); });
    expect(mockApiRequest).toHaveBeenCalledTimes(2);
  });

  it.each([['resolved', 1], ['not_found', 2]] as const)('reuses a recent %s cache appropriately when reopening the screen', async (status, requests) => {
    jest.useFakeTimers();
    mockApiRequest.mockResolvedValue({ ...lookup(), status, destination: status === 'resolved' ? lookup().destination : null });
    const { wrapper } = harness();
    const first = await renderHook(() => useJourneyRoute(trip(), true), { wrapper });
    await waitFor(() => expect(first.result.current.status).toBe(status));
    await first.unmount();
    await act(async () => { await jest.advanceTimersByTimeAsync(31_000); });
    const reopened = await renderHook(() => useJourneyRoute(trip(), true), { wrapper });
    await waitFor(() => expect(reopened.result.current.status).toBe(status));
    expect(mockApiRequest).toHaveBeenCalledTimes(requests);
  });
});
