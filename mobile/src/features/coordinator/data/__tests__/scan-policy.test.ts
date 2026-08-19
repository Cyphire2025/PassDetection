import {
  EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
  confirmedAttendanceCount,
  isRapidRepeatScan,
  reconcileAttendanceCount,
  recordOptimisticAttendanceScan,
  restorePendingAttendanceScans,
  settleOptimisticAttendanceScans,
  visibleAttendanceCount,
} from '../scan-policy';

test('suppresses only a rapid repeat in the same attendance activity', () => {
  const previous = { sessionId: 'session-a', value: 'pdatt:signed', at: 1_000 };

  expect(isRapidRepeatScan(previous, 'session-a', 'pdatt:signed', 2_999)).toBe(true);
  expect(isRapidRepeatScan(previous, 'session-b', 'pdatt:signed', 1_100)).toBe(false);
  expect(isRapidRepeatScan(previous, 'session-a', 'pdatt:other', 1_100)).toBe(false);
  expect(isRapidRepeatScan(previous, 'session-a', 'pdatt:signed', 3_000)).toBe(false);
});

test('reconciles local scans with server progress without double counting', () => {
  let state = recordOptimisticAttendanceScan(
    EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
    'session-a',
    10,
  );
  state = recordOptimisticAttendanceScan(state, 'session-a', 10);
  expect(visibleAttendanceCount(state, 'session-a', 10)).toBe(12);

  state = reconcileAttendanceCount(state, 'session-a', 11);
  expect(state).toEqual({ sessionId: 'session-a', confirmedCount: 11, pendingCount: 1 });
  expect(visibleAttendanceCount(state, 'session-a', 11)).toBe(12);

  state = reconcileAttendanceCount(state, 'session-a', 14);
  expect(state).toEqual({ sessionId: 'session-a', confirmedCount: 14, pendingCount: 0 });
  expect(visibleAttendanceCount(state, 'session-a', 14)).toBe(14);

  state = recordOptimisticAttendanceScan(state, 'session-a', 14);
  expect(visibleAttendanceCount(state, 'session-a', 14)).toBe(15);
});

test('switching activities resets optimistic state to that activity server count', () => {
  const first = recordOptimisticAttendanceScan(
    EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
    'session-a',
    4,
  );
  expect(reconcileAttendanceCount(first, 'session-b', 7)).toEqual({
    sessionId: 'session-b',
    confirmedCount: 7,
    pendingCount: 0,
  });
});

test('settles an already-applied scan without inflating the visible server count', () => {
  const pending = recordOptimisticAttendanceScan(
    EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
    'session-a',
    9,
  );
  expect(visibleAttendanceCount(pending, 'session-a', 9)).toBe(10);

  const settled = settleOptimisticAttendanceScans(pending, 'session-a', 9, 1);
  expect(settled).toEqual({ sessionId: 'session-a', confirmedCount: 9, pendingCount: 0 });
  expect(visibleAttendanceCount(settled, 'session-a', 9)).toBe(9);
});

test('settles accepted and rejected scans against the refreshed server count exactly once', () => {
  let pending = recordOptimisticAttendanceScan(
    EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
    'session-a',
    20,
  );
  pending = recordOptimisticAttendanceScan(pending, 'session-a', 20);

  const settled = settleOptimisticAttendanceScans(pending, 'session-a', 21, 2);
  expect(settled).toEqual({ sessionId: 'session-a', confirmedCount: 21, pendingCount: 0 });
  expect(visibleAttendanceCount(settled, 'session-a', 21)).toBe(21);
});

test('counts only server-accepted scans as confirmed when the follow-up read is stale', () => {
  let pending = recordOptimisticAttendanceScan(
    EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
    'session-a',
    20,
  );
  pending = recordOptimisticAttendanceScan(pending, 'session-a', 20);

  const settled = settleOptimisticAttendanceScans(pending, 'session-a', 20, 2, 1);

  expect(settled).toEqual({ sessionId: 'session-a', confirmedCount: 21, pendingCount: 0 });
  expect(confirmedAttendanceCount(settled, 'session-a', 20)).toBe(21);
});

test('restores the durable pending count without presenting it as confirmed', () => {
  const restored = restorePendingAttendanceScans(
    EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
    'session-a',
    20,
    3,
  );

  expect(restored).toEqual({ sessionId: 'session-a', confirmedCount: 20, pendingCount: 3 });
  expect(confirmedAttendanceCount(restored, 'session-a', 20)).toBe(20);
  expect(visibleAttendanceCount(restored, 'session-a', 20)).toBe(23);
});
