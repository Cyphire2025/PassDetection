import {
  calendarDateOrdinalAt,
  formatCalendarDate,
  formatInstantDate,
  formatInstantDateTime,
  formatInstantTime,
  parseCalendarDate,
  startOfCalendarDateEpochMs,
} from '../date-time';
import { parseIanaTimeZone } from '../time-zone';

describe('canonical trip date and time formatting', () => {
  const newYork = parseIanaTimeZone('America/New_York');

  it('validates calendar dates without a device-timezone conversion', () => {
    expect(parseCalendarDate('2024-02-29')).toEqual({ year: 2024, month: 2, day: 29 });
    expect(parseCalendarDate('2023-02-29')).toBeNull();
    expect(formatCalendarDate('2026-08-03', { locale: 'en-US' })).toBe('Aug 3, 2026');
  });

  it('resolves local midnight using the trip IANA zone across a DST boundary', () => {
    const resolved = startOfCalendarDateEpochMs('2026-03-08', newYork);

    expect(resolved).toBe(Date.parse('2026-03-08T05:00:00Z'));
    expect(calendarDateOrdinalAt(Date.parse('2026-03-08T04:59:59Z'), newYork))
      .toBeLessThan(calendarDateOrdinalAt(resolved!, newYork)!);
  });

  it('formats an exact instant in the trip zone, independently of the device zone', () => {
    expect(formatInstantTime('2026-08-03T04:30:00Z', {
      locale: 'en-GB',
      timeZone: parseIanaTimeZone('Asia/Kolkata'),
    })).toBe('10:00');
  });

  it('fails closed for malformed instants and unsupported zones', () => {
    expect(() => parseIanaTimeZone('Mars/Olympus_Mons')).toThrow(/supported IANA timezone/);
    expect(() => parseIanaTimeZone(' Asia/Kolkata ')).not.toThrow();
    expect(formatInstantTime('2026-08-03', { timeZone: newYork })).toBe('Date unavailable');
    expect(formatInstantDate('2026-08-03T04:30:00Z')).toBe('Date unavailable');
    expect(formatInstantDateTime('2026-08-03T04:30:00Z')).toBe('Date unavailable');
  });

  it('fails safely instead of using the device timezone when Hermes Intl is unavailable', () => {
    const original = Intl.DateTimeFormat;
    Object.defineProperty(Intl, 'DateTimeFormat', {
      configurable: true,
      value: undefined,
      writable: true,
    });
    try {
      expect(formatCalendarDate('2026-08-03')).toBe('2026-08-03');
      expect(formatInstantTime('2026-08-03T04:30:00Z', { timeZone: newYork }))
        .toBe('Date unavailable');
      expect(() => parseIanaTimeZone('Asia/Kolkata')).toThrow(/supported IANA timezone/);
    } finally {
      Object.defineProperty(Intl, 'DateTimeFormat', {
        configurable: true,
        value: original,
        writable: true,
      });
    }
  });
});
