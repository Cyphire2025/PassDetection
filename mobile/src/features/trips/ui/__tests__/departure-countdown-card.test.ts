import { departureCountdown, tripDayState } from '../../data/departure-countdown';

test('reports calendar days and a live exact countdown independently', () => {
  const now = new Date(2026, 7, 1, 12, 30, 15).getTime();
  expect(departureCountdown('2026-08-03', now)).toEqual({
    calendarDays: 2,
    days: 1,
    hours: 11,
    minutes: 29,
    seconds: 45,
    complete: false,
  });
});

test('settles cleanly once departure has arrived', () => {
  const now = new Date(2026, 7, 3, 1).getTime();
  expect(departureCountdown('2026-08-03', now)).toMatchObject({
    calendarDays: 0,
    days: 0,
    hours: 0,
    minutes: 0,
    seconds: 0,
    complete: true,
  });
});

test('counts the departure date as trip day one', () => {
  expect(tripDayState('2026-08-02', '2026-08-08', new Date(2026, 7, 2, 14).getTime())).toEqual({
    dayNumber: 1,
    phase: 'underway',
  });
  expect(tripDayState('2026-08-02', '2026-08-08', new Date(2026, 7, 5, 14).getTime())).toEqual({
    dayNumber: 4,
    phase: 'underway',
  });
});

test('marks the trip complete after its return date', () => {
  expect(tripDayState('2026-08-02', '2026-08-08', new Date(2026, 7, 9, 9).getTime())).toEqual({
    dayNumber: 7,
    phase: 'completed',
  });
});
