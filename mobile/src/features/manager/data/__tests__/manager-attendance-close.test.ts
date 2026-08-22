import { apiRequest } from '@/core/api/client';

import {
  AttendanceCloseoutStatusSchema,
  completeManagerAttendanceSession,
  createManagerAttendanceSession,
  loadManagerAttendanceCloseoutStatus,
} from '../manager-operations';

jest.mock('@/core/api/client', () => ({ apiRequest: jest.fn() }));

const mockedApiRequest = jest.mocked(apiRequest);

beforeEach(() => {
  jest.clearAllMocks();
});

test('canonical attendance creation uses only the client-manager server boundary', async () => {
  const tripId = '11111111-1111-4111-8111-111111111111';
  const created = {
    id: '22222222-2222-4222-8222-222222222222',
    name: 'Airport reporting',
    status: 'active' as const,
    scanned_count: 0,
    assigned_count: 800,
    started_at: '2030-01-01T00:00:00.000Z',
    completed_at: null,
  };
  mockedApiRequest.mockResolvedValueOnce(created);

  await expect(createManagerAttendanceSession(tripId, '  Airport reporting  ')).resolves.toBe(created);

  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(mockedApiRequest).toHaveBeenCalledWith(
    `/mobile/manager/groups/${tripId}/attendance/sessions`,
    expect.objectContaining({ method: 'POST', body: { name: 'Airport reporting' } }),
  );
  expect(mockedApiRequest.mock.calls[0]?.[0]).not.toContain('/coordinator/');
});

test('global attendance close uses only the client-manager server boundary', async () => {
  const tripId = '11111111-1111-4111-8111-111111111111';
  const sessionId = '22222222-2222-4222-8222-222222222222';
  const completed = {
    id: sessionId,
    name: 'Airport reporting',
    status: 'completed' as const,
    scanned_count: 794,
    assigned_count: 800,
    started_at: '2030-01-01T00:00:00.000Z',
    completed_at: '2030-01-01T01:00:00.000Z',
  };
  mockedApiRequest.mockResolvedValueOnce(completed);

  await expect(completeManagerAttendanceSession(tripId, sessionId)).resolves.toBe(completed);

  expect(mockedApiRequest).toHaveBeenCalledTimes(1);
  expect(mockedApiRequest).toHaveBeenCalledWith(
    `/mobile/manager/groups/${tripId}/attendance/sessions/${sessionId}/complete`,
    expect.objectContaining({ method: 'PUT', body: {} }),
  );
  expect(mockedApiRequest.mock.calls[0]?.[0]).not.toContain('/coordinator/');
});

test('audited exception reason is normalized and bounded before manager close', async () => {
  mockedApiRequest.mockResolvedValueOnce({});

  await completeManagerAttendanceSession(
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    '  approved   transport emergency  ',
  );

  expect(mockedApiRequest).toHaveBeenCalledWith(
    '/mobile/manager/groups/11111111-1111-4111-8111-111111111111/attendance/sessions/22222222-2222-4222-8222-222222222222/complete',
    expect.objectContaining({
      body: { exception_reason: 'approved transport emergency' },
      method: 'PUT',
    }),
  );
  expect(() => completeManagerAttendanceSession(
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    'too short',
  )).toThrow();
});

test('manager closeout status uses a strict aggregate-only response contract', async () => {
  const response = {
    ready: false,
    checkpoint_ttl_seconds: 120,
    active_assignment_count: 0,
    ready_assignment_count: 0,
    missing_assignment_count: 0,
    stale_assignment_count: 0,
    nonzero_assignment_count: 0,
    blocked_assignment_count: 0,
    unresolved_count: 0,
    oldest_pending_age_seconds: null,
    coordinators: [],
  };
  mockedApiRequest.mockResolvedValueOnce(response);

  await expect(loadManagerAttendanceCloseoutStatus(
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
  )).resolves.toBe(response);

  expect(mockedApiRequest).toHaveBeenCalledWith(
    '/mobile/manager/groups/11111111-1111-4111-8111-111111111111/attendance/sessions/22222222-2222-4222-8222-222222222222/closeout',
    expect.objectContaining({ schema: AttendanceCloseoutStatusSchema }),
  );
  expect(AttendanceCloseoutStatusSchema.safeParse({
    ...response,
    passenger_ids: ['forbidden'],
  }).success).toBe(false);
  expect(AttendanceCloseoutStatusSchema.safeParse({
    ...response,
    ready: true,
  }).success).toBe(false);
});
