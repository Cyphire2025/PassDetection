import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import type { PropsWithChildren } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { accountNamespace, type MobileSession } from '@/core/auth/types';
import { rememberPassengerTrip, rememberedPassengerTrip } from '../../data/passenger-trip-selection';
import type { Trip } from '../../model/trip';
import { useSelectedTripStore } from '../../state/selected-trip-store';
import { useTrips } from '../use-trips';

jest.mock('@/core/query/use-persistent-query-hydration', () => ({
  usePersistentQueryHydration: () => true,
}));
jest.mock('@/core/query/account-query-context', () => ({ withAccountQueryContext: jest.fn() }));
jest.mock('@/core/sync/sync-trigger', () => ({ requestSync: jest.fn() }));
jest.mock('../../data/trip-repository', () => ({ localTrips: jest.fn(), localTripsInContext: jest.fn() }));
jest.mock('../../data/passenger-trip-selection', () => ({
  rememberPassengerTrip: jest.fn(),
  rememberedPassengerTrip: jest.fn(),
}));

const session: MobileSession = {
  accessToken: 'test-access',
  accessTokenExpiresAt: '2030-01-01T00:00:00.000Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00.000Z',
  sessionId: 'test-session',
  networkMode: 'online',
  principal: {
    id: 'account',
    accountId: 'account',
    principalType: 'passenger',
    agencyId: 'agency',
    passengerId: 'passenger',
    displayName: 'Passenger',
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  },
};

const trip = (id: string): Trip => ({
  id,
  name: `Trip ${id}`,
  destination: 'Tokyo',
  travelDate: null,
  returnDate: null,
  timeZone: 'Asia/Tokyo' as Trip['timeZone'],
  role: 'passenger',
  accessGeneration: 1,
  accessExpiresAt: null,
  itineraryVersion: 1,
  commonDocumentVersion: 1,
  announcementVersion: 1,
  updatedAt: '2026-09-19T00:00:00Z',
});

const mockRemember = jest.mocked(rememberPassengerTrip);
const mockRestore = jest.mocked(rememberedPassengerTrip);
let client: QueryClient;

async function mountTrips(trips: Trip[]) {
  client.setQueryData(['mobile-trips', accountNamespace(session.principal)], { trips, offline: true });
  return renderHook(() => useTrips(), {
    wrapper: ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

describe('passenger trip selection responsiveness', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, gcTime: 0, retry: false } } });
    useSessionStore.getState().setSession(session);
    useSelectedTripStore.getState().clear();
    mockRemember.mockImplementation(async (_trips, id) => trip(id));
    mockRestore.mockResolvedValue(null);
  });

  afterEach(() => {
    client.clear();
    useSessionStore.getState().clear();
    useSelectedTripStore.getState().clear();
  });

  it('opens the sole trip while preference storage is still pending', async () => {
    const onlyTrip = trip('only');
    mockRemember.mockImplementation(() => new Promise(() => {}));
    const { result, unmount } = await mountTrips([onlyTrip]);

    expect(result.current.selectedTrip).toEqual(onlyTrip);
    expect(result.current.selectionResolved).toBe(true);
    expect(mockRestore).not.toHaveBeenCalled();
    expect(mockRemember).toHaveBeenCalledWith([onlyTrip], onlyTrip.id);
    await unmount();
  });

  it('keeps the sole trip usable when saving the preference fails', async () => {
    mockRemember.mockRejectedValue(new Error('secure storage unavailable'));
    useSelectedTripStore.getState().selectTrip('expired-trip');
    const { result, unmount } = await mountTrips([trip('only')]);

    await waitFor(() => expect(result.current.selectionResolved).toBe(true));
    expect(result.current.selectedTripId).toBe('only');
    expect(result.current.selectedTrip?.id).toBe('only');
    await unmount();
  });

  it('still waits for the remembered choice when several trips are available', async () => {
    const trips = [trip('first'), trip('second')];
    let resolveChoice!: (value: Trip | null) => void;
    mockRestore.mockImplementation(() => new Promise((resolve) => { resolveChoice = resolve; }));
    const { result, unmount } = await mountTrips(trips);

    expect(result.current.selectionResolved).toBe(false);
    expect(result.current.selectedTrip).toBeNull();
    await act(async () => { resolveChoice(trips[1]!); });

    expect(result.current.selectedTripId).toBe('second');
    expect(result.current.selectionResolved).toBe(true);
    expect(mockRemember).not.toHaveBeenCalled();
    await unmount();
  });

  it('settles without a stale trip when restoring a multiple-trip choice fails', async () => {
    useSelectedTripStore.getState().selectTrip('expired-trip');
    mockRestore.mockRejectedValue(new Error('secure storage unavailable'));
    const { result, unmount } = await mountTrips([trip('first'), trip('second')]);

    await waitFor(() => expect(result.current.selectionResolved).toBe(true));
    expect(result.current.selectedTripId).toBeNull();
    await unmount();
  });
});
