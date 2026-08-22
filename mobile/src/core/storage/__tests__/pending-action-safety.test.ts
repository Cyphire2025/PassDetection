import { openAccountDatabase } from '../database';
import {
  assertDurableActionQueueSynchronized,
  durableAttendanceRecordCount,
  durableActionQueueSummary,
  UnsynchronizedActionsError,
} from '../pending-action-safety';

jest.mock('../database', () => ({
  openAccountDatabase: jest.fn(),
}));

const mockedOpenAccountDatabase = jest.mocked(openAccountDatabase);
const namespace = '11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222';

function queueDatabase(row: Record<string, number> | null) {
  const getFirstAsync = jest.fn(async () => row);
  mockedOpenAccountDatabase.mockResolvedValueOnce({ getFirstAsync } as never);
  return getFirstAsync;
}

beforeEach(() => {
  mockedOpenAccountDatabase.mockReset();
});

test('blocks sign-out for every upload-capable state and reports attendance separately', async () => {
  const getFirstAsync = queueDatabase({
    pending_count: 2,
    sending_count: 1,
    retryable_count: 3,
    unresolved_review_count: 4,
    unsynchronized_attendance_count: 5,
  });

  await expect(assertDurableActionQueueSynchronized(namespace)).rejects.toMatchObject({
    name: 'UnsynchronizedActionsError',
    code: 'UNSYNCHRONIZED_LOCAL_ACTIONS',
    summary: {
      pending: 2,
      sending: 1,
      retryable: 3,
      unresolvedReview: 4,
      unsynchronized: 6,
      unsynchronizedAttendanceScans: 5,
      unsynchronizedOtherActions: 1,
    },
  } satisfies Partial<UnsynchronizedActionsError>);
  expect(getFirstAsync).toHaveBeenCalledWith(
    expect.stringContaining("state IN ('pending', 'sending', 'retryable')"),
    namespace,
  );
});

test('allows sign-out when only encrypted rejected or needs-review evidence remains', async () => {
  queueDatabase({
    pending_count: 0,
    sending_count: 0,
    retryable_count: 0,
    unresolved_review_count: 7,
    unsynchronized_attendance_count: 0,
  });

  await expect(assertDurableActionQueueSynchronized(namespace)).resolves.toBeUndefined();
});

test.each([
  ['negative count', {
    pending_count: -1,
    sending_count: 0,
    retryable_count: 0,
    unresolved_review_count: 0,
    unsynchronized_attendance_count: 0,
  }],
  ['attendance count larger than total', {
    pending_count: 1,
    sending_count: 0,
    retryable_count: 0,
    unresolved_review_count: 0,
    unsynchronized_attendance_count: 2,
  }],
  ['missing aggregate row', null],
])('fails closed for %s', async (_label, row) => {
  queueDatabase(row);
  await expect(durableActionQueueSummary(namespace)).rejects.toThrow();
});

test('counts all attendance states before an explicitly destructive account purge', async () => {
  const getFirstAsync = queueDatabase({ attendance_count: 9 });

  await expect(durableAttendanceRecordCount(namespace)).resolves.toBe(9);
  expect(getFirstAsync).toHaveBeenCalledWith(
    expect.stringContaining("action_type = 'attendance.scan'"),
    namespace,
  );
});
