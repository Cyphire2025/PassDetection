import {
  AttendanceTokenAuthorizationError,
  authorizeAttendanceTokenForOfflineQueue,
} from '../attendance-token-authorization';

const ACCOUNT = 'agency.coordinator';
const TRIP = '11111111-1111-4111-8111-111111111111';
const SESSION = '22222222-2222-4222-8222-222222222222';
const HASH = 'a'.repeat(64);
const NOW = Date.parse('2030-01-02T12:00:00.000Z');

function activeEvidence(overrides: Record<string, unknown> = {}) {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    display_name: 'Passenger One',
    attendance_evidence_observed_at: '2030-01-02T11:59:00.000Z',
    attendance_evidence_valid_until: '2030-01-02T13:00:00.000Z',
    attendance_token_expires_at: '2030-01-03T12:00:00.000Z',
    attendance_token_hash: HASH,
    attendance_token_state: 'active',
    attendance_token_updated_at: '2030-01-02T11:58:00.000Z',
    attendance_token_version: 3,
    ...overrides,
  };
}

class AuthorizationDatabase {
  fence: Record<string, unknown> | null = {
    advertised_roster_version: 9,
    last_server_time: '2030-01-02T12:00:00.000Z',
    role: 'coordinator',
    roster_projection_complete: 1,
    roster_version: 9,
  };
  evidence: Record<string, unknown>[] = [activeEvidence()];
  session: Record<string, unknown> | null = {
    name: 'Airport departure',
    status: 'active',
    scheduled_starts_at: '2030-01-02T11:00:00.000Z',
    scheduled_ends_at: '2030-01-02T13:00:00.000Z',
    schedule_timezone: 'Asia/Kolkata',
    schedule_version: 1,
  };
  fenceParameters: unknown[] = [];
  sessionParameters: unknown[] = [];
  evidenceParameters: unknown[] = [];

  async getFirstAsync<T>(sql: string, ...parameters: unknown[]): Promise<T | null> {
    if (sql.includes('FROM attendance_sessions')) {
      this.sessionParameters = parameters;
      return this.session as T | null;
    }
    this.fenceParameters = parameters;
    return this.fence as T | null;
  }

  async getAllAsync<T>(_sql: string, ...parameters: unknown[]): Promise<T[]> {
    this.evidenceParameters = parameters;
    return this.evidence as T[];
  }
}

test('authorizes one active hash only inside the exact account and trip fence', async () => {
  const database = new AuthorizationDatabase();

  await expect(authorizeAttendanceTokenForOfflineQueue(
    database as never,
    ACCOUNT,
    TRIP,
    SESSION,
    HASH,
    NOW,
  )).resolves.toEqual({
    passengerId: '33333333-3333-4333-8333-333333333333',
    passengerLabel: 'Passenger One',
    sessionLabel: 'Airport departure',
  });

  expect(database.fenceParameters).toEqual([ACCOUNT, TRIP]);
  expect(database.sessionParameters).toEqual([ACCOUNT, TRIP, SESSION]);
  expect(database.evidenceParameters).toEqual([ACCOUNT, TRIP, HASH]);
});

test.each([
  ['missing projection', { roster_projection_complete: 0 }],
  ['stale projection', { advertised_roster_version: 10 }],
  ['wrong role', { role: 'client_manager' }],
  ['missing authenticated server clock', { last_server_time: null }],
])('rejects %s before consulting any token row', async (_label, override) => {
  const database = new AuthorizationDatabase();
  database.fence = { ...database.fence, ...override };

  await expect(authorizeAttendanceTokenForOfflineQueue(
    database as never,
    ACCOUNT,
    TRIP,
    SESSION,
    HASH,
    NOW,
  )).rejects.toMatchObject({ code: 'ROSTER_EVIDENCE_UNAVAILABLE' });
  expect(database.evidenceParameters).toEqual([]);
});

test.each([
  ['unknown or wrong-trip hash', []],
  ['ambiguous duplicate hash', [activeEvidence(), activeEvidence()]],
  ['inactive token', [activeEvidence({ attendance_token_state: 'inactive' })]],
])('rejects %s without disclosing whether another scope owns it', async (_label, evidence) => {
  const database = new AuthorizationDatabase();
  database.evidence = evidence;

  await expect(authorizeAttendanceTokenForOfflineQueue(
    database as never,
    ACCOUNT,
    TRIP,
    SESSION,
    HASH,
    NOW,
  )).rejects.toMatchObject({ code: 'QR_NOT_IN_ACTIVE_ROSTER' });
});

test('rejects expired evidence and a device clock rolled behind server time', async () => {
  const expired = new AuthorizationDatabase();
  expired.evidence = [activeEvidence({
    attendance_evidence_observed_at: '2030-01-02T11:00:00.000Z',
    attendance_evidence_valid_until: '2030-01-02T11:59:59.000Z',
    attendance_token_updated_at: '2030-01-02T10:59:00.000Z',
  })];
  await expect(authorizeAttendanceTokenForOfflineQueue(
    expired as never,
    ACCOUNT,
    TRIP,
    SESSION,
    HASH,
    NOW,
  )).rejects.toMatchObject({ code: 'QR_EVIDENCE_EXPIRED' });

  const rolledBack = new AuthorizationDatabase();
  await expect(authorizeAttendanceTokenForOfflineQueue(
    rolledBack as never,
    ACCOUNT,
    TRIP,
    SESSION,
    HASH,
    NOW - 6 * 60_000,
  )).rejects.toBeInstanceOf(AttendanceTokenAuthorizationError);
});

test('rejects malformed or overlong evidence windows', async () => {
  const database = new AuthorizationDatabase();
  database.evidence = [activeEvidence({
    attendance_evidence_observed_at: '2030-01-01T11:59:00.000Z',
  })];

  await expect(authorizeAttendanceTokenForOfflineQueue(
    database as never,
    ACCOUNT,
    TRIP,
    SESSION,
    HASH,
    NOW,
  )).rejects.toMatchObject({ code: 'QR_EVIDENCE_INVALID' });
});
