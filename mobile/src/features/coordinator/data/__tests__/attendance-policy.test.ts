import {
  ATTENDANCE_QUEUE_POLICY,
  attendanceDedupeMaterial,
  attendanceQueueCutoffs,
  attendanceSessionQueueLimit,
} from '../attendance-policy';

test('same owner, trip, activity and QR create the same pending-action identity material', () => {
  const first = attendanceDedupeMaterial('agency.user', 'trip-a', 'session-a', 'pdatt:signed');
  expect(attendanceDedupeMaterial('agency.user', 'trip-a', 'session-a', 'pdatt:signed')).toBe(first);
  expect(attendanceDedupeMaterial('agency.user', 'trip-a', 'session-b', 'pdatt:signed')).not.toBe(first);
  expect(attendanceDedupeMaterial('agency.user', 'trip-b', 'session-a', 'pdatt:signed')).not.toBe(first);
  expect(attendanceDedupeMaterial('agency.other', 'trip-a', 'session-a', 'pdatt:signed')).not.toBe(first);
});

test('bounds a session queue by assigned population with operational headroom', () => {
  expect(attendanceSessionQueueLimit(5)).toBe(ATTENDANCE_QUEUE_POLICY.minActivePerSession);
  expect(attendanceSessionQueueLimit(1_000)).toBe(1_100);
  expect(attendanceSessionQueueLimit(10_000)).toBe(11_000);
  expect(attendanceSessionQueueLimit(100_000)).toBe(ATTENDANCE_QUEUE_POLICY.maxActivePerTrip);
  expect(attendanceSessionQueueLimit()).toBe(ATTENDANCE_QUEUE_POLICY.maxActivePerTrip);
});

test('derives fixed queue and audit-retention cutoffs from one timestamp', () => {
  const now = Date.parse('2030-06-01T00:00:00.000Z');

  expect(attendanceQueueCutoffs(now)).toEqual({
    active: new Date(now - ATTENDANCE_QUEUE_POLICY.maxActiveAgeMs).toISOString(),
    rejected: new Date(now - ATTENDANCE_QUEUE_POLICY.rejectedRetentionMs).toISOString(),
    receipt: new Date(now - ATTENDANCE_QUEUE_POLICY.receiptRetentionMs).toISOString(),
  });
});
