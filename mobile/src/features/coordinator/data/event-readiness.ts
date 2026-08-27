import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { openAccountDatabase } from '@/core/storage/database';
import type { MobileRealtimeStatus } from '@/core/realtime/realtime-status';

import {
  EVENT_BATTERY_BLOCK_LEVEL,
  EVENT_BATTERY_WARNING_LEVEL,
  EVENT_STORAGE_BLOCK_BYTES,
  EVENT_STORAGE_WARNING_BYTES,
  type DeviceEventReadiness,
} from './device-event-readiness';
import {
  DEFAULT_ATTENDANCE_SCHEDULE_POLICY,
  resolveAttendanceScheduleWindow,
  type AttendanceSchedule,
  type AttendanceSchedulePolicy,
  type AttendanceScheduleWindow,
} from './attendance-schedule-policy';

export const MAX_EVENT_READINESS_SYNC_AGE_MS = 15 * 60_000;

export const DEFAULT_EVENT_READINESS_SCHEDULE_POLICY = DEFAULT_ATTENDANCE_SCHEDULE_POLICY;
export type EventReadinessSchedulePolicy = AttendanceSchedulePolicy;
export type EventReadinessScheduleWindow = AttendanceScheduleWindow;

type ReadinessEvidenceRow = Readonly<{
  advertised_roster_version: number;
  evidence_ready_count: number;
  evidence_valid_until: string | null;
  last_server_time: string | null;
  roster_count: number;
  roster_projection_complete: number;
  roster_version: number;
}>;

export type CoordinatorReadinessEvidence = Readonly<{
  advertisedRosterVersion: number;
  evidenceReadyCount: number;
  evidenceValidUntil: string | null;
  lastServerTime: string | null;
  rosterCount: number;
  rosterProjectionComplete: boolean;
  rosterVersion: number;
}>;

function safeCount(value: number): number {
  return Number.isSafeInteger(value) && value >= 0 ? value : -1;
}

export async function loadCoordinatorReadinessEvidence(
  tripId: string,
): Promise<CoordinatorReadinessEvidence | null> {
  const principal = useSessionStore.getState().session?.principal;
  if (!principal || principal.principalType !== 'coordinator') {
    throw new Error('Coordinator authentication is required.');
  }
  const namespace = principalAccountNamespace(principal);
  const database = await openAccountDatabase(namespace);
  const row = await database.getFirstAsync<ReadinessEvidenceRow>(
    `SELECT trip.roster_projection_complete, trip.roster_version,
            trip.advertised_roster_version, cursor.last_synced_at AS last_server_time,
            COUNT(passenger.id) AS roster_count,
            COALESCE(SUM(CASE
              WHEN passenger.attendance_token_state = 'active'
               AND passenger.attendance_token_hash IS NOT NULL
               AND length(passenger.attendance_token_hash) = 64
               AND lower(passenger.attendance_token_hash) NOT GLOB '*[^0-9a-f]*'
               AND passenger.attendance_token_version >= 1
               AND passenger.attendance_token_expires_at IS NOT NULL
               AND passenger.attendance_token_updated_at IS NOT NULL
               AND passenger.attendance_evidence_observed_at IS NOT NULL
               AND passenger.attendance_evidence_valid_until IS NOT NULL
              THEN 1 ELSE 0 END), 0) AS evidence_ready_count,
            MIN(CASE WHEN passenger.attendance_token_state = 'active'
              THEN passenger.attendance_evidence_valid_until ELSE NULL END) AS evidence_valid_until
       FROM trips trip
       LEFT JOIN sync_cursors cursor
         ON cursor.account_namespace = trip.account_namespace AND cursor.trip_id = trip.id
       LEFT JOIN coordinator_passengers passenger
         ON passenger.account_namespace = trip.account_namespace AND passenger.trip_id = trip.id
      WHERE trip.account_namespace = ? AND trip.id = ? AND trip.role = 'coordinator'
      GROUP BY trip.id, trip.roster_projection_complete, trip.roster_version,
               trip.advertised_roster_version, cursor.last_synced_at`,
    namespace,
    tripId,
  );
  if (!row) return null;
  return {
    advertisedRosterVersion: safeCount(row.advertised_roster_version),
    evidenceReadyCount: safeCount(row.evidence_ready_count),
    evidenceValidUntil: row.evidence_valid_until,
    lastServerTime: row.last_server_time,
    rosterCount: safeCount(row.roster_count),
    rosterProjectionComplete: row.roster_projection_complete === 1,
    rosterVersion: safeCount(row.roster_version),
  };
}

export type EventReadinessCheck = Readonly<{
  id:
    | 'trip'
    | 'roster'
    | 'qr_evidence'
    | 'offline_authorization'
    | 'activity'
    | 'schedule'
    | 'queue'
    | 'scan_issues'
    | 'last_sync'
    | 'camera'
    | 'realtime'
    | 'storage'
    | 'database'
    | 'network'
    | 'battery';
  label: string;
  message: string;
  outcome: 'ready' | 'warning' | 'blocked';
}>;

