import { act, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/auth.store";
import type { User, UserRole } from "@/types";

import { subscribeAttendanceInvalidationHints } from "../services/attendance-invalidation";
import { DashboardRealtimeAttendanceBridge } from "./dashboard-realtime-attendance-bridge";

class FakeWebSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readyState = FakeWebSocket.OPEN;
  readonly sent: string[] = [];
  readonly closes: Array<Readonly<{ code: number; reason: string }>> = [];

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    FakeWebSocket.instances.push(this);
  }

  send(value: string) {
    this.sent.push(value);
  }

  close(code = 1000, reason = "") {
    if (this.readyState >= FakeWebSocket.CLOSING) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.closes.push({ code, reason });
    this.dispatchEvent(new CloseEvent("close", { code, reason }));
  }

  receive(payload: object) {
    if (this.readyState !== FakeWebSocket.OPEN) return;
    this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }
}

describe("DashboardRealtimeAttendanceBridge", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    useAuthStore.setState({
      user: user("agency_manager"),
      isAuthenticated: true,
      hasHydrated: true,
      sessionVersion: 7,
    });
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      hasHydrated: true,
      sessionVersion: 0,
    });
  });

  it("uses the cookie-only route, acknowledges heartbeats, and deduplicates attendance hints", () => {
    const hints = vi.fn();
    const unsubscribe = subscribeAttendanceInvalidationHints(hints);
    const invalidations = vi.spyOn(queryClient, "invalidateQueries");
    const view = renderBridge(queryClient);
    const socket = FakeWebSocket.instances[0];

    expect(socket?.url).toBe("ws://localhost:3000/api/v1/dashboard/realtime");
    expect(socket?.url).not.toContain("?");
    expect(socket?.readyState).toBe(FakeWebSocket.OPEN);

    act(() => {
      socket?.receive({ type: "ready", heartbeat_seconds: 20, idle_timeout_seconds: 65 });
      socket?.receive({ type: "heartbeat" });
      socket?.receive({
        type: "sync_hint",
        trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
        cursor: 4,
        invalidation: "attendance",
      });
      socket?.receive({
        type: "sync_hint",
        trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
        cursor: 4,
        invalidation: "attendance",
      });
      socket?.receive({
        type: "sync_hint",
        trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
        cursor: 5,
        invalidation: "documents",
      });
    });

    expect(socket?.sent).toEqual(['{"type":"heartbeat_ack"}']);
    expect(hints).toHaveBeenCalledTimes(1);
    expect(hints).toHaveBeenCalledWith(expect.objectContaining({
      groupId: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
      source: "server-push",
    }));
    expect(invalidations).toHaveBeenCalledTimes(2);
    expect(invalidations).toHaveBeenCalledWith({ queryKey: ["document-distribution"] });
    expect(invalidations).toHaveBeenCalledWith({ queryKey: ["gc-app"] });

    view.unmount();
    expect(socket?.closes).toContainEqual(expect.objectContaining({ code: 1000 }));
    unsubscribe();
  });

  it("does not open a dashboard socket for unsupported super-admin authority", () => {
    useAuthStore.setState({ user: user("super_admin"), sessionVersion: 8 });
    renderBridge(queryClient);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it.each(["account", "agency"] as const)(
    "closes the old socket across a real %s authority change and accepts the new owner's hints",
    (change) => {
      const owners: Array<string | null> = [];
      const invalidate = queryClient.invalidateQueries.bind(queryClient);
      const invalidations = vi.spyOn(queryClient, "invalidateQueries").mockImplementation((...args) => {
        owners.push(useAuthStore.getState().user?.id ?? null);
        return invalidate(...args);
      });
      const view = renderBridge(queryClient);
      const oldSocket = FakeWebSocket.instances[0]!;
      const original = useAuthStore.getState().user!;
      act(() => {
        receiveReady(oldSocket);
        oldSocket.receive(documentHint(4));
      });
      expect(owners).toEqual([original.id, original.id]);
      const replacement = change === "account"
        ? { ...original, id: "replacement-manager", email: "replacement@example.test" }
        : { ...original, agency_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa3" };

      act(() => useAuthStore.getState().setSession(replacement));
      expect(oldSocket.readyState).toBe(FakeWebSocket.CLOSED);
      expect(oldSocket.closes).toContainEqual(expect.objectContaining({ code: 1000 }));
      const currentSocket = FakeWebSocket.instances[1]!;
      expect(currentSocket.readyState).toBe(FakeWebSocket.OPEN);
      invalidations.mockClear();
      owners.length = 0;
      act(() => oldSocket.receive(documentHint(5)));
      expect(invalidations).not.toHaveBeenCalled();
      act(() => {
        receiveReady(currentSocket);
        currentSocket.receive(documentHint(1));
      });
      expect(owners).toEqual([replacement.id, replacement.id]);
      expect(invalidations).toHaveBeenCalledTimes(2);
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["document-distribution"] });
      expect(invalidations).toHaveBeenCalledWith({ queryKey: ["gc-app"] });
      view.unmount();
    },
  );

  it("ignores old frames after unmount and permits a fresh mounted socket", () => {
    const invalidations = vi.spyOn(queryClient, "invalidateQueries");
    const view = renderBridge(queryClient);
    const oldSocket = FakeWebSocket.instances[0]!;
    act(() => receiveReady(oldSocket));
    view.unmount();
    expect(oldSocket.readyState).toBe(FakeWebSocket.CLOSED);
    act(() => oldSocket.receive(documentHint(5)));
    expect(invalidations).not.toHaveBeenCalled();

    const nextView = renderBridge(queryClient);
    const currentSocket = FakeWebSocket.instances[1]!;
    expect(currentSocket.readyState).toBe(FakeWebSocket.OPEN);
    act(() => {
      receiveReady(currentSocket);
      currentSocket.receive(documentHint(1));
    });
    expect(invalidations).toHaveBeenCalledTimes(2);
    nextView.unmount();
  });

  it("ignores a closed socket's frames while its healthy replacement reconnects", () => {
    vi.useFakeTimers();
    const invalidations = vi.spyOn(queryClient, "invalidateQueries");
    const view = renderBridge(queryClient);
    const oldSocket = FakeWebSocket.instances[0]!;
    act(() => {
      receiveReady(oldSocket);
      oldSocket.close(1000, "Connection ended");
      oldSocket.receive(documentHint(5));
      vi.advanceTimersByTime(35_000);
    });
    expect(oldSocket.readyState).toBe(FakeWebSocket.CLOSED);
    expect(invalidations).not.toHaveBeenCalled();
    const currentSocket = FakeWebSocket.instances[1]!;
    expect(currentSocket.readyState).toBe(FakeWebSocket.OPEN);
    act(() => {
      receiveReady(currentSocket);
      currentSocket.receive(documentHint(1));
    });
    expect(invalidations).toHaveBeenCalledTimes(2);
    view.unmount();
  });
});

function receiveReady(socket: FakeWebSocket) {
  expect(socket.readyState).toBe(FakeWebSocket.OPEN);
  socket.receive({ type: "ready", heartbeat_seconds: 20, idle_timeout_seconds: 65 });
}

function documentHint(cursor: number) {
  return {
    type: "sync_hint",
    trip_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
    cursor,
    invalidation: "documents",
  };
}

function renderBridge(queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardRealtimeAttendanceBridge />
    </QueryClientProvider>,
  );
}

function user(role: UserRole): User {
  return {
    id: `${role}-id`,
    email: `${role}@example.test`,
    full_name: role,
    role,
    agency_id: role === "super_admin" ? null : "019d2a5b-6357-7600-8ed3-98c5ca70bfa1",
    is_active: true,
    last_login_at: null,
    created_at: "2026-08-25T00:00:00Z",
    updated_at: "2026-08-25T00:00:00Z",
  };
}
