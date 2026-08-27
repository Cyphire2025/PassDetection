import type * as SQLite from 'expo-sqlite';

import { isAccessLeaseExpired } from '@/core/sync/access-expiry-policy';

import { resolveAttendanceScheduleWindow } from './attendance-schedule-policy';

const SHA256_HEX = /^[0-9a-f]{64}$/;
const MAX_EVIDENCE_WINDOW_MS = 24 * 60 * 60 * 1000;

export type AttendanceTokenAuthorizationCode =
  | 'QR_NOT_IN_ACTIVE_ROSTER'
  | 'ROSTER_EVIDENCE_UNAVAILABLE'
  | 'QR_EVIDENCE_EXPIRED'
  | 'QR_EVIDENCE_INVALID'
  | 'ACTIVITY_SCHEDULE_UNAVAILABLE'
  | 'ACTIVITY_NOT_YET_VALID'
  | 'ACTIVITY_EXPIRED';

export class AttendanceTokenAuthorizationError extends Error {
  constructor(readonly code: AttendanceTokenAuthorizationCode) {
    super('This QR cannot be safely queued from the current offline roster.');
    this.name = 'AttendanceTokenAuthorizationError';
  }
}

type RosterFenceRow = Readonly<{
  advertised_roster_version: number;
  last_server_time: string | null;
  role: string;
  roster_projection_complete: number;
  roster_version: number;
}>;

type AttendanceEvidenceRow = Readonly<{
  id: string;
  display_name: string;
  attendance_evidence_observed_at: string | null;
  attendance_evidence_valid_until: string | null;
  attendance_token_expires_at: string | null;
  attendance_token_hash: string | null;
  attendance_token_state: string;
  attendance_token_updated_at: string | null;
  attendance_token_version: number | null;
}>;

type AttendanceSessionAuthorizationRow = Readonly<{
  name: string;
  schedule_timezone: string | null;
  schedule_version: number;
  scheduled_ends_at: string | null;
  scheduled_starts_at: string | null;
  status: string;
}>;

export type AuthorizedAttendanceToken = Readonly<{
  passengerId: string;
  passengerLabel: string;
  sessionLabel: string;
}>;

function invalidDate(value: string | null): boolean {
  return value === null || !Number.isFinite(Date.parse(value));
}

/**
 * Prove that a scanned bearer token belongs to exactly one passenger in the
 * complete, current, tenant-and-trip-scoped encrypted roster projection.
 * The raw QR is never stored in this projection or included in an error.
 */
