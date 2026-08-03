import {
  EMPTY_OPTIMISTIC_ATTENDANCE_COUNT,
  isRapidRepeatScan,
  reconcileAttendanceCount,
  recordOptimisticAttendanceScan,
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
