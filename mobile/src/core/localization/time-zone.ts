import { z } from 'zod';

declare const ianaTimeZoneBrand: unique symbol;

export type IanaTimeZone = string & { readonly [ianaTimeZoneBrand]: true };

export const DEFAULT_TRIP_TIME_ZONE = 'Asia/Kolkata' as IanaTimeZone;

export function parseIanaTimeZone(value: unknown): IanaTimeZone {
  if (typeof value !== 'string') throw new Error('Trip timezone must be a string.');
  const normalized = value.trim();
  if (normalized.length < 1 || normalized.length > 64) {
    throw new Error('Trip timezone must be between 1 and 64 characters.');
  }
  try {
    // Formatting is intentional: construction alone is not consistently eager
    // about unsupported timezone data across JavaScript runtimes.
    new Intl.DateTimeFormat('en-US', { timeZone: normalized }).format(0);
  } catch {
    throw new Error('Trip timezone must be a supported IANA timezone identifier.');
  }
  return normalized as IanaTimeZone;
}

export const IanaTimeZoneSchema = z.string().transform((value, context): IanaTimeZone => {
  try {
    return parseIanaTimeZone(value);
  } catch (error) {
    context.addIssue({
      code: 'custom',
      message: error instanceof Error ? error.message : 'Invalid trip timezone.',
    });
    return z.NEVER;
  }
});
