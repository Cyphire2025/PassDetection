import type { SQLiteDatabase } from 'expo-sqlite';

import type { MobilePrincipal, MobileRole } from '@/core/auth/types';
import {
  calendarDateOrdinalAt,
  calendarDateTimeEpochMs,
} from '@/core/localization/date-time';
import { parseIanaTimeZone, type IanaTimeZone } from '@/core/localization/time-zone';
import { withAccountTransaction } from '@/core/storage/database';

export const DEMO_AGENCY_ID = '00000000-0000-4000-8000-000000000001';

const SINGAPORE_TIME_ZONE = parseIanaTimeZone('Asia/Singapore');
const DUBAI_TIME_ZONE = parseIanaTimeZone('Asia/Dubai');

const DEMO_PRINCIPAL_IDS: Record<MobileRole, string> = {
  passenger: '00000000-0000-4000-8000-000000000011',
  client_manager: '00000000-0000-4000-8000-000000000012',
  coordinator: '00000000-0000-4000-8000-000000000013',
};

const DEMO_DISPLAY_NAMES: Record<MobileRole, string> = {
  passenger: 'Demo Passenger',
  client_manager: 'Demo Client Manager',
  coordinator: 'Demo Coordinator',
};

type DemoTrip = {
  id: string;
  seed: number;
  name: string;
  destination: string;
  timeZone: IanaTimeZone;
  departureOffset: number;
  returnOffset: number;
};

type ItinerarySeedItem = {
  title: string;
  description: string;
  hour: number;
  minute: number;
  durationMinutes: number;
  location: string;
};

function uuid(value: number): string {
  return `00000000-0000-4000-8000-${String(value).padStart(12, '0')}`;
}

