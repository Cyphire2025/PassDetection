export type AttendanceSchedule = Readonly<{
  endsAt: string | null | undefined;
  startsAt: string | null | undefined;
  timeZone: string | null | undefined;
  version: number | null | undefined;
}>;

export type AttendanceSchedulePolicy = Readonly<{
  /** Scanning may begin this far before the scheduled start. */
  captureLeadMs: number;
  /** Keep authorization available for late reconciliation after schedule end. */
  reconciliationGraceMs: number;
  /** Reject an implausibly long single activity instead of silently truncating it. */
  maxActivityDurationMs: number;
  /** Require coordinators to refresh nearer to a far-future activity. */
  maxPreparationHorizonMs: number;
}>;

export const DEFAULT_ATTENDANCE_SCHEDULE_POLICY: AttendanceSchedulePolicy = {
  captureLeadMs: 15 * 60_000,
  reconciliationGraceMs: 2 * 60 * 60_000,
  maxActivityDurationMs: 7 * 24 * 60 * 60_000,
  maxPreparationHorizonMs: 14 * 24 * 60 * 60_000,
};

export type AttendanceScheduleWindow = Readonly<{
  requiredCoverageMs: number | null;
  state: 'active' | 'expired' | 'invalid' | 'missing' | 'not_yet_valid' | 'outside_policy';
}>;

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function supportedTimeZone(value: string | null | undefined): value is string {
  if (!value || value.length > 64) return false;
  try {
    return new Intl.DateTimeFormat('en-US', { timeZone: value })
      .resolvedOptions().timeZone.length > 0;
  } catch {
    return false;
  }
}

function validPolicy(policy: AttendanceSchedulePolicy): boolean {
  return [
    policy.captureLeadMs,
    policy.reconciliationGraceMs,
    policy.maxActivityDurationMs,
    policy.maxPreparationHorizonMs,
  ].every((value) => Number.isSafeInteger(value) && value >= 0)
    && policy.maxActivityDurationMs > 0
    && policy.maxPreparationHorizonMs >= policy.maxActivityDurationMs;
}

/**
 * Uses absolute ISO instants for authorization; the IANA zone is validated as
 * schedule provenance, so DST/time-zone changes cannot reinterpret a cached
 * wall-clock value.
 */
export function resolveAttendanceScheduleWindow(
  schedule: AttendanceSchedule | null,
  trustedNow: number | null,
  policy: AttendanceSchedulePolicy = DEFAULT_ATTENDANCE_SCHEDULE_POLICY,
): AttendanceScheduleWindow {
  if (!schedule) return { requiredCoverageMs: null, state: 'missing' };
  const startsAt = timestamp(schedule.startsAt);
  const endsAt = timestamp(schedule.endsAt);
  if (
    trustedNow === null
    || !Number.isFinite(trustedNow)
    || startsAt === null
    || endsAt === null
    || endsAt <= startsAt
    || !supportedTimeZone(schedule.timeZone)
    || !Number.isSafeInteger(schedule.version)
    || (schedule.version ?? 0) < 1
    || !validPolicy(policy)
  ) {
    return { requiredCoverageMs: null, state: 'invalid' };
  }
  if (endsAt - startsAt > policy.maxActivityDurationMs) {
    return { requiredCoverageMs: null, state: 'outside_policy' };
  }
  const requiredUntil = endsAt + policy.reconciliationGraceMs;
  const requiredCoverageMs = Math.max(0, requiredUntil - trustedNow);
  if (requiredCoverageMs > policy.maxPreparationHorizonMs) {
    return { requiredCoverageMs, state: 'outside_policy' };
  }
  if (trustedNow < startsAt - policy.captureLeadMs) {
    return { requiredCoverageMs, state: 'not_yet_valid' };
  }
  if (trustedNow > requiredUntil) {
    return { requiredCoverageMs: 0, state: 'expired' };
  }
  return { requiredCoverageMs, state: 'active' };
}
