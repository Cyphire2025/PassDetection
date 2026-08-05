import { differenceInCalendarDays, parseISO } from 'date-fns';

const DAY_SECONDS = 86_400;

export type DepartureCountdown = {
  calendarDays: number;
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  complete: boolean;
};

export type TripDayState = {
  dayNumber: number;
  phase: 'underway' | 'completed';
};

export function departureCountdown(travelDate: string, nowMs: number): DepartureCountdown | null {
  const target = parseISO(travelDate);
  if (Number.isNaN(target.getTime())) return null;
  const now = new Date(nowMs);
  const remainingSeconds = Math.max(0, Math.floor((target.getTime() - nowMs) / 1000));
  return {
    calendarDays: Math.max(0, differenceInCalendarDays(target, now)),
    days: Math.floor(remainingSeconds / DAY_SECONDS),
    hours: Math.floor((remainingSeconds % DAY_SECONDS) / 3600),
    minutes: Math.floor((remainingSeconds % 3600) / 60),
    seconds: remainingSeconds % 60,
    complete: remainingSeconds === 0,
  };
}

export function tripDayState(
  travelDate: string,
  returnDate: string | null,
  nowMs: number,
): TripDayState | null {
  const departure = parseISO(travelDate);
  if (Number.isNaN(departure.getTime())) return null;

  const now = new Date(nowMs);
  const elapsedDays = differenceInCalendarDays(now, departure);
  if (elapsedDays < 0) return null;

  const parsedReturnDate = returnDate ? parseISO(returnDate) : null;
  const tripHasEnded = parsedReturnDate && !Number.isNaN(parsedReturnDate.getTime())
    ? differenceInCalendarDays(now, parsedReturnDate) > 0
    : false;

  if (tripHasEnded && parsedReturnDate) {
    return {
      dayNumber: Math.max(1, differenceInCalendarDays(parsedReturnDate, departure) + 1),
      phase: 'completed',
    };
  }

  return { dayNumber: elapsedDays + 1, phase: 'underway' };
}
