import * as Crypto from 'expo-crypto';

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { openAccountDatabase, withAccountTransaction } from '@/core/storage/database';
import { CoordinatorPassengerDetailSchema, AttendanceSessionSchema } from '@/features/coordinator/api/coordinator-contracts';
import { isDemoPrincipal } from './demo-data';
import { assertDemoMode } from './demo-mode';

export async function demoTripDatabase(tripId: string) {
  assertDemoMode();
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || !isDemoPrincipal(principal) || principal.principalType === 'passenger') {
    throw new Error('A sample operations account is required.');
  }
  const account = principalAccountNamespace(principal);
  const database = await openAccountDatabase(account);
  const trip = await database.getFirstAsync('SELECT id FROM trips WHERE account_namespace = ? AND id = ?', account, tripId);
  if (!trip) throw new Error('This sample trip is not assigned to the current account.');
  return { database, account, principal };
}

export type DemoRosterItem = {
  id: string; display_name: string; employee_code: string | null;
  attendance_status: 'present' | 'missing' | 'excused' | 'not_marked';
  room_number: string | null; meal_preference: string | null; has_alert: number;
};

export async function demoRoster(tripId: string) {
  const { database, account } = await demoTripDatabase(tripId);
  return database.getAllAsync<DemoRosterItem>(
    'SELECT id, display_name, employee_code, attendance_status, room_number, meal_preference, has_alert FROM coordinator_passengers WHERE account_namespace = ? AND trip_id = ? ORDER BY display_name', account, tripId,
  );
}

async function demoSessions(tripId: string) {
  const { database, account } = await demoTripDatabase(tripId);
  const rows = await database.getAllAsync<Record<string, unknown>>(
    'SELECT id, name, status, scanned_count, assigned_count, started_at, completed_at, scheduled_starts_at, scheduled_ends_at, schedule_timezone, schedule_version FROM attendance_sessions WHERE account_namespace = ? AND trip_id = ? ORDER BY started_at DESC', account, tripId,
  );
  return rows.map((row) => AttendanceSessionSchema.parse(row));
}

export async function demoPassengerDetail(tripId: string, passengerId: string) {
  const row = (await demoRoster(tripId)).find((item) => item.id === passengerId);
  if (!row) throw new Error('Sample passenger was not found.');
  const nullable = Object.fromEntries([
    'employee_type', 'staff_code', 'base_city', 'agency_dealership_name', 'zone_name',
    'phone_number', 'email', 'departure_city', 'nearest_domestic_airport', 'designation',
    'department', 'gender', 'date_of_birth', 'nationality', 'passport_surname',
    'passport_given_names', 'passport_place_of_issue', 'passport_issuing_country',
    'passport_date_of_issue', 'passport_date_of_expiry', 'roommate_summary',
    'family_relation', 'family_head_name', 'family_head_phone', 'family_head_email',
    'qualifier_relation', 'emergency_contact_name', 'emergency_contact_phone',
    'emergency_contact_relation',
  ].map((key) => [key, null]));
  return CoordinatorPassengerDetailSchema.parse({
    ...nullable, ...row, has_alert: Boolean(row.has_alert),
    hotel_name: 'Marina Bay Grand Hotel', submission_mode: 'single', submission_status: 'submitted',
    operational_remarks: 'Sample passenger record supplied by this offline demo.',
    passport_status: 'available', visa_status: row.has_alert ? 'not_available' : 'available',
    flight_ticket_status: 'available', insurance_status: 'available',
    hotel_voucher_status: 'available', other_document_status: 'not_available',
    additional_details: [], updated_at: new Date().toISOString(),
  });
}

