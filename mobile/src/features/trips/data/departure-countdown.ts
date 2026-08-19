import {
  calendarDateOrdinal,
  calendarDateOrdinalAt,
  startOfCalendarDateEpochMs,
} from '@/core/localization/date-time';
import type { IanaTimeZone } from '@/core/localization/time-zone';

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

export function departureCountdown(
  travelDate: string,
  nowMs: number,
  timeZone: IanaTimeZone,
): DepartureCountdown | null {
  const targetMs = startOfCalendarDateEpochMs(travelDate, timeZone);
  const targetOrdinal = calendarDateOrdinal(travelDate);
  const currentOrdinal = calendarDateOrdinalAt(nowMs, timeZone);
  if (targetMs === null || targetOrdinal === null || currentOrdinal === null) return null;
  const remainingSeconds = Math.max(0, Math.floor((targetMs - nowMs) / 1000));
  return {
    calendarDays: Math.max(0, targetOrdinal - currentOrdinal),
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
  timeZone: IanaTimeZone,
): TripDayState | null {
  const departureOrdinal = calendarDateOrdinal(travelDate);
  const currentOrdinal = calendarDateOrdinalAt(nowMs, timeZone);
  if (departureOrdinal === null || currentOrdinal === null) return null;
  const elapsedDays = currentOrdinal - departureOrdinal;
  if (elapsedDays < 0) return null;

  const returnOrdinal = returnDate ? calendarDateOrdinal(returnDate) : null;
  const tripHasEnded = returnOrdinal !== null && currentOrdinal > returnOrdinal;

  if (tripHasEnded && returnOrdinal !== null) {
    return {
      dayNumber: Math.max(1, returnOrdinal - departureOrdinal + 1),
      phase: 'completed',
    };
  }

  return { dayNumber: elapsedDays + 1, phase: 'underway' };
}