export async function authorizeAttendanceTokenForOfflineQueue(
  database: SQLite.SQLiteDatabase,
  accountNamespace: string,
  tripId: string,
  sessionId: string,
  tokenHash: string,
  observedNowMs: number,
): Promise<AuthorizedAttendanceToken> {
  if (!SHA256_HEX.test(tokenHash) || !Number.isFinite(observedNowMs)) {
    throw new AttendanceTokenAuthorizationError('QR_EVIDENCE_INVALID');
  }

  const fence = await database.getFirstAsync<RosterFenceRow>(
    `SELECT trip.role, trip.roster_projection_complete, trip.roster_version,
            trip.advertised_roster_version, cursor.last_synced_at AS last_server_time
       FROM trips trip
       LEFT JOIN sync_cursors cursor
         ON cursor.account_namespace = trip.account_namespace AND cursor.trip_id = trip.id
      WHERE trip.account_namespace = ? AND trip.id = ?
      LIMIT 1`,
    accountNamespace,
    tripId,
  );
  if (
    !fence
    || fence.role !== 'coordinator'
    || fence.roster_projection_complete !== 1
    || !Number.isSafeInteger(fence.roster_version)
    || fence.roster_version < 0
    || fence.roster_version !== fence.advertised_roster_version
    || invalidDate(fence.last_server_time)
  ) {
    throw new AttendanceTokenAuthorizationError('ROSTER_EVIDENCE_UNAVAILABLE');
  }

  const session = await database.getFirstAsync<AttendanceSessionAuthorizationRow>(
    `SELECT name, status, scheduled_starts_at, scheduled_ends_at,
            schedule_timezone, schedule_version
       FROM attendance_sessions
      WHERE account_namespace = ? AND trip_id = ? AND id = ?
      LIMIT 1`,
    accountNamespace,
    tripId,
    sessionId,
  );
  const scheduleWindow = resolveAttendanceScheduleWindow(
    session ? {
      startsAt: session.scheduled_starts_at,
      endsAt: session.scheduled_ends_at,
      timeZone: session.schedule_timezone,
      version: session.schedule_version,
    } : null,
    observedNowMs,
  );
  if (!session || session.status !== 'active') {
    throw new AttendanceTokenAuthorizationError('ACTIVITY_SCHEDULE_UNAVAILABLE');
  }
  if (scheduleWindow.state === 'not_yet_valid') {
    throw new AttendanceTokenAuthorizationError('ACTIVITY_NOT_YET_VALID');
  }
  if (scheduleWindow.state === 'expired') {
    throw new AttendanceTokenAuthorizationError('ACTIVITY_EXPIRED');
  }
  if (scheduleWindow.state !== 'active') {
    throw new AttendanceTokenAuthorizationError('ACTIVITY_SCHEDULE_UNAVAILABLE');
  }

  const candidates = await database.getAllAsync<AttendanceEvidenceRow>(
    `SELECT id, display_name, attendance_token_hash,
            attendance_token_version, attendance_token_state,
            attendance_token_expires_at, attendance_token_updated_at,
            attendance_evidence_observed_at, attendance_evidence_valid_until
       FROM coordinator_passengers
      WHERE account_namespace = ? AND trip_id = ?
        AND attendance_token_hash = ? COLLATE BINARY
      LIMIT 2`,
    accountNamespace,
    tripId,
    tokenHash,
  );
  if (candidates.length !== 1) {
    throw new AttendanceTokenAuthorizationError('QR_NOT_IN_ACTIVE_ROSTER');
  }

  const evidence = candidates[0];
  if (!evidence) {
    throw new AttendanceTokenAuthorizationError('QR_NOT_IN_ACTIVE_ROSTER');
  }
  if (
    evidence.attendance_token_state !== 'active'
    || evidence.attendance_token_hash !== tokenHash
  ) {
    throw new AttendanceTokenAuthorizationError('QR_NOT_IN_ACTIVE_ROSTER');
  }
  if (
    !Number.isSafeInteger(evidence.attendance_token_version)
    || (evidence.attendance_token_version ?? 0) < 1
    || invalidDate(evidence.attendance_token_expires_at)
    || invalidDate(evidence.attendance_token_updated_at)
    || invalidDate(evidence.attendance_evidence_observed_at)
    || invalidDate(evidence.attendance_evidence_valid_until)
  ) {
    throw new AttendanceTokenAuthorizationError('QR_EVIDENCE_INVALID');
  }

  const tokenExpiresAt = Date.parse(evidence.attendance_token_expires_at!);
  const tokenUpdatedAt = Date.parse(evidence.attendance_token_updated_at!);
  const evidenceObservedAt = Date.parse(evidence.attendance_evidence_observed_at!);
  const evidenceValidUntil = Date.parse(evidence.attendance_evidence_valid_until!);
  if (
    tokenUpdatedAt > evidenceObservedAt
    || evidenceValidUntil <= evidenceObservedAt
    || evidenceValidUntil > tokenExpiresAt
    || evidenceValidUntil - evidenceObservedAt > MAX_EVIDENCE_WINDOW_MS
  ) {
    throw new AttendanceTokenAuthorizationError('QR_EVIDENCE_INVALID');
  }

  const lastServerTime = fence.last_server_time;
  if (
    isAccessLeaseExpired(
      { accessExpiresAt: evidence.attendance_evidence_valid_until!, lastServerTime },
      observedNowMs,
    )
    || isAccessLeaseExpired(
      { accessExpiresAt: evidence.attendance_token_expires_at!, lastServerTime },
      observedNowMs,
    )
  ) {
    throw new AttendanceTokenAuthorizationError('QR_EVIDENCE_EXPIRED');
  }
  return {
    passengerId: evidence.id,
    passengerLabel: evidence.display_name,
    sessionLabel: session.name,
  };
}
