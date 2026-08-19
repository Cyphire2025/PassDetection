import * as Notifications from 'expo-notifications';

import {
  addCalendarDays,
  calendarDateTimeEpochMs,
} from '@/core/localization/date-time';
import type { Trip } from '@/features/trips/model/trip';

import { configureTripUpdateChannel } from './notification-service';

const REMINDER_PREFIX = 'gc.departure.v1.';
const MAX_DEPARTURE_REMINDERS = 48;

type ReminderCopy = Readonly<{
  daysBefore: 0 | 1 | 2 | 3;
  title: string;
  body: string;
}>;

const REMINDER_COPY: readonly ReminderCopy[] = [
  {
    daysBefore: 3,
    title: 'Your trip begins in 3 days ✈️',
    body: 'Please review your itinerary and complete any final travel preparations.',
  },
  {
    daysBefore: 2,
    title: '2 days until departure',
    body: 'Your journey is approaching. Please check your schedule and reporting details.',
  },
  {
    daysBefore: 1,
    title: 'Departure is tomorrow 🧳',
    body: 'Please keep your travel documents ready and review the latest trip updates.',
  },
  {
    daysBefore: 0,
    title: 'Your travel day is here ✈️',
    body: 'Wishing you a smooth journey. Please follow the reporting time in your itinerary.',
  },
] as const;

export type PlannedDepartureReminder = Readonly<{
  identifier: string;
  tripId: string;
  triggerDate: Date;
  title: string;
  body: string;
}>;

function reminderIdentifier(trip: Trip, daysBefore: ReminderCopy['daysBefore']): string {
  return `${REMINDER_PREFIX}${trip.id}.${trip.travelDate}.${trip.timeZone}.${daysBefore}`;
}

function triggerDate(trip: Trip, daysBefore: number): Date | null {
  if (!trip.travelDate) return null;
  const calendarDate = addCalendarDays(trip.travelDate, -daysBefore);
  if (!calendarDate) return null;
  const epochMs = calendarDateTimeEpochMs(calendarDate, trip.timeZone, 9, 0);
  return epochMs === null ? null : new Date(epochMs);
}

export function planDepartureReminders(
  trips: readonly Trip[],
  nowMs = Date.now(),
): PlannedDepartureReminder[] {
  const planned = trips
    .filter((trip) => trip.role === 'passenger' && trip.travelDate)
    .flatMap((trip) => REMINDER_COPY.flatMap((copy) => {
      const scheduledFor = triggerDate(trip, copy.daysBefore);
      if (!scheduledFor || scheduledFor.getTime() <= nowMs) return [];
      return [{
        identifier: reminderIdentifier(trip, copy.daysBefore),
        tripId: trip.id,
        triggerDate: scheduledFor,
        title: copy.title,
        body: copy.body,
      }];
    }))
    .sort((left, right) => left.triggerDate.getTime() - right.triggerDate.getTime());

  // iOS limits the number of pending local notifications. Keep capacity for
  // other operational notifications while prioritizing the nearest departures.
  return planned.slice(0, MAX_DEPARTURE_REMINDERS);
}

function notificationPermissionGranted(
  permission: Notifications.NotificationPermissionsStatus,
): boolean {
  const iosStatus = permission.ios?.status;
  return permission.granted
    || iosStatus === Notifications.IosAuthorizationStatus.PROVISIONAL
    || iosStatus === Notifications.IosAuthorizationStatus.EPHEMERAL;
}

let reconciliationTail: Promise<void> = Promise.resolve();

function serialize(operation: () => Promise<void>): Promise<void> {
  const request = reconciliationTail.catch(() => undefined).then(operation);
  reconciliationTail = request.catch(() => undefined);
  return request;
}

async function reconcile(trips: readonly Trip[]): Promise<void> {
  const permission = await Notifications.getPermissionsAsync();
  if (!notificationPermissionGranted(permission)) return;

  await configureTripUpdateChannel();
  const planned = planDepartureReminders(trips);
  const plannedIds = new Set(planned.map((reminder) => reminder.identifier));
  const scheduled = await Notifications.getAllScheduledNotificationsAsync();
  const scheduledIds = new Set(scheduled.map((request) => request.identifier));

  await Promise.all(scheduled
    .filter((request) => (
      request.identifier.startsWith(REMINDER_PREFIX)
      && !plannedIds.has(request.identifier)
    ))
    .map((request) => Notifications.cancelScheduledNotificationAsync(request.identifier)));

  for (const reminder of planned) {
    if (scheduledIds.has(reminder.identifier)) continue;
    await Notifications.scheduleNotificationAsync({
      identifier: reminder.identifier,
      content: {
        title: reminder.title,
        body: reminder.body,
        sound: 'default',
        data: {
          route: 'trip',
          trip_id: reminder.tripId,
        },
      },
      trigger: {
        type: Notifications.SchedulableTriggerInputTypes.DATE,
        date: reminder.triggerDate,
        channelId: 'trip-updates',
      },
    });
  }
}

export function reconcileDepartureReminders(trips: readonly Trip[]): Promise<void> {
  return serialize(() => reconcile(trips));
}

export function cancelDepartureReminders(): Promise<void> {
  return serialize(async () => {
    const scheduled = await Notifications.getAllScheduledNotificationsAsync();
    await Promise.all(scheduled
      .filter((request) => request.identifier.startsWith(REMINDER_PREFIX))
      .map((request) => Notifications.cancelScheduledNotificationAsync(request.identifier)));
  });
}
