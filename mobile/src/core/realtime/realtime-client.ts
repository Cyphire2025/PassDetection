import { env } from '@/core/config/env';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { requestSync } from '@/core/sync/sync-trigger';

import {
  fullJitterReconnectDelayMs,
  parseRealtimeServerFrame,
  SyncHintCoalescer,
} from './realtime-policy';

const SOCKET_CONNECTING = 0;
const SOCKET_OPEN = 1;
const MAX_INVALID_FRAMES = 3;
const DEFAULT_SERVER_IDLE_MS = 75_000;
const MIN_SERVER_IDLE_MS = 20_000;
const MAX_SERVER_IDLE_MS = 185_000;
const STABLE_CONNECTION_MS = 30_000;

type TimeoutHandle = ReturnType<typeof setTimeout>;

export type RealtimeSocketLike = {
  readonly readyState: number;
  onopen: (() => void) | null;
  onmessage: ((event: Readonly<{ data: unknown }>) => void) | null;
  onclose: ((event: Readonly<{ code: number }>) => void) | null;
  onerror: (() => void) | null;
  send: (value: string) => void;
  close: (code?: number, reason?: string) => void;
};

export type RealtimeSocketFactory = (
  url: string,
  accessToken: string,
) => RealtimeSocketLike;

export type RealtimeSessionBoundary = Readonly<{
  sessionId: string;
  accessToken: string;
}>;

export type RealtimeLifecycleState = Readonly<{
  foreground: boolean;
  online: boolean;
  session: RealtimeSessionBoundary | null;
}>;

type NativeWebSocketConstructor = new (
  url: string,
  protocols: string[] | null,
  options: Readonly<{ headers: Readonly<Record<string, string>> }>,
) => RealtimeSocketLike;

export function realtimeWebSocketUrl(apiUrl: string = env.apiUrl): string {
  const url = new URL(apiUrl);
  if (url.protocol === 'https:') url.protocol = 'wss:';
  else if (url.protocol === 'http:') url.protocol = 'ws:';
  else throw new Error('Realtime requires an HTTP(S) API base URL.');
  url.pathname = `${url.pathname.replace(/\/$/, '')}/mobile/realtime`;
  url.search = '';
  url.hash = '';
  return url.toString();
}

