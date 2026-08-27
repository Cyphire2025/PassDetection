import { API_ENDPOINTS } from "@/lib/api/endpoints";

export const DASHBOARD_REALTIME_PATH = API_ENDPOINTS.dashboard.realtime;

const MAX_SERVER_FRAME_BYTES = 1_024;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const INVALIDATIONS = new Set([
  "all",
  "announcements",
  "attendance",
  "documents",
  "itinerary",
  "operations",
  "roster",
]);
const ATTENDANCE_INVALIDATIONS = new Set(["all", "attendance", "operations", "roster"]);
const SLOW_RECONNECT_CODES = new Set([1008, 4401, 4403]);

export type DashboardRealtimeInvalidation =
  | "all"
  | "announcements"
  | "attendance"
  | "documents"
  | "itinerary"
  | "operations"
  | "roster";

export type DashboardRealtimeServerFrame =
  | Readonly<{
      type: "ready";
      heartbeat_seconds: number;
      idle_timeout_seconds: number;
    }>
  | Readonly<{ type: "heartbeat" }>
  | Readonly<{
      type: "sync_hint";
      trip_id: string;
      cursor: number;
      invalidation: DashboardRealtimeInvalidation;
    }>;

export type DashboardRealtimeQueryPrefix = readonly unknown[];

/**
 * Maps a PII-free server hint onto existing React Query cache families.
 *
 * These hints are deliberately lossy: they never carry entity payloads and
 * they only mark canonical HTTP reads stale. Attendance keeps its dedicated
 * invalidation bus because it also wakes the durable offline queue repair
 * path. A lost socket frame is still repaired by focus/reconnect polling.
 */
export function dashboardRealtimeQueryPrefixes(
  frame: DashboardRealtimeServerFrame,
): readonly DashboardRealtimeQueryPrefix[] {
  if (frame.type !== "sync_hint") return [];

  const groupOperations = [
    "operations",
    "tour-operations",
    "groups",
    frame.trip_id,
  ] as const;
  switch (frame.invalidation) {
    case "announcements":
      return [["gc-app"]];
    case "attendance":
      return [];
    case "documents":
      return [["document-distribution"], ["gc-app"]];
    case "itinerary":
      return [["gc-app"], groupOperations];
    case "operations":
      return [groupOperations, ["operations", "rooming", frame.trip_id]];
    case "roster":
      return [
        groupOperations,
        ["operations", "rooming", frame.trip_id],
        ["passports"],
        ["document-distribution"],
        ["dashboard", "stats"],
      ];
    case "all":
      return [
        ["gc-app"],
        groupOperations,
        ["operations", "rooming", frame.trip_id],
        ["passports"],
        ["document-distribution"],
        ["dashboard", "stats"],
      ];
  }
}

export function dashboardRealtimeWebSocketUrl(
  location: Readonly<Pick<Location, "protocol" | "host">>,
): string | null {
  const socketProtocol = location.protocol === "https:"
    ? "wss:"
    : location.protocol === "http:"
      ? "ws:"
      : null;
  if (!socketProtocol || !location.host || /[/?#@\\]/.test(location.host)) return null;
  return `${socketProtocol}//${location.host}${DASHBOARD_REALTIME_PATH}`;
}

export function parseDashboardRealtimeServerFrame(
  value: unknown,
): DashboardRealtimeServerFrame | null {
  if (typeof value !== "string" || utf8ByteLength(value) > MAX_SERVER_FRAME_BYTES) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (!isRecord(parsed) || typeof parsed.type !== "string") return null;

  if (parsed.type === "heartbeat") {
    return hasExactKeys(parsed, ["type"])
      ? Object.freeze({ type: "heartbeat" as const })
      : null;
  }
  if (parsed.type === "ready") {
    if (!hasExactKeys(parsed, ["type", "heartbeat_seconds", "idle_timeout_seconds"])) {
      return null;
    }
    if (
      !isBoundedInteger(parsed.heartbeat_seconds, 5, 60)
      || !isBoundedInteger(parsed.idle_timeout_seconds, 15, 180)
      || parsed.idle_timeout_seconds <= parsed.heartbeat_seconds * 2
    ) return null;
    return Object.freeze({
      type: "ready" as const,
      heartbeat_seconds: parsed.heartbeat_seconds,
      idle_timeout_seconds: parsed.idle_timeout_seconds,
    });
  }
  if (parsed.type !== "sync_hint") return null;
  if (!hasExactKeys(parsed, ["type", "trip_id", "cursor", "invalidation"])) return null;
  if (
    typeof parsed.trip_id !== "string"
    || !UUID_PATTERN.test(parsed.trip_id)
    || !isBoundedInteger(parsed.cursor, 1, Number.MAX_SAFE_INTEGER)
    || typeof parsed.invalidation !== "string"
    || !INVALIDATIONS.has(parsed.invalidation)
  ) return null;
  return Object.freeze({
    type: "sync_hint" as const,
    trip_id: parsed.trip_id,
    cursor: parsed.cursor,
    invalidation: parsed.invalidation as DashboardRealtimeInvalidation,
  });
}

export function shouldInvalidateAttendanceFromRealtime(
  frame: DashboardRealtimeServerFrame,
): frame is Extract<DashboardRealtimeServerFrame, { type: "sync_hint" }> {
  return frame.type === "sync_hint" && ATTENDANCE_INVALIDATIONS.has(frame.invalidation);
}

export function dashboardRealtimeReconnectDelayMs(
  attempt: number,
  closeCode: number,
  entropy = Math.random(),
): number {
  const normalizedAttempt = Number.isSafeInteger(attempt)
    ? Math.max(0, Math.min(attempt, 10))
    : 0;
  const normalizedEntropy = Number.isFinite(entropy)
    ? Math.max(0, Math.min(entropy, 1))
    : 0.5;
  const base = SLOW_RECONNECT_CODES.has(closeCode)
    ? 30_000
    : Math.min(30_000, 1_000 * (2 ** normalizedAttempt));
  const jitter = Math.min(5_000, Math.round(base * 0.25 * normalizedEntropy));
  return base + jitter;
}

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

function isBoundedInteger(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= minimum
    && value <= maximum;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
