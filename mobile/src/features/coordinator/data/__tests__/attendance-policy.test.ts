import { attendanceDedupeMaterial } from '../attendance-policy';

test('same owner, trip, activity and QR create the same pending-action identity material', () => {
  const first = attendanceDedupeMaterial('agency.user', 'trip-a', 'session-a', 'pdatt:signed');
  expect(attendanceDedupeMaterial('agency.user', 'trip-a', 'session-a', 'pdatt:signed')).toBe(first);
  expect(attendanceDedupeMaterial('agency.user', 'trip-a', 'session-b', 'pdatt:signed')).not.toBe(first);
  expect(attendanceDedupeMaterial('agency.user', 'trip-b', 'session-a', 'pdatt:signed')).not.toBe(first);
  expect(attendanceDedupeMaterial('agency.other', 'trip-a', 'session-a', 'pdatt:signed')).not.toBe(first);
});
