import { departureCountdown, tripDayState } from '../../data/departure-countdown';
import { parseIanaTimeZone } from '@/core/localization/time-zone';

const INDIA = parseIanaTimeZone('Asia/Kolkata');

test('reports calendar days and a live exact countdown independently', () => {
  const now = Date.parse('2026-08-01T07:00:15Z');
  expect(departureCountdown('2026-08-03', now, INDIA)).toEqual({
    calendarDays: 2,
    days: 1,
    hours: 11,
    minutes: 29,
    seconds: 45,
    complete: false,
  });
});

test('settles cleanly once departure has arrived', () => {
  const now = Date.parse('2026-08-02T19:30:00Z');
  expect(departureCountdown('2026-08-03', now, INDIA)).toMatchObject({
    calendarDays: 0,
    days: 0,
    hours: 0,
    minutes: 0,
    seconds: 0,
    complete: true,
  });
});

test('counts the departure date as trip day one', () => {
  expect(tripDayState('2026-08-02', '2026-08-08', Date.parse('2026-08-02T08:30:00Z'), INDIA)).toEqual({
    dayNumber: 1,
    phase: 'underway',
  });
  expect(tripDayState('2026-08-02', '2026-08-08', Date.parse('2026-08-05T08:30:00Z'), INDIA)).toEqual({
    dayNumber: 4,
    phase: 'underway',
  });
});

test('marks the trip complete after its return date', () => {
  expect(tripDayState('2026-08-02', '2026-08-08', Date.parse('2026-08-09T03:30:00Z'), INDIA)).toEqual({
    dayNumber: 7,
    phase: 'completed',
  });
});

test('uses the trip timezone rather than the device timezone at a date boundary', () => {
  const instant = Date.parse('2026-08-01T18:30:00Z');
  const singapore = parseIanaTimeZone('Asia/Singapore');
  const losAngeles = parseIanaTimeZone('America/Los_Angeles');

  expect(tripDayState('2026-08-02', null, instant, singapore)).toEqual({
    dayNumber: 1,
    phase: 'underway',
  });
  expect(tripDayState('2026-08-02', null, instant, losAngeles)).toBeNull();
});
