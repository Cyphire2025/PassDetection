import {
  MAX_EVENT_READINESS_SYNC_AGE_MS,
  assessCoordinatorEventReadiness,
  eventReadinessAllowsCapture,
  type CoordinatorReadinessEvidence,
  type EventReadinessInput,
} from '../event-readiness';

const NOW = Date.parse('2030-01-02T12:00:00.000Z');
const HORIZON = 8 * 60 * 60_000;

const readyEvidence: CoordinatorReadinessEvidence = {
  advertisedRosterVersion: 9,
  evidenceReadyCount: 800,
  evidenceValidUntil: new Date(NOW + HORIZON + 60_000).toISOString(),
  lastServerTime: new Date(NOW - 60_000).toISOString(),
  rosterCount: 800,
  rosterProjectionComplete: true,
  rosterVersion: 9,
};

function readyInput(overrides: Partial<EventReadinessInput> = {}): EventReadinessInput {
  return {
    activitySelected: true,
    cameraGranted: true,
    device: {
      apiReachable: true,
      availableStorageBytes: 500 * 1024 * 1024,
      batteryCharging: false,
      batteryLevel: 0.8,
      databaseWritable: true,
      lowPowerMode: false,
      networkReachable: true,
    },
    evidence: readyEvidence,
    offlineAuthorization: {
      remainingMs: HORIZON + 60_000,
      trustedServerTimeMs: NOW,
    },
    queue: { awaitingConfirmation: 0, needsReview: 0 },
    realtimeStatus: 'connected',
    schedule: {
      startsAt: new Date(NOW - 60 * 60_000).toISOString(),
      endsAt: new Date(NOW + 6 * 60 * 60_000).toISOString(),
      timeZone: 'Asia/Kolkata',
      version: 3,
    },
    tripSelected: true,
    ...overrides,
  };
}

test('reports ready only when every event-critical prerequisite is green', () => {
  const assessment = assessCoordinatorEventReadiness(readyInput());

  expect(assessment.status).toBe('ready');
  expect(assessment.checks).toHaveLength(15);
  expect(assessment.checks.every((check) => check.outcome === 'ready')).toBe(true);
});

test.each([
  ['group is missing', { tripSelected: false }],
  ['roster projection is incomplete', {
    evidence: { ...readyEvidence, rosterProjectionComplete: false },
  }],
  ['roster version is stale', {
    evidence: { ...readyEvidence, advertisedRosterVersion: 10 },
  }],
  ['QR evidence is incomplete', {
    evidence: { ...readyEvidence, evidenceReadyCount: 799 },
  }],
  ['QR evidence expires during the event', {
    evidence: {
      ...readyEvidence,
      evidenceValidUntil: new Date(NOW + HORIZON - 1).toISOString(),
    },
  }],
  ['offline authorization expires during the event', {
    offlineAuthorization: {
      remainingMs: HORIZON - 1,
      trustedServerTimeMs: NOW,
    },
  }],
  ['activity is missing', { activitySelected: false }],
  ['the activity schedule is missing', { schedule: null }],
  ['scan issues are unresolved', {
    queue: { awaitingConfirmation: 0, needsReview: 1 },
  }],
  ['camera permission is missing', { cameraGranted: false }],
  ['storage is critically low', {
    device: { ...readyInput().device!, availableStorageBytes: 50 * 1024 * 1024 },
  }],
  ['the encrypted database is not writable', {
    device: { ...readyInput().device!, databaseWritable: false },
  }],
  ['battery is critically low and unplugged', {
    device: { ...readyInput().device!, batteryLevel: 0.1 },
  }],
] as const)('blocks readiness when %s', (_label, override) => {
  const assessment = assessCoordinatorEventReadiness(readyInput(override));

  expect(assessment.status).toBe('blocked');
  expect(assessment.checks.some((check) => check.outcome === 'blocked')).toBe(true);
});

