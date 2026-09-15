import { act, render, waitFor } from '@testing-library/react-native';
import type { NotificationResponse } from 'expo-notifications';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileSession } from '@/core/auth/types';

import { NotificationRuntime } from '../notification-runtime';

const mockPush = jest.fn();
const mockRouter = { push: mockPush };
const mockSelectTrip = jest.fn();
const mockClearTrip = jest.fn();
const mockGetHandled = jest.fn();
const mockSetHandled = jest.fn();
const mockRefreshTrips = jest.fn();
const mockGetLastResponse = jest.fn();
const mockAddResponseListener = jest.fn();
const mockSubscription = () => ({ remove: jest.fn() });

jest.mock('expo-router', () => ({ useRouter: () => mockRouter }));
jest.mock('expo-notifications', () => ({
  addPushTokenListener: () => mockSubscription(),
  addNotificationReceivedListener: () => mockSubscription(),
  addNotificationResponseReceivedListener: (...args: unknown[]) => mockAddResponseListener(...args),
  getLastNotificationResponseAsync: () => mockGetLastResponse(),
}));
jest.mock('@/core/demo/demo-mode', () => ({ isDemoMode: () => false }));
jest.mock('@/core/observability/mobile-observability', () => ({ recordMobileMetric: jest.fn() }));
jest.mock('@/core/storage/secure-store', () => ({
  getHandledNotificationResponse: (...args: unknown[]) => mockGetHandled(...args),
  setHandledNotificationResponse: (...args: unknown[]) => mockSetHandled(...args),
}));
jest.mock('@/core/sync/sync-trigger', () => ({ requestSync: jest.fn(async () => undefined) }));
jest.mock('@/features/trips/data/trip-repository', () => ({
  localTrips: async () => [],
  refreshTrips: () => mockRefreshTrips(),
}));
jest.mock('@/features/coordinator/state/coordinator-trip-store', () => ({
  useCoordinatorTripStore: { getState: () => ({ selectTrip: mockSelectTrip, clearSelection: mockClearTrip }) },
}));
jest.mock('@/features/trips/state/selected-trip-store', () => ({
  useSelectedTripStore: { getState: () => ({ selectTrip: mockSelectTrip, clear: mockClearTrip }) },
}));
jest.mock('../departure-reminders', () => ({ reconcileDepartureReminders: async () => undefined }));
jest.mock('../notification-service', () => ({
  registerPushDevice: async () => true,
  invalidateCurrentPushRegistration: async () => undefined,
  notificationData: (response: NotificationResponse) => response.notification.request.content.data,
  notificationContentData: () => null,
}));

const tripId = '11111111-1111-4111-8111-111111111111';
const eventId = '22222222-2222-4222-8222-222222222222';
const response: NotificationResponse = {
  actionIdentifier: 'expo.modules.notifications.actions.DEFAULT',
  notification: { date: 1, request: { identifier: 'fcm-message-1', trigger: { type: 'push' },
    content: { title: 'Trip update', subtitle: null, body: null, categoryIdentifier: null,
      sound: 'default', data: { route: 'updates', trip_id: tripId, event_id: eventId } } } },
};
const session: MobileSession = {
  accessToken: 'test-token', accessTokenExpiresAt: '2030-01-01T00:00:00Z',
  refreshTokenExpiresAt: '2030-02-01T00:00:00Z', sessionId: 'session-a', networkMode: 'online',
  principal: { id: 'coordinator-a', accountId: 'account-a', agencyId: 'agency-a',
    principalType: 'coordinator', displayName: 'Test Coordinator', email: null,
    phoneNumber: null, forcePasswordChange: false },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function emitResponse() {
  const callback = mockAddResponseListener.mock.calls[0]![0] as (item: NotificationResponse) => void;
  callback(response);
}

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.getState().setSession(session);
  mockGetHandled.mockReset().mockResolvedValue(null);
  mockSetHandled.mockReset().mockResolvedValue(undefined);
  mockRefreshTrips.mockReset().mockResolvedValue({ trips: [{ id: tripId }] });
  mockGetLastResponse.mockReset().mockResolvedValue(null);
  mockAddResponseListener.mockImplementation(mockSubscription);
});

test('coalesces the native cold-start response and listener before the storage read resolves', async () => {
  const read = deferred<string | null>();
  mockGetHandled.mockReturnValue(read.promise);
  mockGetLastResponse.mockResolvedValue(response);
  await render(<NotificationRuntime />);
  await waitFor(() => expect(mockGetHandled).toHaveBeenCalledTimes(1));
  await act(async () => { emitResponse(); });
  expect(mockGetHandled).toHaveBeenCalledTimes(1);
  await act(async () => { read.resolve(null); });
  await waitFor(() => expect(mockPush).toHaveBeenCalledTimes(1));
  expect(mockRefreshTrips).toHaveBeenCalledTimes(1);
  expect(mockSelectTrip).toHaveBeenCalledWith('agency-a.account-a', tripId);
  expect(mockPush).toHaveBeenCalledWith('/(coordinator)/operations/updates');
});

test.each([true, false])('does not navigate or select a trip after a session switch during the claim write (assigned=%s)', async (assigned) => {
  const write = deferred<void>();
  mockSetHandled.mockReturnValue(write.promise);
  mockRefreshTrips.mockResolvedValue({ trips: assigned ? [{ id: tripId }] : [] });
  await render(<NotificationRuntime />);
  await act(async () => { emitResponse(); });
  await waitFor(() => expect(mockSetHandled).toHaveBeenCalledTimes(1));
  await act(async () => {
    useSessionStore.getState().setSession({ ...session, sessionId: 'session-b',
      principal: { ...session.principal, accountId: 'account-b' } });
    write.resolve(undefined);
  });
  expect(mockPush).not.toHaveBeenCalled();
  expect(mockSelectTrip).not.toHaveBeenCalled();
  expect(mockClearTrip).not.toHaveBeenCalled();
});

test('a failed claim read releases the in-flight response so a later tap can retry', async () => {
  mockGetHandled.mockRejectedValueOnce(new Error('secure storage temporarily unavailable'));
  await render(<NotificationRuntime />);
  await act(async () => { emitResponse(); });
  expect(mockPush).not.toHaveBeenCalled();
  await act(async () => { emitResponse(); });
  await waitFor(() => expect(mockPush).toHaveBeenCalledTimes(1));
  expect(mockGetHandled).toHaveBeenCalledTimes(2);
});

test('a stored handled response does not navigate again', async () => {
  mockGetHandled.mockResolvedValue(`event:${eventId}`);
  mockGetLastResponse.mockResolvedValue(response);
  await render(<NotificationRuntime />);
  await waitFor(() => expect(mockGetHandled).toHaveBeenCalledTimes(1));
  expect(mockRefreshTrips).not.toHaveBeenCalled();
  expect(mockPush).not.toHaveBeenCalled();
});
