import type { IanaTimeZone } from './time-zone';
import { englishMessages } from './messages';

export { englishMessages } from './messages';

export const DEFAULT_FORMAT_LOCALE = 'en-IN';

type CalendarDateParts = Readonly<{ year: number; month: number; day: number }>;

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})$/;

function formatLocale(locale?: string): string {
  try {
    const candidate = locale?.trim()
      || new Intl.DateTimeFormat().resolvedOptions().locale
      || DEFAULT_FORMAT_LOCALE;
    return new Intl.DateTimeFormat(candidate).resolvedOptions().locale;
  } catch {
    return DEFAULT_FORMAT_LOCALE;
  }
}

function createDateTimeFormatter(
  locale: string,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat | null {
  try {
    return new Intl.DateTimeFormat(locale, options);
  } catch {
    return null;
  }
}

export function parseCalendarDate(value: string): CalendarDateParts | null {
  const match = ISO_DATE.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const candidate = new Date(Date.UTC(year, month - 1, day));
  if (
    candidate.getUTCFullYear() !== year
    || candidate.getUTCMonth() !== month - 1
    || candidate.getUTCDate() !== day
  ) return null;
  return { year, month, day };
}

export function calendarDateOrdinal(value: string): number | null {
  const parts = parseCalendarDate(value);
  return parts ? Math.floor(Date.UTC(parts.year, parts.month - 1, parts.day) / 86_400_000) : null;
}

export function addCalendarDays(value: string, days: number): string | null {
  const parts = parseCalendarDate(value);
  if (!parts || !Number.isInteger(days)) return null;
  const shifted = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days));
  return [
    String(shifted.getUTCFullYear()).padStart(4, '0'),
    String(shifted.getUTCMonth() + 1).padStart(2, '0'),
    String(shifted.getUTCDate()).padStart(2, '0'),
  ].join('-');
}

function numericPartsAt(epochMs: number, timeZone: IanaTimeZone): Required<CalendarDateParts> & {
  hour: number;
  minute: number;
  second: number;
} | null {
  const formatter = createDateTimeFormatter('en-US-u-ca-gregory-nu-latn', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  });
  if (!formatter || typeof formatter.formatToParts !== 'function') return null;
  try {
    const values = new Map(formatter.formatToParts(new Date(epochMs)).map(
      (part) => [part.type, Number(part.value)],
    ));
    const year = values.get('year');
    const month = values.get('month');
    const day = values.get('day');
    const hour = values.get('hour');
    const minute = values.get('minute');
    const second = values.get('second');
    if ([year, month, day, hour, minute, second].some((value) => !Number.isInteger(value))) {
      return null;
    }
    return {
      year: year!,
      month: month!,
      day: day!,
      hour: hour!,
      minute: minute!,
      second: second!,
    };
  } catch {
    return null;
  }
}

export function calendarDateOrdinalAt(epochMs: number, timeZone: IanaTimeZone): number | null {
  if (!Number.isFinite(epochMs)) return null;
  const parts = numericPartsAt(epochMs, timeZone);
  return parts
    ? Math.floor(Date.UTC(parts.year, parts.month - 1, parts.day) / 86_400_000)
    : null;
}

