import { recordMobileMetric } from '@/core/observability/mobile-observability';

import {
  ForegroundRealtimeClient,
  realtimeWebSocketUrl,
  type RealtimeSocketLike,
} from '../realtime-client';

jest.mock('@/core/observability/mobile-observability', () => ({ recordMobileMetric: jest.fn() }));

const mockedRecordMobileMetric = jest.mocked(recordMobileMetric);

const tripId = '123e4567-e89b-42d3-a456-426614174000';
const session = { sessionId: 'session-1', accessToken: 'private-access-token' };

class FakeSocket implements RealtimeSocketLike {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: Readonly<{ data: unknown }>) => void) | null = null;
  onclose: ((event: Readonly<{ code: number }>) => void) | null = null;
  onerror: (() => void) | null = null;
  readonly sent: string[] = [];
  readonly closes: { code: number | undefined; reason: string | undefined }[] = [];

  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  message(value: unknown): void {
    this.onmessage?.({ data: value });
  }

  remoteClose(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  send(value: string): void {
    this.sent.push(value);
  }

  close(code?: number, reason?: string): void {
    this.closes.push({ code, reason });
    this.remoteClose(code ?? 1000);
  }
}

describe('ForegroundRealtimeClient', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });
  afterEach(() => jest.useRealTimers());

  it('connects only in foreground and never places the bearer token in the URL', () => {
    const sockets: FakeSocket[] = [];
    const calls: { url: string; token: string }[] = [];
    const trips: string[] = [];
    const client = new ForegroundRealtimeClient({
      url: 'wss://api.example.com/api/v1/mobile/realtime',
      socketFactory: (url, token) => {
        calls.push({ url, token });
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onTripReconcile: (value) => trips.push(value),
    });
    client.start({ foreground: false, online: true, session });
    expect(sockets).toHaveLength(0);

    client.updateLifecycle({ foreground: true, online: true, session });
    expect(sockets).toHaveLength(1);
    expect(calls[0]).toEqual({
      url: 'wss://api.example.com/api/v1/mobile/realtime',
      token: 'private-access-token',
    });
    expect(calls[0]?.url).not.toContain('private-access-token');
    sockets[0]?.open();
    sockets[0]?.message(JSON.stringify({
      type: 'ready',
      heartbeat_seconds: 20,
      idle_timeout_seconds: 65,
    }));
    sockets[0]?.message(JSON.stringify({ type: 'heartbeat' }));
    expect(sockets[0]?.sent).toEqual(['{"type":"heartbeat_ack"}']);
    for (const cursor of [9, 7, 9]) {
      sockets[0]?.message(JSON.stringify({
        type: 'sync_hint',
        trip_id: tripId,
        cursor,
        invalidation: 'roster',
      }));
    }
    jest.advanceTimersByTime(250);
    expect(trips).toEqual([tripId]);

    client.updateLifecycle({ foreground: false, online: true, session });
    expect(sockets[0]?.closes.at(-1)).toEqual({ code: 1000, reason: 'inactive' });
    jest.runOnlyPendingTimers();
    expect(sockets).toHaveLength(1);
    client.stop();
  });

  it('reconnects with bounded exponential full jitter', () => {
    const sockets: FakeSocket[] = [];
    const client = new ForegroundRealtimeClient({
      url: 'wss://api.example.com/api/v1/mobile/realtime',
      random: () => 1,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });
    client.start({ foreground: true, online: true, session });
    expect(sockets).toHaveLength(1);
    sockets[0]?.remoteClose(1013);
    jest.advanceTimersByTime(499);
    expect(sockets).toHaveLength(1);
    jest.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);
    sockets[1]?.remoteClose(1013);
    jest.advanceTimersByTime(999);
    expect(sockets).toHaveLength(2);
    jest.advanceTimersByTime(1);
    expect(sockets).toHaveLength(3);
    client.stop();
  });

  it('publishes a privacy-safe connection state for degraded-mode UI', () => {
    const sockets: FakeSocket[] = [];
    const states: string[] = [];
    const client = new ForegroundRealtimeClient({
      url: 'wss://api.example.com/api/v1/mobile/realtime',
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onConnectionStateChange: (state) => states.push(state),
    });

    client.start({ foreground: true, online: true, session });
    expect(states.at(-1)).toBe('connecting');
    sockets[0]?.open();
    expect(states.at(-1)).toBe('connected');
    sockets[0]?.remoteClose(1013);
    expect(states.at(-1)).toBe('reconnecting');
    expect(mockedRecordMobileMetric).toHaveBeenCalledWith(
      'realtime_connection',
      1,
      { outcome: 'success', trigger: 'realtime' },
    );
    expect(mockedRecordMobileMetric).toHaveBeenCalledWith(
      'realtime_connection_duration',
      expect.any(Number),
      { outcome: 'success', trigger: 'realtime' },
    );
    expect(mockedRecordMobileMetric).toHaveBeenCalledWith(
      'realtime_connection',
      1,
      { outcome: 'failure', trigger: 'realtime' },
    );
    client.stop();
    expect(states.at(-1)).toBe('idle');
    expect(JSON.stringify(states)).not.toContain(session.accessToken);
    expect(JSON.stringify(mockedRecordMobileMetric.mock.calls)).not.toContain(session.accessToken);
  });

  it('requests cursor recovery on authorization close and tears down on account change', () => {
    const sockets: FakeSocket[] = [];
    const full = jest.fn();
    const client = new ForegroundRealtimeClient({
      url: 'wss://api.example.com/api/v1/mobile/realtime',
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      onFullReconcile: full,
    });
    client.start({ foreground: true, online: true, session });
    sockets[0]?.remoteClose(4401);
    expect(full).toHaveBeenCalledTimes(1);
    jest.runOnlyPendingTimers();
    expect(sockets).toHaveLength(1);

    client.updateLifecycle({
      foreground: true,
      online: true,
      session: { sessionId: 'session-2', accessToken: 'next-token' },
    });
    expect(sockets).toHaveLength(2);
    client.stop();
  });

  it('closes and reconnects when the server exceeds its idle window', () => {
    const sockets: FakeSocket[] = [];
    const client = new ForegroundRealtimeClient({
      url: 'wss://api.example.com/api/v1/mobile/realtime',
      random: () => 1,
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });
    client.start({ foreground: true, online: true, session });
    sockets[0]?.open();
    sockets[0]?.message(JSON.stringify({
      type: 'ready',
      heartbeat_seconds: 5,
      idle_timeout_seconds: 15,
    }));
    jest.advanceTimersByTime(19_999);
    expect(sockets[0]?.closes).toEqual([]);
    jest.advanceTimersByTime(1);
    expect(sockets[0]?.closes.at(-1)).toEqual({ code: 4000, reason: 'server idle' });
    client.stop();
  });

  it('treats a failed heartbeat acknowledgement as a transport failure', () => {
    const sockets: FakeSocket[] = [];
    const client = new ForegroundRealtimeClient({
      url: 'wss://api.example.com/api/v1/mobile/realtime',
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });
    client.start({ foreground: true, online: true, session });
    const socket = sockets[0];
    expect(socket).toBeDefined();
    socket?.open();
    jest.spyOn(socket as FakeSocket, 'send').mockImplementation(() => {
      throw new Error('socket closed between readyState and send');
    });
    socket?.message(JSON.stringify({ type: 'heartbeat' }));
    expect(socket?.closes.at(-1)).toEqual({ code: 4001, reason: 'transport error' });
    client.stop();
  });

  it('derives a WebSocket URL without carrying API query state', () => {
    expect(realtimeWebSocketUrl('https://api.example.com/api/v1?unsafe=1')).toBe(
      'wss://api.example.com/api/v1/mobile/realtime',
    );
    expect(realtimeWebSocketUrl('http://127.0.0.1:8000/api/v1')).toBe(
      'ws://127.0.0.1:8000/api/v1/mobile/realtime',
    );
  });
});
