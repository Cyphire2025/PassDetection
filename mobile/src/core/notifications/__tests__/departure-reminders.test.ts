import type { Trip } from '@/features/trips/model/trip';
import { parseIanaTimeZone } from '@/core/localization/time-zone';

import {
  cancelDepartureReminders,
  planDepartureReminders,
  reconcileDepartureReminders,
} from '../departure-reminders';

const mockGetPermissions = jest.fn();
const mockGetScheduled = jest.fn();
const mockSchedule = jest.fn();
const mockCancel = jest.fn();
const mockSetChannel = jest.fn();

jest.mock('expo-notifications', () => ({
  AndroidImportance: { HIGH: 4 },
  AndroidNotificationVisibility: { PRIVATE: 0 },
  IosAuthorizationStatus: { PROVISIONAL: 3, EPHEMERAL: 4 },
  SchedulableTriggerInputTypes: { DATE: 'date' },
  getPermissionsAsync: (...args: unknown[]) => mockGetPermissions(...args),
  getAllScheduledNotificationsAsync: (...args: unknown[]) => mockGetScheduled(...args),
  scheduleNotificationAsync: (...args: unknown[]) => mockSchedule(...args),
  cancelScheduledNotificationAsync: (...args: unknown[]) => mockCancel(...args),
  setNotificationChannelAsync: (...args: unknown[]) => mockSetChannel(...args),
  setNotificationHandler: jest.fn(),
}));

jest.mock('expo-device', () => ({ isDevice: true }));

function trip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    name: 'Vietnam Adventure',
    destination: 'Vietnam',
    travelDate: '2026-08-10',
    returnDate: '2026-08-16',
    timeZone: parseIanaTimeZone('Asia/Singapore'),
    role: 'passenger',
    accessGeneration: 1,
    accessExpiresAt: null,
    itineraryVersion: 1,
    commonDocumentVersion: 1,
    announcementVersion: 1,
    updatedAt: '2026-08-01T00:00:00.000Z',
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGetPermissions.mockResolvedValue({ granted: true, canAskAgain: true, ios: null });
  mockGetScheduled.mockResolvedValue([]);
  mockSchedule.mockImplementation(async (request) => request.identifier);
  mockCancel.mockResolvedValue(undefined);
  mockSetChannel.mockResolvedValue(undefined);
});

test('plans corporate reminders at 9 AM for three, two, one and zero days before departure', () => {
  const reminders = planDepartureReminders(
    [trip()],
    Date.parse('2026-08-01T04:00:00Z'),
  );

  expect(reminders).toHaveLength(4);
  expect(reminders.map((reminder) => ({
    instant: reminder.triggerDate.toISOString(),
    title: reminder.title,
  }))).toEqual([
    { instant: '2026-08-07T01:00:00.000Z', title: 'Your trip begins in 3 days ✈️' },
    { instant: '2026-08-08T01:00:00.000Z', title: '2 days until departure' },
    { instant: '2026-08-09T01:00:00.000Z', title: 'Departure is tomorrow 🧳' },
    { instant: '2026-08-10T01:00:00.000Z', title: 'Your travel day is here ✈️' },
  ]);
});

test('timezone participates in the schedule and identifier', () => {
  const [singapore] = planDepartureReminders(
    [trip()],
    Date.parse('2026-08-09T00:00:00Z'),
  );
  const [losAngeles] = planDepartureReminders(
    [trip({ timeZone: parseIanaTimeZone('America/Los_Angeles') })],
    Date.parse('2026-08-09T00:00:00Z'),
  );

  expect(singapore?.triggerDate.toISOString()).toBe('2026-08-09T01:00:00.000Z');
  expect(losAngeles?.triggerDate.toISOString()).toBe('2026-08-09T16:00:00.000Z');
  expect(singapore?.identifier).toContain('.Asia/Singapore.1');
  expect(losAngeles?.identifier).toContain('.America/Los_Angeles.1');
});

test('schedules passenger reminders once and removes stale departure dates', async () => {
  jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-08-01T04:00:00Z'));
  mockGetScheduled.mockResolvedValueOnce([
    { identifier: 'gc.departure.v1.11111111-1111-4111-8111-111111111111.2026-08-09.3' },
    { identifier: 'unrelated.notification' },
  ]);

  await reconcileDepartureReminders([
    trip(),
    trip({ id: '22222222-2222-4222-8222-222222222222', role: 'coordinator' }),
  ]);

  expect(mockCancel).toHaveBeenCalledWith(
    'gc.departure.v1.11111111-1111-4111-8111-111111111111.2026-08-09.3',
  );
  expect(mockCancel).not.toHaveBeenCalledWith('unrelated.notification');
  expect(mockSchedule).toHaveBeenCalledTimes(4);
  expect(mockSchedule).toHaveBeenCalledWith(expect.objectContaining({
    content: expect.objectContaining({
      sound: 'default',
      data: {
        route: 'trip',
        trip_id: '11111111-1111-4111-8111-111111111111',
      },
    }),
  }));

  jest.restoreAllMocks();
});

test('cancels only Group Companion departure reminders on sign-out', async () => {
  mockGetScheduled.mockResolvedValueOnce([
    { identifier: 'gc.departure.v1.trip.date.1' },
    { identifier: 'another.feature' },
  ]);

  await cancelDepartureReminders();

  expect(mockCancel).toHaveBeenCalledTimes(1);
  expect(mockCancel).toHaveBeenCalledWith('gc.departure.v1.trip.date.1');
});