export function calendarDateTimeEpochMs(
  value: string,
  timeZone: IanaTimeZone,
  hour: number,
  minute: number,
  second = 0,
): number | null {
  const desired = parseCalendarDate(value);
  if (
    !desired
    || !Number.isInteger(hour)
    || hour < 0
    || hour > 23
    || !Number.isInteger(minute)
    || minute < 0
    || minute > 59
    || !Number.isInteger(second)
    || second < 0
    || second > 59
  ) return null;
  const desiredWallClock = Date.UTC(
    desired.year,
    desired.month - 1,
    desired.day,
    hour,
    minute,
    second,
  );
  let candidate = desiredWallClock;

  // Fixed-point conversion avoids assuming one UTC offset and therefore
  // handles ordinary DST transitions. A skipped/ambiguous wall-clock time that
  // cannot round-trip exactly fails closed rather than inventing an instant.
  for (let iteration = 0; iteration < 4; iteration += 1) {
    const actual = numericPartsAt(candidate, timeZone);
    if (!actual) return null;
    const actualWallClock = Date.UTC(
      actual.year,
      actual.month - 1,
      actual.day,
      actual.hour,
      actual.minute,
      actual.second,
    );
    const correction = desiredWallClock - actualWallClock;
    candidate += correction;
    if (correction === 0) break;
  }

  const roundTrip = numericPartsAt(candidate, timeZone);
  return roundTrip
    && roundTrip.year === desired.year
    && roundTrip.month === desired.month
    && roundTrip.day === desired.day
    && roundTrip.hour === hour
    && roundTrip.minute === minute
    && roundTrip.second === second
    ? candidate
    : null;
}

export function startOfCalendarDateEpochMs(
  value: string,
  timeZone: IanaTimeZone,
): number | null {
  return calendarDateTimeEpochMs(value, timeZone, 0, 0);
}

export function formatCalendarDate(
  value: string,
  options: Readonly<{
    locale?: string;
    weekday?: 'long' | 'short' | 'narrow';
    month?: 'long' | 'short' | 'narrow' | 'numeric' | '2-digit';
    day?: 'numeric' | '2-digit';
    year?: 'numeric' | '2-digit';
  }> = {},
): string {
  const parts = parseCalendarDate(value);
  if (!parts) return englishMessages.dateUnavailable();
  const { locale, ...dateOptions } = options;
  const formatter = createDateTimeFormatter(formatLocale(locale), {
    timeZone: 'UTC',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...dateOptions,
  });
  if (!formatter) {
    // Calendar-only API values have no timezone conversion. Returning the
    // validated ISO date is deterministic and more useful than crashing when
    // a damaged or unexpectedly old JavaScript runtime lacks Intl data.
    return value;
  }
  try {
    return formatter.format(new Date(Date.UTC(parts.year, parts.month - 1, parts.day, 12)));
  } catch {
    return value;
  }
}

function parseInstant(value: string): Date | null {
  if (!ISO_INSTANT.test(value)) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? null : parsed;
}

export function formatInstantDate(
  value: string,
  options: Readonly<{
    locale?: string | undefined;
    timeZone?: IanaTimeZone | undefined;
  }> = {},
): string {
  const parsed = parseInstant(value);
  if (!parsed || !options.timeZone) return englishMessages.dateUnavailable();
  const formatter = createDateTimeFormatter(formatLocale(options.locale), {
    timeZone: options.timeZone,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
  if (!formatter) return englishMessages.dateUnavailable();
  try {
    return formatter.format(parsed);
  } catch {
    return englishMessages.dateUnavailable();
  }
}

export function formatInstantTime(
  value: string,
  options: Readonly<{ locale?: string; timeZone: IanaTimeZone }>,
): string {
  const parsed = parseInstant(value);
  if (!parsed) return englishMessages.dateUnavailable();
  const formatter = createDateTimeFormatter(formatLocale(options.locale), {
    timeZone: options.timeZone,
    hour: '2-digit',
    minute: '2-digit',
  });
  if (!formatter) return englishMessages.dateUnavailable();
  try {
    return formatter.format(parsed);
  } catch {
    return englishMessages.dateUnavailable();
  }
}

export function formatInstantDateTime(
  value: string,
  options: Readonly<{
    locale?: string | undefined;
    timeZone?: IanaTimeZone | undefined;
  }> = {},
): string {
  const parsed = parseInstant(value);
  if (!parsed || !options.timeZone) return englishMessages.dateUnavailable();
  const formatter = createDateTimeFormatter(formatLocale(options.locale), {
    timeZone: options.timeZone,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
  if (!formatter) return englishMessages.dateUnavailable();
  try {
    return formatter.format(parsed);
  } catch {
    return englishMessages.dateUnavailable();
  }
}
