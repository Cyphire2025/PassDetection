export type AttendanceInvalidationSource =
  | "local-mutation"
  | "queue-sync"
  | "server-push";

export type AttendanceInvalidationHint = Readonly<{
  groupId: string;
  sessionId?: string;
  source: AttendanceInvalidationSource;
  occurredAt: string;
}>;

const LOCAL_EVENT_NAME = "gc:attendance-invalidated";
const BROADCAST_CHANNEL_NAME = "gc-attendance-invalidation-v1";
const MAX_IDENTIFIER_LENGTH = 128;

export function publishAttendanceInvalidationHint(
  hint: Omit<AttendanceInvalidationHint, "occurredAt"> & { occurredAt?: string },
): void {
  if (typeof window === "undefined") return;
  const normalized = normalizeAttendanceInvalidationHint({
    ...hint,
    occurredAt: hint.occurredAt ?? new Date().toISOString(),
  });
  if (!normalized) return;

  window.dispatchEvent(new CustomEvent<AttendanceInvalidationHint>(LOCAL_EVENT_NAME, {
    detail: normalized,
  }));

  if (typeof BroadcastChannel === "undefined") return;
  try {
    const channel = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
    channel.postMessage(normalized);
    channel.close();
  } catch {
    // Local invalidation already succeeded. Conditional repair polling remains
    // the cross-device fallback when a browser blocks BroadcastChannel.
  }
}

export function subscribeAttendanceInvalidationHints(
  listener: (hint: AttendanceInvalidationHint) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;

  const handleLocal = (event: Event) => {
    const hint = normalizeAttendanceInvalidationHint(
      (event as CustomEvent<unknown>).detail,
    );
    if (hint) listener(hint);
  };
  window.addEventListener(LOCAL_EVENT_NAME, handleLocal);

  let channel: BroadcastChannel | null = null;
  if (typeof BroadcastChannel !== "undefined") {
    try {
      channel = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
      channel.addEventListener("message", (event) => {
        const hint = normalizeAttendanceInvalidationHint(event.data);
        if (hint) listener(hint);
      });
    } catch {
      channel = null;
    }
  }

  return () => {
    window.removeEventListener(LOCAL_EVENT_NAME, handleLocal);
    channel?.close();
  };
}

export function normalizeAttendanceInvalidationHint(
  value: unknown,
): AttendanceInvalidationHint | null {
  if (!isRecord(value)) return null;
  if (!isIdentifier(value.groupId)) return null;
  if (value.sessionId !== undefined && !isIdentifier(value.sessionId)) return null;
  if (
    value.source !== "local-mutation" &&
    value.source !== "queue-sync" &&
    value.source !== "server-push"
  ) return null;
  if (typeof value.occurredAt !== "string" || !Number.isFinite(Date.parse(value.occurredAt))) {
    return null;
  }
  return Object.freeze({
    groupId: value.groupId,
    ...(value.sessionId === undefined ? {} : { sessionId: value.sessionId }),
    source: value.source,
    occurredAt: value.occurredAt,
  });
}

export function attendanceRepairIntervalMs({
  groupId,
  accessScope,
  hasActiveSession,
}: {
  groupId: string;
  accessScope: string;
  hasActiveSession: boolean;
}): number {
  return stableJitterMs(
    `${groupId}:${accessScope}:${hasActiveSession ? "active" : "settled"}`,
    hasActiveSession ? 5_000 : 30_000,
    hasActiveSession ? 7_000 : 40_000,
  );
}

export function stableJitterMs(seed: string, minimum: number, maximum: number): number {
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || maximum < minimum) {
    throw new RangeError("A jitter range requires finite bounds with maximum >= minimum");
  }
  let hash = 2_166_136_261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  const width = Math.floor(maximum - minimum) + 1;
  return Math.floor(minimum) + ((hash >>> 0) % width);
}

function isIdentifier(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= MAX_IDENTIFIER_LENGTH;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