function dateOnly(offsetDays: number, timeZone: IanaTimeZone): string {
  const todayOrdinal = calendarDateOrdinalAt(Date.now(), timeZone);
  if (todayOrdinal === null) throw new Error('Demo trip timezone is unavailable.');
  const value = new Date((todayOrdinal + offsetDays) * 86_400_000);
  const year = value.getUTCFullYear();
  const month = String(value.getUTCMonth() + 1).padStart(2, '0');
  const day = String(value.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function dateTime(
  offsetDays: number,
  timeZone: IanaTimeZone,
  hour = 9,
  minute = 0,
): string {
  const calendarDate = dateOnly(offsetDays, timeZone);
  const epochMs = calendarDateTimeEpochMs(calendarDate, timeZone, hour, minute);
  if (epochMs === null) throw new Error('Demo trip wall-clock time is unavailable.');
  return new Date(epochMs).toISOString();
}

function addMinutes(value: string, minutes: number): string {
  return new Date(Date.parse(value) + minutes * 60_000).toISOString();
}

function demoTrips(role: MobileRole): DemoTrip[] {
  if (role === 'client_manager') {
    return [
      {
        id: uuid(201),
        seed: 2_000,
        name: 'Singapore Discovery · Demo',
        destination: 'Singapore',
        timeZone: SINGAPORE_TIME_ZONE,
        departureOffset: 8,
        returnOffset: 13,
      },
      {
        id: uuid(202),
        seed: 3_000,
        name: 'Dubai Leadership Retreat · Demo',
        destination: 'Dubai, UAE',
        timeZone: DUBAI_TIME_ZONE,
        departureOffset: 24,
        returnOffset: 28,
      },
    ];
  }
  if (role === 'coordinator') {
    return [
      {
        id: uuid(301),
        seed: 4_000,
        name: 'Singapore Operations Group · Demo',
        destination: 'Singapore',
        timeZone: SINGAPORE_TIME_ZONE,
        departureOffset: 8,
        returnOffset: 13,
      },
    ];
  }
  return [
    {
      id: uuid(101),
      seed: 1_000,
      name: 'Singapore Discovery · Demo',
      destination: 'Singapore',
      timeZone: SINGAPORE_TIME_ZONE,
      departureOffset: 8,
      returnOffset: 13,
    },
  ];
}

export function demoPrincipal(role: MobileRole): MobilePrincipal {
  return {
    id: DEMO_PRINCIPAL_IDS[role],
    accountId: DEMO_PRINCIPAL_IDS[role],
    principalType: role,
    agencyId: DEMO_AGENCY_ID,
    passengerId: role === 'passenger' ? DEMO_PRINCIPAL_IDS.passenger : null,
    displayName: DEMO_DISPLAY_NAMES[role],
    email: null,
    phoneNumber: null,
    forcePasswordChange: false,
  };
}

export function isDemoPrincipal(principal: MobilePrincipal): boolean {
  return (
    principal.agencyId === DEMO_AGENCY_ID &&
    DEMO_PRINCIPAL_IDS[principal.principalType] === principal.id
  );
}

async function seedItinerary(
  database: SQLiteDatabase,
  namespace: string,
  trip: DemoTrip,
): Promise<void> {
  const schedules: { title: string; offset: number; items: ItinerarySeedItem[] }[] = [
    {
      title: 'Arrival & welcome',
      offset: trip.departureOffset,
      items: [
        {
          title: 'Airport reporting',
          description: 'Meet the coordinator at the Global Connect Travels desk. Keep your QR ready.',
          hour: 5,
          minute: 30,
          durationMinutes: 60,
          location: 'Terminal 3 · Door 6',
        },
        {
          title: 'Flight departure',
          description: 'Group boarding closes 45 minutes before departure.',
          hour: 8,
          minute: 15,
          durationMinutes: 330,
          location: 'International Departures',
        },
        {
          title: 'Hotel transfer',
          description: 'Coaches depart together after baggage collection.',
          hour: 17,
          minute: 30,
          durationMinutes: 75,
          location: 'Changi Airport arrival hall',
        },
        {
          title: 'Welcome dinner',
          description: 'Smart casual dress. Vegetarian and Jain meals are pre-arranged.',
          hour: 20,
          minute: 0,
          durationMinutes: 90,
          location: 'Marina Bay Ballroom',
        },
      ],
    },
    {
      title: 'Explore & connect',
      offset: trip.departureOffset + 1,
      items: [
        {
          title: 'Breakfast',
          description: 'Please carry your room key sleeve for entry.',
          hour: 7,
          minute: 0,
          durationMinutes: 75,
          location: 'Hotel Level 3',
        },
        {
          title: 'City highlights tour',
          description: 'Coach allocation is shown by the coordinator at the lobby meeting point.',
          hour: 9,
          minute: 0,
          durationMinutes: 210,
          location: 'Hotel main lobby',
        },
        {
          title: 'Group briefing',
          description: 'Next-day timings, baggage guidance and emergency contacts.',
          hour: 16,
          minute: 30,
          durationMinutes: 45,
          location: 'Orchid Meeting Room',
        },
        {
          title: 'Dinner cruise',
          description: 'Meet in the lobby 20 minutes before coach departure.',
          hour: 19,
          minute: 0,
          durationMinutes: 150,
          location: 'Clarke Quay',
        },
      ],
    },
    {
      title: 'Conference day',
      offset: trip.departureOffset + 2,
      items: [
        {
          title: 'Conference registration',
          description: 'Wear the group badge provided in your welcome kit.',
          hour: 8,
          minute: 30,
          durationMinutes: 45,
          location: 'Convention Centre · Hall B',
        },
        {
          title: 'Opening session',
          description: 'Seating is reserved for the group until 09:25.',
          hour: 9,
          minute: 30,
          durationMinutes: 120,
          location: 'Convention Centre · Hall B',
        },
        {
          title: 'Networking lunch',
          description: 'Meal preference cards are available at the group table.',
          hour: 12,
          minute: 30,
          durationMinutes: 90,
          location: 'Atrium Restaurant',
        },
      ],
    },
  ];

  for (const [dayIndex, schedule] of schedules.entries()) {
    const dayId = uuid(trip.seed + 10 + dayIndex);
    await database.runAsync(
      `INSERT INTO itinerary_days
        (id, account_namespace, trip_id, version, day_number, calendar_date, title, sort_order)
       VALUES (?, ?, ?, 3, ?, ?, ?, ?)`,
      dayId,
      namespace,
      trip.id,
      dayIndex + 1,
      dateOnly(schedule.offset, trip.timeZone),
      schedule.title,
      dayIndex,
    );
    for (const [itemIndex, item] of schedule.items.entries()) {
      const startsAt = dateTime(schedule.offset, trip.timeZone, item.hour, item.minute);
      await database.runAsync(
        `INSERT INTO itinerary_items
          (id, account_namespace, trip_id, day_id, version, title, description, starts_at,
           ends_at, location_name, latitude, longitude, sort_order)
         VALUES (?, ?, ?, ?, 3, ?, ?, ?, ?, ?, NULL, NULL, ?)`,
        uuid(trip.seed + 100 + dayIndex * 20 + itemIndex),
        namespace,
        trip.id,
        dayId,
        item.title,
        item.description,
        startsAt,
        addMinutes(startsAt, item.durationMinutes),
        item.location,
        itemIndex,
      );
    }
  }
}

async function seedSharedTripContent(
  database: SQLiteDatabase,
  namespace: string,
  trip: DemoTrip,
  role: MobileRole,
  now: string,
): Promise<void> {
  const announcementItems = [
    {
      title: 'Meeting point confirmed',
      message: 'Airport reporting is at Terminal 3, Door 6. Look for the Global Connect Travels sign.',
      priority: 'important',
    },
    {
      title: 'Baggage reminder',
      message: 'Keep medicines, one change of clothes and charging cables in your cabin bag.',
      priority: 'normal',
    },
  ] as const;
  for (const [index, announcement] of announcementItems.entries()) {
    await database.runAsync(
      `INSERT INTO announcements
        (id, account_namespace, trip_id, version, title, message, priority,
         published_at, available_until, is_read)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      uuid(trip.seed + 300 + index),
      namespace,
      trip.id,
      index + 1,
      announcement.title,
      announcement.message,
      announcement.priority,
      dateTime(-index, trip.timeZone, 10, 0),
      dateTime(trip.returnOffset + 7, trip.timeZone, 23, 59),
      index === 1 ? 1 : 0,
    );
  }

  const commonDocuments = [
    { category: 'travel_tips', title: 'Travel tips · Demo preview' },
    { category: 'emergency_information', title: 'Emergency contacts · Demo preview' },
  ];
  for (const [index, document] of commonDocuments.entries()) {
    await database.runAsync(
      `INSERT INTO document_metadata
        (id, account_namespace, trip_id, passenger_id, scope, category, display_name,
         content_type, size_bytes, version, checksum_sha256, offline_available,
         metadata_state, updated_at, revoked_at)
       VALUES (?, ?, ?, NULL, 'common', ?, ?, 'application/pdf', ?, 1, ?, 0, 'ready', ?, NULL)`,
      uuid(trip.seed + 320 + index),
      namespace,
      trip.id,
      document.category,
      document.title,
      240_000 + index * 25_000,
      String(index + 1).repeat(64),
      now,
    );
  }

  const notifications = [
    {
      type: 'itinerary.updated',
      category: 'itinerary',
      priority: 'important',
      title: 'Itinerary refreshed',
      body: 'The airport reporting point and welcome dinner timing are ready in your trip timeline.',
      route: role === 'client_manager' ? '/(manager)/(tabs)/itinerary' : '/(passenger)/(tabs)/trip',
    },
    {
      type: 'group.reminder',
      category: 'travel',
      priority: 'normal',
      title: 'Departure checklist',
      body: 'Keep your passport, ticket and personal QR easy to reach before arriving at the airport.',
      route: role === 'coordinator' ? '/(coordinator)/operations/updates' : '/(passenger)/(tabs)/updates',
    },
  ] as const;
  for (const [index, notification] of notifications.entries()) {
    await database.runAsync(
      `INSERT INTO mobile_notifications
        (id, account_namespace, trip_id, notification_type, category, priority, title, body,
         deep_link_path, available_at, expires_at, read_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)`,
      uuid(trip.seed + 340 + index),
      namespace,
      trip.id,
      notification.type,
      notification.category,
      notification.priority,
      notification.title,
      notification.body,
      notification.route,
      dateTime(-index, trip.timeZone, 11, 15),
      dateTime(trip.returnOffset + 7, trip.timeZone, 23, 59),
      now,
    );
  }
}

async function seedPassengerContent(
  database: SQLiteDatabase,
  namespace: string,
  trip: DemoTrip,
  principalId: string,
  now: string,
): Promise<void> {
  await database.runAsync(
    `INSERT INTO passenger_profiles
      (passenger_id, account_namespace, trip_id, display_name, personal_status, updated_at)
     VALUES (?, ?, ?, 'Demo Passenger', 'Ready to travel', ?)`,
    principalId,
    namespace,
    trip.id,
    now,
  );
  await database.runAsync(
    `INSERT INTO room_assignments
      (id, account_namespace, trip_id, passenger_id, hotel_name, room_number,
       roommate_summary, version, updated_at)
     VALUES (?, ?, ?, ?, 'Marina Bay Grand Hotel', '1208', 'A. Sharma · approved roommate', 2, ?)`,
    uuid(trip.seed + 400),
    namespace,
    trip.id,
    principalId,
    now,
  );
  await database.runAsync(
    `INSERT INTO meal_information
      (id, account_namespace, trip_id, passenger_id, preference, notes, version, updated_at)
     VALUES (?, ?, ?, ?, 'Vegetarian', 'No peanuts. Airline and hotel have been notified.', 2, ?)`,
    uuid(trip.seed + 401),
    namespace,
    trip.id,
    principalId,
    now,
  );
  await database.runAsync(
    `INSERT INTO qr_metadata
      (id, account_namespace, trip_id, passenger_id, signed_payload, version, valid_from,
       valid_until, offline_allowed, updated_at)
     VALUES (?, ?, ?, ?, ?, 3, ?, ?, 1, ?)`,
    uuid(trip.seed + 402),
    namespace,
    trip.id,
    principalId,
    `GC-DEMO:${trip.id}:${principalId}:OFFLINE-PREVIEW-V3`,
    dateTime(-1, trip.timeZone, 0, 0),
    dateTime(trip.returnOffset + 2, trip.timeZone, 23, 59),
    now,
  );

  const personalDocuments = [
    ['passport', 'Passport · Demo metadata'],
    ['visa', 'Singapore visa · Demo metadata'],
    ['flight_ticket', 'Return flight ticket · Demo metadata'],
    ['insurance', 'Travel insurance · Demo metadata'],
  ] as const;
  for (const [index, document] of personalDocuments.entries()) {
    await database.runAsync(
      `INSERT INTO document_metadata
        (id, account_namespace, trip_id, passenger_id, scope, category, display_name,
         content_type, size_bytes, version, checksum_sha256, offline_available,
         metadata_state, updated_at, revoked_at)
       VALUES (?, ?, ?, ?, 'personal', ?, ?, 'application/pdf', 0, 1, '', 0, 'pending', ?, NULL)`,
      uuid(trip.seed + 420 + index),
      namespace,
      trip.id,
      principalId,
      document[0],
      document[1],
      now,
    );
  }
}

async function seedManagerContent(
  database: SQLiteDatabase,
  namespace: string,
  trip: DemoTrip,
  now: string,
  index: number,
): Promise<void> {
  const passengerCount = index === 0 ? 700 : 184;
  const attention = index === 0 ? 16 : 7;
  await database.runAsync(
    `INSERT INTO manager_readiness
      (account_namespace, trip_id, passenger_count, passports_complete, visas_available,
       tickets_available, items_needing_attention, rooms_assigned, meals_confirmed,
       version, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 5, ?)`,
    namespace,
    trip.id,
    passengerCount,
    passengerCount - attention,
    passengerCount - attention - (index === 0 ? 14 : 3),
    passengerCount - (index === 0 ? 8 : 5),
    attention,
    passengerCount - (index === 0 ? 4 : 2),
    passengerCount - (index === 0 ? 3 : 1),
    now,
  );
}

async function seedCoordinatorContent(
  database: SQLiteDatabase,
  namespace: string,
  trip: DemoTrip,
  now: string,
): Promise<void> {
  const passengers = [
    ['Aarav Mehta', 'EMP-1001', 'present', '1201', 'Vegetarian', 0],
    ['Aisha Khan', 'EMP-1002', 'present', '1202', 'Halal', 0],
    ['Ananya Rao', 'EMP-1003', 'missing', '1203', 'Jain', 1],
    ['Arjun Patel', 'EMP-1004', 'present', '1204', 'Vegetarian', 0],
    ['Diya Iyer', 'EMP-1005', 'present', '1205', 'No seafood', 0],
    ['Ishaan Gupta', 'EMP-1006', 'excused', '1206', 'Standard', 1],
    ['Kabir Singh', 'EMP-1007', 'present', '1207', 'High protein', 0],
    ['Meera Nair', 'EMP-1008', 'missing', '1208', 'Vegetarian', 1],
    ['Neha Verma', 'EMP-1009', 'present', '1209', 'Vegan', 0],
    ['Rohan Das', 'EMP-1010', 'present', '1210', 'Standard', 0],
    ['Saanvi Joshi', 'EMP-1011', 'present', '1211', 'Gluten free', 0],
    ['Vihaan Shah', 'EMP-1012', 'missing', '1212', 'Vegetarian', 1],
    ['Zara Ali', 'EMP-1013', 'present', '1213', 'Halal', 0],
    ['Dev Malhotra', 'EMP-1014', 'not_marked', null, 'Standard', 1],
  ] as const;

  for (const [index, passenger] of passengers.entries()) {
    await database.runAsync(
      `INSERT INTO coordinator_passengers
        (id, account_namespace, trip_id, display_name, employee_code, attendance_status,
         room_number, meal_preference, has_alert, roster_version, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 4, ?)`,
      uuid(trip.seed + 500 + index),
      namespace,
      trip.id,
      passenger[0],
      passenger[1],
      passenger[2],
      passenger[3],
      passenger[4],
      passenger[5],
      now,
    );
  }

  await database.runAsync(
    `INSERT INTO attendance_summaries
      (account_namespace, trip_id, total, present, missing, excused, not_marked, version, updated_at)
     VALUES (?, ?, 14, 9, 3, 1, 1, 6, ?)`,
    namespace,
    trip.id,
    now,
  );
  const sessionId = uuid(trip.seed + 550);
  await database.runAsync(
    `INSERT INTO attendance_sessions
      (id, account_namespace, trip_id, name, status, scanned_count, assigned_count,
       started_at, completed_at, updated_at)
     VALUES (?, ?, ?, 'Airport reporting', 'active', 10, 14, ?, NULL, ?)`,
    sessionId,
    namespace,
    trip.id,
    dateTime(0, trip.timeZone, 8, 0),
    now,
  );
  await database.runAsync(
    `INSERT INTO attendance_session_selection
      (account_namespace, trip_id, session_id, selected_at)
     VALUES (?, ?, ?, ?)`,
    namespace,
    trip.id,
    sessionId,
    now,
  );
  for (const index of [2, 7, 11, 13]) {
    const passenger = passengers[index];
    if (!passenger) continue;
    await database.runAsync(
      `INSERT INTO attendance_session_missing
        (account_namespace, trip_id, session_id, passenger_id, display_name, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
      namespace,
      trip.id,
      sessionId,
      uuid(trip.seed + 500 + index),
      passenger[0],
      now,
    );
  }
}

export async function seedDemoAccount(
  database: SQLiteDatabase,
  input: {
    namespace: string;
    principal: MobilePrincipal;
  },
): Promise<void> {
  const { namespace, principal } = input;
  const trips = demoTrips(principal.principalType);
  const now = new Date().toISOString();

  await withAccountTransaction(database, async (transaction) => {
    await transaction.runAsync('DELETE FROM mobile_notifications WHERE account_namespace = ?', namespace);
    await transaction.runAsync('DELETE FROM sync_cursors WHERE account_namespace = ?', namespace);
    await transaction.runAsync('DELETE FROM trips WHERE account_namespace = ?', namespace);

    for (const [index, trip] of trips.entries()) {
      const accessExpiresAt = dateTime(60, trip.timeZone, 23, 59);
      await transaction.runAsync(
        `INSERT INTO trips
          (id, account_namespace, agency_id, role, name, destination, travel_date, return_date, timezone,
           access_generation, access_expires_at, itinerary_version, common_document_version,
           personal_document_version, announcement_version, readiness_version, roster_version,
           rooming_version, meals_version, qr_version, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 3, 1, ?, 2, ?, ?, ?, ?, ?, ?)`,
        trip.id,
        namespace,
        principal.agencyId,
        principal.principalType,
        trip.name,
        trip.destination,
        dateOnly(trip.departureOffset, trip.timeZone),
        dateOnly(trip.returnOffset, trip.timeZone),
        trip.timeZone,
        accessExpiresAt,
        principal.principalType === 'passenger' ? 1 : 0,
        principal.principalType === 'client_manager' ? 5 : 0,
        principal.principalType === 'coordinator' ? 4 : 0,
        principal.principalType === 'passenger' || principal.principalType === 'coordinator' ? 2 : 0,
        principal.principalType === 'passenger' || principal.principalType === 'coordinator' ? 2 : 0,
        principal.principalType === 'passenger' ? 3 : 0,
        now,
      );
      await transaction.runAsync(
        `UPDATE trips SET
           advertised_itinerary_version = itinerary_version,
           advertised_common_document_version = common_document_version,
           advertised_personal_document_version = personal_document_version,
           advertised_announcement_version = announcement_version,
           advertised_readiness_version = readiness_version,
           advertised_roster_version = roster_version,
           advertised_rooming_version = rooming_version,
           advertised_meals_version = meals_version,
           advertised_qr_version = qr_version,
           roster_projection_complete = CASE WHEN role = 'passenger' THEN 0 ELSE 1 END
         WHERE account_namespace = ? AND id = ?`,
        namespace,
        trip.id,
      );
      await seedItinerary(transaction, namespace, trip);
      await seedSharedTripContent(transaction, namespace, trip, principal.principalType, now);
      await transaction.runAsync(
        `INSERT INTO sync_cursors
          (account_namespace, trip_id, cursor, access_generation, last_synced_at, last_error_code)
         VALUES (?, ?, 12, 1, ?, NULL)`,
        namespace,
        trip.id,
        now,
      );

      if (principal.principalType === 'passenger') {
        await seedPassengerContent(transaction, namespace, trip, principal.id, now);
      } else if (principal.principalType === 'client_manager') {
        await seedManagerContent(transaction, namespace, trip, now, index);
      } else {
        await seedCoordinatorContent(transaction, namespace, trip, now);
      }
    }
  });
}