test.each([
  ['saved scans await confirmation', {
    queue: { awaitingConfirmation: 3, needsReview: 0 },
  }],
  ['the last synchronization is stale', {
    evidence: {
      ...readyEvidence,
      lastServerTime: new Date(NOW - MAX_EVENT_READINESS_SYNC_AGE_MS - 1).toISOString(),
    },
  }],
  ['realtime is degraded', { realtimeStatus: 'reconnecting' }],
  ['the API network path is offline', {
    device: { ...readyInput().device!, networkReachable: false },
  }],
  ['the internet works but the API liveness probe fails', {
    device: { ...readyInput().device!, apiReachable: false },
  }],
  ['battery is low', {
    device: { ...readyInput().device!, batteryLevel: 0.25 },
  }],
  ['storage is low', {
    device: { ...readyInput().device!, availableStorageBytes: 150 * 1024 * 1024 },
  }],
] as const)('requires attention rather than claiming ready when %s', (_label, override) => {
  const assessment = assessCoordinatorEventReadiness(readyInput(override));

  expect(assessment.status).toBe('attention');
  expect(assessment.checks.some((check) => check.outcome === 'warning')).toBe(true);
});

test('fails closed when trusted time or readiness evidence is malformed', () => {
  expect(assessCoordinatorEventReadiness(readyInput({
    evidence: { ...readyEvidence, evidenceValidUntil: 'not-a-date' },
  })).status).toBe('blocked');
  expect(assessCoordinatorEventReadiness(readyInput({
    offlineAuthorization: null,
  })).status).toBe('blocked');
  expect(assessCoordinatorEventReadiness(readyInput({
    queue: null,
  })).status).toBe('blocked');
});

test('capture policy fails closed for loading and red while explicitly accepting amber', () => {
  expect(eventReadinessAllowsCapture('loading')).toBe(false);
  expect(eventReadinessAllowsCapture('blocked')).toBe(false);
  expect(eventReadinessAllowsCapture('attention')).toBe(true);
  expect(eventReadinessAllowsCapture('ready')).toBe(true);
});

test.each([
  ['overnight', '2030-01-02T22:00:00+05:30', '2030-01-03T04:00:00+05:30', 'Asia/Kolkata'],
  ['DST spring transition', '2030-03-10T00:30:00-05:00', '2030-03-10T04:30:00-04:00', 'America/New_York'],
  ['DST fall transition', '2030-11-03T00:30:00-04:00', '2030-11-03T03:30:00-05:00', 'America/New_York'],
  ['multi-day', '2030-01-01T12:00:00Z', '2030-01-05T12:00:00Z', 'UTC'],
])('calculates %s schedules from absolute instants without a fixed eight-hour horizon', (
  _label,
  startsAt,
  endsAt,
  timeZone,
) => {
  const startsAtMs = Date.parse(startsAt);
  const assessment = assessCoordinatorEventReadiness(readyInput({
    offlineAuthorization: {
      remainingMs: Date.parse(endsAt) + 2 * 60 * 60_000 - startsAtMs + 60_000,
      trustedServerTimeMs: startsAtMs,
    },
    evidence: {
      ...readyEvidence,
      evidenceValidUntil: new Date(Date.parse(endsAt) + 2 * 60 * 60_000 + 60_000).toISOString(),
      lastServerTime: new Date(startsAtMs - 60_000).toISOString(),
    },
    schedule: { startsAt, endsAt, timeZone, version: 1 },
  }));
  expect(assessment.checks.find((check) => check.id === 'schedule')?.outcome).toBe('ready');
});

test('reports clear not-yet-valid and expired schedule states', () => {
  const future = assessCoordinatorEventReadiness(readyInput({
    schedule: {
      startsAt: new Date(NOW + 60 * 60_000).toISOString(),
      endsAt: new Date(NOW + 3 * 60 * 60_000).toISOString(),
      timeZone: 'UTC',
      version: 1,
    },
  }));
  expect(future.checks.find((check) => check.id === 'schedule')?.message)
    .toContain('not yet open');

  const expired = assessCoordinatorEventReadiness(readyInput({
    schedule: {
      startsAt: new Date(NOW - 5 * 60 * 60_000).toISOString(),
      endsAt: new Date(NOW - 3 * 60 * 60_000).toISOString(),
      timeZone: 'UTC',
      version: 1,
    },
  }));
  expect(expired.checks.find((check) => check.id === 'schedule')?.message)
    .toContain('expired');
});