export type EventReadinessInput = Readonly<{
  activitySelected: boolean;
  cameraGranted: boolean;
  device: DeviceEventReadiness | null;
  evidence: CoordinatorReadinessEvidence | null;
  offlineAuthorization: Readonly<{
    remainingMs: number;
    trustedServerTimeMs: number;
  }> | null;
  queue: Readonly<{
    awaitingConfirmation: number;
    needsReview: number;
  }> | null;
  realtimeStatus: MobileRealtimeStatus;
  schedule: AttendanceSchedule | null;
  schedulePolicy?: EventReadinessSchedulePolicy;
  tripSelected: boolean;
}>;

function validTimestamp(value: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export type EventReadinessAssessment = Readonly<{
  checks: readonly EventReadinessCheck[];
  status: 'ready' | 'attention' | 'blocked';
}>;

export type EventReadinessCaptureGate = EventReadinessAssessment['status'] | 'loading';

export const resolveEventReadinessScheduleWindow = resolveAttendanceScheduleWindow;

/**
 * Amber readiness is deliberately capture-safe: every event-critical control is
 * green, while only operational warnings such as an offline network path or
 * pending confirmations remain. Loading, red, and unverified states fail closed.
 */
export function eventReadinessAllowsCapture(gate: EventReadinessCaptureGate): boolean {
  return gate === 'ready' || gate === 'attention';
}

export function assessCoordinatorEventReadiness(
  input: EventReadinessInput,
): EventReadinessAssessment {
  const trustedNow = input.offlineAuthorization?.trustedServerTimeMs ?? null;
  const scheduleWindow = resolveEventReadinessScheduleWindow(
    input.schedule,
    trustedNow,
    input.schedulePolicy,
  );
  const requiredCoverageMs = scheduleWindow.requiredCoverageMs;
  const evidenceValidUntil = validTimestamp(input.evidence?.evidenceValidUntil ?? null);
  const lastServerTime = validTimestamp(input.evidence?.lastServerTime ?? null);
  const rosterReady = Boolean(
    input.evidence
    && input.evidence.rosterProjectionComplete
    && input.evidence.rosterCount > 0
    && input.evidence.rosterVersion >= 0
    && input.evidence.rosterVersion === input.evidence.advertisedRosterVersion,
  );
  const evidenceReady = Boolean(
    rosterReady
    && input.evidence
    && input.evidence.evidenceReadyCount === input.evidence.rosterCount
    && trustedNow !== null
    && evidenceValidUntil !== null
    && requiredCoverageMs !== null
    && evidenceValidUntil - trustedNow >= requiredCoverageMs,
  );
  const offlineReady = Boolean(
    input.offlineAuthorization
    && requiredCoverageMs !== null
    && input.offlineAuthorization.remainingMs >= requiredCoverageMs,
  );
  const syncAgeMs = trustedNow !== null && lastServerTime !== null
    ? Math.max(0, trustedNow - lastServerTime)
    : null;
  const storageBytes = input.device?.availableStorageBytes ?? null;
  const storageOutcome = storageBytes === null || storageBytes < EVENT_STORAGE_BLOCK_BYTES
    ? 'blocked'
    : storageBytes < EVENT_STORAGE_WARNING_BYTES ? 'warning' : 'ready';
  const batteryLevel = input.device?.batteryLevel ?? null;
  const batteryCharging = input.device?.batteryCharging === true;
  const batteryOutcome = batteryLevel === null
    ? 'warning'
    : batteryLevel < EVENT_BATTERY_BLOCK_LEVEL && !batteryCharging
      ? 'blocked'
      : batteryLevel < EVENT_BATTERY_WARNING_LEVEL || input.device?.lowPowerMode
        ? 'warning'
        : 'ready';

  const checks: EventReadinessCheck[] = [
    {
      id: 'trip',
      label: 'Assigned group',
      outcome: input.tripSelected ? 'ready' : 'blocked',
      message: input.tripSelected ? 'Selected' : 'Select the event group.',
    },
    {
      id: 'roster',
      label: 'Complete roster',
      outcome: rosterReady ? 'ready' : 'blocked',
      message: rosterReady
        ? `${input.evidence!.rosterCount} passengers at roster version ${input.evidence!.rosterVersion}`
        : 'Download the complete current roster before going offline.',
    },
    {
      id: 'qr_evidence',
      label: 'QR verification evidence',
      outcome: evidenceReady ? 'ready' : 'blocked',
      message: evidenceReady
        ? 'Valid through the configured event window.'
        : 'Refresh QR evidence; it is missing, incomplete, or expires too soon.',
    },
    {
      id: 'offline_authorization',
      label: 'Offline authorization',
      outcome: offlineReady ? 'ready' : 'blocked',
      message: offlineReady
        ? 'Signed authorization covers the event window.'
        : 'Sign in online again to renew offline authorization.',
    },
    {
      id: 'activity',
      label: 'Attendance activity',
      outcome: input.activitySelected ? 'ready' : 'blocked',
      message: input.activitySelected ? 'Selected and scannable.' : 'Select an attendance activity.',
    },
    {
      id: 'schedule',
      label: 'Scheduled activity window',
      outcome: scheduleWindow.state === 'active' ? 'ready' : 'blocked',
      message: scheduleWindow.state === 'active'
        ? `Authorized through the scheduled activity and reconciliation window (${input.schedule!.timeZone}).`
        : scheduleWindow.state === 'not_yet_valid'
          ? 'This activity is not yet open for attendance capture.'
          : scheduleWindow.state === 'expired'
            ? 'This activity and its reconciliation window have expired.'
            : scheduleWindow.state === 'outside_policy'
              ? 'This activity schedule exceeds the configured readiness policy; refresh closer to the event or contact a manager.'
              : scheduleWindow.state === 'missing'
                ? 'The server has not supplied an authoritative activity schedule.'
                : 'The activity schedule, time zone, or version is invalid.',
    },
    {
      id: 'queue',
      label: 'Pending uploads',
      outcome: input.queue === null
        ? 'blocked'
        : input.queue.awaitingConfirmation === 0 ? 'ready' : 'warning',
      message: input.queue === null
        ? 'The durable upload queue could not be verified.'
        : input.queue.awaitingConfirmation === 0
          ? 'No scans are waiting for confirmation.'
          : `${input.queue.awaitingConfirmation} saved scans still need server confirmation.`,
    },
    {
      id: 'scan_issues',
      label: 'Scan issues',
      outcome: input.queue !== null && input.queue.needsReview === 0 ? 'ready' : 'blocked',
      message: input.queue === null
        ? 'The Scan Issues queue could not be verified.'
        : input.queue.needsReview === 0
          ? 'No unresolved scan issues.'
          : `${input.queue.needsReview} scan issues require review.`,
    },
    {
      id: 'last_sync',
      label: 'Authoritative synchronization',
      outcome: syncAgeMs !== null && syncAgeMs <= MAX_EVENT_READINESS_SYNC_AGE_MS
        ? 'ready'
        : 'warning',
      message: syncAgeMs !== null && syncAgeMs <= MAX_EVENT_READINESS_SYNC_AGE_MS
        ? 'Recently synchronized with the server.'
        : 'Synchronize again before entering a poor-network venue.',
    },
    {
      id: 'camera',
      label: 'Camera permission',
      outcome: input.cameraGranted ? 'ready' : 'blocked',
      message: input.cameraGranted ? 'Granted.' : 'Allow camera access before the event.',
    },
    {
      id: 'realtime',
      label: 'Live update channel',
      outcome: input.realtimeStatus === 'connected' ? 'ready' : 'warning',
      message: input.realtimeStatus === 'connected'
        ? 'Connected.'
        : 'Degraded; manual and cursor synchronization remain available.',
    },
    {
      id: 'storage',
      label: 'Free device storage',
      outcome: storageOutcome,
      message: storageBytes === null
        ? 'Available storage could not be measured.'
        : storageOutcome === 'ready'
          ? `${Math.floor(storageBytes / (1024 * 1024))} MB available.`
          : storageOutcome === 'warning'
            ? 'Storage is running low; clear space before the event.'
            : 'Storage is critically low; clear space before scanning.',
    },
    {
      id: 'database',
      label: 'Encrypted queue writability',
      outcome: input.device?.databaseWritable ? 'ready' : 'blocked',
      message: input.device?.databaseWritable
        ? 'Encrypted local storage accepted a scoped write probe.'
        : 'Encrypted local storage is not writable; do not begin scanning.',
    },
    {
      id: 'network',
      label: 'API network path',
      outcome: input.device?.networkReachable && input.device.apiReachable ? 'ready' : 'warning',
      message: input.device?.networkReachable && input.device.apiReachable
        ? 'The API liveness endpoint is reachable for synchronization.'
        : input.device?.networkReachable
          ? 'Internet is available but the API did not pass its liveness probe.'
          : 'Offline mode only; signed authorization and local queue remain required.',
    },
    {
      id: 'battery',
      label: 'Battery and power mode',
      outcome: batteryOutcome,
      message: batteryLevel === null
        ? 'Battery level is unavailable; verify it manually.'
        : batteryOutcome === 'ready'
          ? `${Math.round(batteryLevel * 100)}% battery available.`
          : batteryOutcome === 'warning'
            ? `${Math.round(batteryLevel * 100)}% battery or power saver enabled; connect a charger.`
            : `${Math.round(batteryLevel * 100)}% battery; charging is required before scanning.`,
    },
  ];
  return {
    checks,
    status: checks.some((check) => check.outcome === 'blocked')
      ? 'blocked'
      : checks.some((check) => check.outcome === 'warning')
        ? 'attention'
        : 'ready',
  };
}