export function createNativeRealtimeSocket(
  url: string,
  accessToken: string,
): RealtimeSocketLike {
  const NativeWebSocket = WebSocket as unknown as NativeWebSocketConstructor;
  return new NativeWebSocket(url, null, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type ForegroundRealtimeClientOptions = Readonly<{
  url?: string;
  socketFactory?: RealtimeSocketFactory;
  random?: () => number;
  onTripReconcile?: (tripId: string) => void;
  onFullReconcile?: () => void;
  setTimeoutFn?: (callback: () => void, delayMs: number) => TimeoutHandle;
  clearTimeoutFn?: (handle: TimeoutHandle) => void;
}>;

/**
 * Foreground-only socket lifecycle. Realtime frames never mutate local data;
 * they only submit coalesced intent to the existing cursor-sync coordinator.
 */
export class ForegroundRealtimeClient {
  private readonly url: string;
  private readonly socketFactory: RealtimeSocketFactory;
  private readonly random: () => number;
  private readonly onFullReconcile: () => void;
  private readonly setTimeoutFn: (callback: () => void, delayMs: number) => TimeoutHandle;
  private readonly clearTimeoutFn: (handle: TimeoutHandle) => void;
  private readonly coalescer: SyncHintCoalescer;
  private lifecycle: RealtimeLifecycleState = {
    foreground: false,
    online: false,
    session: null,
  };
  private running = false;
  private socket: RealtimeSocketLike | null = null;
  private generation = 0;
  private retryAttempt = 0;
  private invalidFrames = 0;
  private serverIdleMs = DEFAULT_SERVER_IDLE_MS;
  private retryTimer: TimeoutHandle | null = null;
  private idleTimer: TimeoutHandle | null = null;
  private stableTimer: TimeoutHandle | null = null;

  constructor(options: ForegroundRealtimeClientOptions = {}) {
    this.url = options.url ?? realtimeWebSocketUrl();
    this.socketFactory = options.socketFactory ?? createNativeRealtimeSocket;
    this.random = options.random ?? Math.random;
    this.onFullReconcile = options.onFullReconcile ?? (() => {
      void requestSync({
        scope: 'full',
        reason: 'realtime-auth-or-overflow',
      }).catch(() => undefined);
    });
    this.setTimeoutFn = options.setTimeoutFn ?? setTimeout;
    this.clearTimeoutFn = options.clearTimeoutFn ?? clearTimeout;
    this.coalescer = new SyncHintCoalescer({
      onTrip: options.onTripReconcile ?? ((tripId) => {
        void requestSync({
          scope: 'trip',
          tripId,
          reason: 'realtime-hint',
        }).catch(() => undefined);
      }),
      onFull: this.onFullReconcile,
      setTimeoutFn: this.setTimeoutFn,
      clearTimeoutFn: this.clearTimeoutFn,
    });
  }

  start(initial: RealtimeLifecycleState): void {
    if (this.running) return;
    this.running = true;
    this.lifecycle = initial;
    this.reconcileLifecycle();
  }

  updateLifecycle(next: RealtimeLifecycleState): void {
    const previousBoundary = this.lifecycle.session;
    const boundaryChanged = (
      previousBoundary?.sessionId !== next.session?.sessionId
      || previousBoundary?.accessToken !== next.session?.accessToken
    );
    this.lifecycle = next;
    if (boundaryChanged) this.disconnectForLifecycle();
    this.reconcileLifecycle();
  }

  stop(): void {
    this.running = false;
    this.disconnectForLifecycle();
  }

  private eligible(): boolean {
    return Boolean(
      this.running
      && this.lifecycle.foreground
      && this.lifecycle.online
      && this.lifecycle.session?.accessToken,
    );
  }

  private reconcileLifecycle(): void {
    if (!this.eligible()) {
      this.disconnectForLifecycle();
      return;
    }
    if (this.socket === null && this.retryTimer === null) this.connect();
  }

  private connect(): void {
    const session = this.lifecycle.session;
    if (!session || !this.eligible()) return;
    const generation = ++this.generation;
    let socket: RealtimeSocketLike;
    try {
      socket = this.socketFactory(this.url, session.accessToken);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    this.invalidFrames = 0;
    this.serverIdleMs = DEFAULT_SERVER_IDLE_MS;

    socket.onopen = () => {
      if (!this.isCurrent(socket, generation)) return;
      this.armIdleTimer(socket, generation);
      this.clearStableTimer();
      this.stableTimer = this.setTimeoutFn(() => {
        if (this.isCurrent(socket, generation)) this.retryAttempt = 0;
      }, STABLE_CONNECTION_MS);
    };
    socket.onmessage = (event) => {
      if (!this.isCurrent(socket, generation)) return;
      const frame = parseRealtimeServerFrame(event.data);
      if (frame === null) {
        this.invalidFrames += 1;
        if (this.invalidFrames >= MAX_INVALID_FRAMES) socket.close(4002, 'invalid frame');
        return;
      }
      this.invalidFrames = 0;
      if (frame.type === 'ready') {
        this.serverIdleMs = Math.max(
          MIN_SERVER_IDLE_MS,
          Math.min(MAX_SERVER_IDLE_MS, (frame.idle_timeout_seconds + 5) * 1000),
        );
      } else if (frame.type === 'heartbeat') {
        if (socket.readyState === SOCKET_OPEN) {
          try {
            socket.send(JSON.stringify({ type: 'heartbeat_ack' }));
          } catch {
            socket.close(4001, 'transport error');
            return;
          }
        }
      } else {
        this.coalescer.enqueue(frame);
      }
      this.armIdleTimer(socket, generation);
    };
    socket.onerror = () => {
      if (this.isCurrent(socket, generation)) socket.close(4001, 'transport error');
    };
    socket.onclose = (event) => {
      if (!this.isCurrent(socket, generation)) return;
      this.socket = null;
      this.clearIdleTimer();
      this.clearStableTimer();
      if (event.code === 4401 || event.code === 4403) this.onFullReconcile();
      this.scheduleReconnect();
    };
  }

  private isCurrent(socket: RealtimeSocketLike, generation: number): boolean {
    return this.socket === socket && this.generation === generation;
  }

  private scheduleReconnect(): void {
    if (!this.eligible() || this.retryTimer !== null || this.socket !== null) return;
    const delay = fullJitterReconnectDelayMs(this.retryAttempt, this.random);
    recordMobileMetric('realtime_reconnect', 1, { trigger: 'realtime' });
    recordMobileMetric('realtime_reconnect_delay', delay, { trigger: 'realtime' });
    this.retryAttempt += 1;
    this.retryTimer = this.setTimeoutFn(() => {
      this.retryTimer = null;
      if (this.eligible()) this.connect();
    }, delay);
  }

  private armIdleTimer(socket: RealtimeSocketLike, generation: number): void {
    this.clearIdleTimer();
    this.idleTimer = this.setTimeoutFn(() => {
      if (this.isCurrent(socket, generation)) socket.close(4000, 'server idle');
    }, this.serverIdleMs);
  }

  private disconnectForLifecycle(): void {
    this.generation += 1;
    if (this.retryTimer !== null) this.clearTimeoutFn(this.retryTimer);
    this.retryTimer = null;
    this.clearIdleTimer();
    this.clearStableTimer();
    this.coalescer.dispose();
    const socket = this.socket;
    this.socket = null;
    if (socket !== null) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      if (socket.readyState === SOCKET_CONNECTING || socket.readyState === SOCKET_OPEN) {
        socket.close(1000, 'inactive');
      }
    }
  }

  private clearIdleTimer(): void {
    if (this.idleTimer !== null) this.clearTimeoutFn(this.idleTimer);
    this.idleTimer = null;
  }

  private clearStableTimer(): void {
    if (this.stableTimer !== null) this.clearTimeoutFn(this.stableTimer);
    this.stableTimer = null;
  }
}
