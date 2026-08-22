import { useSessionStore } from '@/core/auth/session-store';
import { openAccountDatabase } from '@/core/storage/database';

import {
  attendanceIssueExplanation,
  listRejectedAttendanceIssues,
} from '../attendance-scan-issues';

const AGENCY = '11111111-1111-4111-8111-111111111111';
const ACCOUNT = '22222222-2222-4222-8222-222222222222';
const TRIP = '33333333-3333-4333-8333-333333333333';
const EVENT = '44444444-4444-4444-8444-444444444444';
const database = {
  getAllAsync: jest.fn(),
};

jest.mock('@/core/storage/database', () => ({
  openAccountDatabase: jest.fn(),
}));

const mockedOpenDatabase = jest.mocked(openAccountDatabase);

beforeEach(() => {
  jest.clearAllMocks();
  useSessionStore.setState({
    session: {
      accessToken: 'access-token',
      accessTokenExpiresAt: '2030-01-02T13:00:00.000Z',
      refreshTokenExpiresAt: '2030-01-03T12:00:00.000Z',
      sessionId: '55555555-5555-4555-8555-555555555555',
      networkMode: 'online',
      principal: {
        id: '66666666-6666-4666-8666-666666666666',
        accountId: ACCOUNT,
        principalType: 'coordinator',
        agencyId: AGENCY,
        passengerId: null,
        displayName: 'Coordinator',
        email: null,
        phoneNumber: null,
        forcePasswordChange: false,
      },
    },
  });
  mockedOpenDatabase.mockResolvedValue(database as never);
  database.getAllAsync.mockResolvedValue([{
    attempt_count: 2,
    created_at: '2030-01-02T11:00:00.000Z',
    idempotency_key: EVENT,
    last_error_code: 'QR_INVALID',
    updated_at: '2030-01-02T11:01:00.000Z',
  }]);
});

test('lists only safe terminal metadata inside the authenticated account and trip', async () => {
  await expect(listRejectedAttendanceIssues(TRIP)).resolves.toEqual([{
    attemptCount: 2,
    createdAt: '2030-01-02T11:00:00.000Z',
    idempotencyKey: EVENT,
    reasonCode: 'QR_INVALID',
    updatedAt: '2030-01-02T11:01:00.000Z',
  }]);

  const [sql, ...parameters] = database.getAllAsync.mock.calls[0] ?? [];
  expect(sql).not.toContain('payload_json');
  expect(sql).toContain("action_type = 'attendance.scan'");
  expect(sql).toContain("state = 'rejected'");
  expect(parameters).toEqual([`${AGENCY}.${ACCOUNT}`, TRIP]);
});

test('rejects unscoped trip identifiers before opening encrypted storage', async () => {
  await expect(listRejectedAttendanceIssues('../another-trip')).rejects.toBeTruthy();
  expect(mockedOpenDatabase).not.toHaveBeenCalled();
});

test.each([
  ['REFRESH_REQUIRED', 'roster or activity changed'],
  ['SESSION_COMPLETED', 'activity changed or closed'],
  ['QR_INVALID', 'invalid, expired, revoked'],
  ['AUTH_REVOKED', 'Authorization changed'],
  ['CAPACITY_REACHED', 'attendance limit was reached'],
  ['UNRECOGNIZED', 'server could not confirm'],
])('turns %s into bounded actionable copy without echoing the code', (code, expected) => {
  const explanation = attendanceIssueExplanation(code);
  expect(explanation).toContain(expected);
  expect(explanation).not.toContain(code);
});
