export const DEFAULT_TRIP_TIMEZONE = "Asia/Kolkata";

const MAX_TIMEZONE_LENGTH = 64;

/**
 * Validate an IANA timezone using the same runtime primitive used to format
 * trip dates. Numeric offsets and guessed city names are deliberately rejected.
 */
export function isSupportedIanaTimeZone(value: string): boolean {
  const normalized = value.trim();
  if (
    normalized.length < 1
    || normalized.length > MAX_TIMEZONE_LENGTH
    || normalized !== value
  ) {
    return false;
  }
  try {
    new Intl.DateTimeFormat("en", { timeZone: normalized }).format(0);
    return true;
  } catch {
    return false;
  }
}

export function supportedTripTimeZones(currentValue?: string): string[] {
  let runtimeValues: string[] = [];
  try {
    runtimeValues = Intl.supportedValuesOf("timeZone");
  } catch {
    // Older browsers can still enter a valid identifier manually. The API is
    // the final authority and applies the same IANA validation server-side.
  }
  return Array.from(new Set([
    DEFAULT_TRIP_TIMEZONE,
    "UTC",
    ...(currentValue ? [currentValue] : []),
    ...runtimeValues,
  ])).sort((left, right) => left.localeCompare(right));
}
