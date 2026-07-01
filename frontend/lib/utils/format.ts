/**
 * Formatting Utilities
 * ====================
 * Pure, side-effect-free formatting functions.
 * No component imports. No framework dependencies.
 */

/**
 * Format a UTC ISO date string to a readable local date.
 * Example: "2024-06-15T10:30:00Z" → "15 Jun 2024"
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(isoString));
}

/**
 * Format a UTC ISO date string to date + time.
 * Example: "2024-06-15T10:30:00Z" → "15 Jun 2024, 10:30"
 */
export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(isoString));
}

/**
 * Format a relative time string.
 * Example: 2 minutes ago, in 3 hours
 */
export function formatRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const diff = (new Date(isoString).getTime() - Date.now()) / 1000;
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
    ["second", 1],
  ];
  for (const [unit, secs] of units) {
    if (Math.abs(diff) >= secs) {
      return rtf.format(Math.round(diff / secs), unit);
    }
  }
  return "just now";
}

/**
 * Format a confidence score (0–1) to a readable percentage.
 * Example: 0.9234 → "92.3%"
 */
export function formatConfidence(score: number | null | undefined): string {
  if (score === null || score === undefined) return "—";
  return `${(score * 100).toFixed(1)}%`;
}

/**
 * Truncate a string to a maximum length with ellipsis.
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return `${str.slice(0, maxLength - 3)}...`;
}

/**
 * Format bytes to human-readable file size.
 * Example: 1_500_000 → "1.4 MB"
 */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}