/** Local counterparts for the operations screens; never makes a request. */
export async function demoOperationsRequest(path: string, method = 'GET', rawBody?: unknown): Promise<unknown> {
  const url = new URL(path, 'https://demo.invalid');
  const match = /^\/mobile\/(manager|coordinator)\/groups\/([0-9a-f-]{36})(\/.*)?$/.exec(url.pathname);
  if (!match) throw new Error('This operation is unavailable in the offline demo.');
  const [, role, tripId, suffix = ''] = match;
  const { database, account, principal } = await demoTripDatabase(tripId!);
  if ((role === 'manager' ? 'client_manager' : 'coordinator') !== principal.principalType) {
    throw new Error('This operation belongs to a different sample role.');
  }
  const body = rawBody && typeof rawBody === 'object' ? rawBody as Record<string, unknown> : {};
  if (suffix === '/passengers' && method === 'GET') {
    const search = (url.searchParams.get('search') ?? '').toLowerCase();
    const roster = await demoRoster(tripId!);
    const items = roster.filter((item) => `${item.display_name} ${item.employee_code}`.toLowerCase().includes(search));
    return { items: items.map((item) => role === 'manager'
      ? { id: item.id, display_name: item.display_name, employee_code: item.employee_code, visa_status: item.has_alert ? 'not_available' : 'available', flight_ticket_status: 'available' }
      : { ...item, has_alert: Boolean(item.has_alert) }), total: roster.length, next_cursor: null };
  }
  const passenger = /^\/passengers\/([0-9a-f-]{36})$/.exec(suffix);
  if (passenger && method === 'GET') return demoPassengerDetail(tripId!, passenger[1]!);
  if (suffix === '/attendance/sessions') {
    if (method === 'GET') return { items: await demoSessions(tripId!), next_cursor: null };
    if (role === 'manager' && method === 'POST') {
      const name = String(body.name ?? '').trim();
      if (name.length < 2 || name.length > 160) throw new Error('Enter an activity name between 2 and 160 characters.');
      const id = Crypto.randomUUID();
      const now = new Date().toISOString();
      const roster = await demoRoster(tripId!);
      await withAccountTransaction(database, async (tx) => {
        await tx.runAsync("INSERT INTO attendance_sessions (id, account_namespace, trip_id, name, status, scanned_count, assigned_count, started_at, completed_at, updated_at) VALUES (?, ?, ?, ?, 'active', 0, ?, ?, NULL, ?)", id, account, tripId!, name, roster.length, now, now);
        for (const item of roster) await tx.runAsync('INSERT INTO attendance_session_missing (account_namespace, trip_id, session_id, passenger_id, display_name, updated_at) VALUES (?, ?, ?, ?, ?, ?)', account, tripId!, id, item.id, item.display_name, now);
      });
      return (await demoSessions(tripId!)).find((session) => session.id === id);
    }
  }
  const activity = /^\/attendance\/sessions\/([0-9a-f-]{36})(\/roster|\/complete|\/closeout)?$/.exec(suffix);
  if (activity) {
    const sessionId = activity[1]!;
    const session = (await demoSessions(tripId!)).find((item) => item.id === sessionId);
    if (!session) throw new Error('Sample attendance activity was not found.');
    if (activity[2] === '/complete' && role === 'manager' && method === 'PUT') {
      await database.runAsync("UPDATE attendance_sessions SET status = 'completed', completed_at = ?, updated_at = ? WHERE account_namespace = ? AND trip_id = ? AND id = ?", new Date().toISOString(), new Date().toISOString(), account, tripId!, sessionId);
      return (await demoSessions(tripId!)).find((item) => item.id === sessionId);
    }
    if (activity[2] === '/closeout') {
      const now = new Date().toISOString();
      return { ready: true, checkpoint_ttl_seconds: 300, active_assignment_count: 1, ready_assignment_count: 1, missing_assignment_count: 0, stale_assignment_count: 0, nonzero_assignment_count: 0, blocked_assignment_count: 0, unresolved_count: 0, oldest_pending_age_seconds: null, coordinators: [{ coordinator_id: '00000000-0000-4000-8000-000000000013', coordinator_name: 'Demo Coordinator', state: 'ready', reported_at: now, report_age_seconds: 0, pending_count: 0, sending_count: 0, retryable_count: 0, needs_review_count: 0, unreviewed_rejected_count: 0, oldest_pending_age_seconds: null }] };
    }
    const missing = await database.getAllAsync<{ id: string; display_name: string }>('SELECT passenger_id AS id, display_name FROM attendance_session_missing WHERE account_namespace = ? AND trip_id = ? AND session_id = ?', account, tripId!, sessionId);
    const missingIds = new Set(missing.map((item) => item.id));
    const counted = (await demoRoster(tripId!)).filter((item) => !missingIds.has(item.id)).map(({ id, display_name }) => ({ id, display_name }));
    return activity[2] === '/roster'
      ? { session, items: url.searchParams.get('status') === 'counted' ? counted : missing, next_cursor: null }
      : { session, missing, next_cursor: null };
  }
  if (suffix === '/incidents' && role === 'coordinator' && method === 'POST') {
    return { client_event_id: body.client_event_id, status: 'accepted', incident_id: Crypto.randomUUID(), reason_code: null };
  }
  throw new Error('This operation is unavailable in the offline demo.');
}

export async function markDemoAttendance(tripId: string, passengerId: string): Promise<string> {
  const { database, account, principal } = await demoTripDatabase(tripId);
  if (principal.principalType !== 'coordinator') throw new Error('Coordinator demo access is required.');
  const row = (await demoRoster(tripId)).find((item) => item.id === passengerId);
  if (!row) throw new Error('This QR does not belong to a sample passenger.');
  const activity = (await demoSessions(tripId)).find((item) => item.status === 'active');
  if (!activity) throw new Error('No sample attendance activity is active.');
  let duplicate = false;
  await withAccountTransaction(database, async (tx) => {
    const missing = await tx.getFirstAsync('SELECT passenger_id FROM attendance_session_missing WHERE account_namespace = ? AND trip_id = ? AND session_id = ? AND passenger_id = ?', account, tripId, activity.id, passengerId);
    if (!missing) { duplicate = true; return; }
    await tx.runAsync('DELETE FROM attendance_session_missing WHERE account_namespace = ? AND trip_id = ? AND session_id = ? AND passenger_id = ?', account, tripId, activity.id, passengerId);
    await tx.runAsync("UPDATE coordinator_passengers SET attendance_status = 'present', has_alert = 0 WHERE account_namespace = ? AND trip_id = ? AND id = ?", account, tripId, passengerId);
    await tx.runAsync('UPDATE attendance_sessions SET scanned_count = scanned_count + 1, updated_at = ? WHERE account_namespace = ? AND trip_id = ? AND id = ?', new Date().toISOString(), account, tripId, activity.id);
    await tx.runAsync("UPDATE attendance_summaries SET present = (SELECT COUNT(*) FROM coordinator_passengers WHERE account_namespace = ? AND trip_id = ? AND attendance_status = 'present'), missing = (SELECT COUNT(*) FROM coordinator_passengers WHERE account_namespace = ? AND trip_id = ? AND attendance_status = 'missing'), not_marked = (SELECT COUNT(*) FROM coordinator_passengers WHERE account_namespace = ? AND trip_id = ? AND attendance_status = 'not_marked'), updated_at = ? WHERE account_namespace = ? AND trip_id = ?", account, tripId, account, tripId, account, tripId, new Date().toISOString(), account, tripId);
  });
  return duplicate ? `${row.display_name} was already counted.` : `${row.display_name} marked present in the local demo.`;
}
