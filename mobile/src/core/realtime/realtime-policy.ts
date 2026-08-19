import { z } from 'zod';

const MAX_FRAME_BYTES = 1024;
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 30_000;

const SyncHintSchema = z.object({
  type: z.literal('sync_hint'),
  trip_id: z.string().uuid(),
  cursor: z.number().int().safe().positive(),
  invalidation: z.enum([
    'all',
    'announcements',
    'attendance',
    'documents',
    'itinerary',
    'operations',
    'roster',
  ]),
}).strict();

const ReadySchema = z.object({
  type: z.literal('ready'),
  heartbeat_seconds: z.number().int().min(5).max(60),
  idle_timeout_seconds: z.number().int().min(15).max(180),
}).strict();

const HeartbeatSchema = z.object({
  type: z.literal('heartbeat'),
}).strict();

const RealtimeFrameSchema = z.discriminatedUnion('type', [
  SyncHintSchema,
  ReadySchema,
  HeartbeatSchema,
]);

export type RealtimeSyncHint = z.infer<typeof SyncHintSchema>;
export type RealtimeServerFrame = z.infer<typeof RealtimeFrameSchema>;

export function parseRealtimeServerFrame(value: unknown): RealtimeServerFrame | null {
  if (typeof value !== 'string' || new TextEncoder().encode(value).byteLength > MAX_FRAME_BYTES) {
    return null;
  }
  try {
    const result = RealtimeFrameSchema.safeParse(JSON.parse(value) as unknown);
    return result.success ? result.data : null;
  } catch {
    return null;
  }
}

export function fullJitterReconnectDelayMs(
  attempt: number,
  random: () => number = Math.random,
): number {
  const boundedAttempt = Math.max(0, Math.min(10, Math.floor(attempt)));
  const cap = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * (2 ** boundedAttempt));
  const sample = random();
  const boundedSample = Number.isFinite(sample) ? Math.max(0, Math.min(1, sample)) : 1;
  return Math.floor(cap * boundedSample);
}

type TimeoutHandle = ReturnType<typeof setTimeout>;

export type SyncHintCoalescerOptions = Readonly<{
  onTrip: (tripId: string) => void;
  onFull: () => void;
  flushDelayMs?: number;
  maximumPendingTrips?: number;
  setTimeoutFn?: (callback: () => void, delayMs: number) => TimeoutHandle;
  clearTimeoutFn?: (handle: TimeoutHandle) => void;
}>;

/**
 * Coalesce lossy, duplicate, and reordered hints into cursor reconciliations.
 * The hinted cursor is deliberately never persisted or trusted as a commit
 * boundary; the existing sync coordinator reads its own durable cursor.
 */
export class SyncHintCoalescer {
  private readonly pending = new Map<string, number>();
  private readonly onTrip: (tripId: string) => void;
  private readonly onFull: () => void;
  private readonly flushDelayMs: number;
  private readonly maximumPendingTrips: number;
  private readonly setTimeoutFn: (callback: () => void, delayMs: number) => TimeoutHandle;
  private readonly clearTimeoutFn: (handle: TimeoutHandle) => void;
  private timeout: TimeoutHandle | null = null;
  private fullPending = false;

  constructor(options: SyncHintCoalescerOptions) {
    this.onTrip = options.onTrip;
    this.onFull = options.onFull;
    this.flushDelayMs = options.flushDelayMs ?? 250;
    this.maximumPendingTrips = options.maximumPendingTrips ?? 64;
    this.setTimeoutFn = options.setTimeoutFn ?? setTimeout;
    this.clearTimeoutFn = options.clearTimeoutFn ?? clearTimeout;
  }

  enqueue(hint: RealtimeSyncHint): void {
    const previous = this.pending.get(hint.trip_id);
    if (previous !== undefined) {
      this.pending.set(hint.trip_id, Math.max(previous, hint.cursor));
    } else if (this.pending.size >= this.maximumPendingTrips) {
      this.pending.clear();
      this.fullPending = true;
    } else if (!this.fullPending) {
      this.pending.set(hint.trip_id, hint.cursor);
    }
    if (this.timeout === null) {
      this.timeout = this.setTimeoutFn(() => this.flush(), this.flushDelayMs);
    }
  }

  flush(): void {
    if (this.timeout !== null) {
      this.clearTimeoutFn(this.timeout);
      this.timeout = null;
    }
    if (this.fullPending) {
      this.fullPending = false;
      this.pending.clear();
      this.onFull();
      return;
    }
    const tripIds = [...this.pending.keys()];
    this.pending.clear();
    for (const tripId of tripIds) this.onTrip(tripId);
  }

  dispose(): void {
    if (this.timeout !== null) this.clearTimeoutFn(this.timeout);
    this.timeout = null;
    this.pending.clear();
    this.fullPending = false;
  }
}
