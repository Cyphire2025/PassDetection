"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useAuthStore } from "@/stores/auth.store";

import {
  dashboardRealtimeReconnectDelayMs,
  dashboardRealtimeQueryPrefixes,
  dashboardRealtimeWebSocketUrl,
  parseDashboardRealtimeServerFrame,
  shouldInvalidateAttendanceFromRealtime,
} from "../services/dashboard-realtime";
import { publishAttendanceInvalidationHint } from "../services/attendance-invalidation";

const REALTIME_ROLES = new Set([
  "agency_admin",
  "agency_manager",
  "agency_staff",
  "agency_coordinator",
]);
const STABLE_CONNECTION_MS = 30_000;

/**
 * Converts the backend's lossy, PII-free cursor hints into the existing
 * attendance invalidation bus. Canonical ETag/revision reads and adaptive
 * polling remain responsible for correctness when a socket or hint is lost.
 */
export function DashboardRealtimeAttendanceBridge() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const hasHydrated = useAuthStore((state) => state.hasHydrated);
  const sessionVersion = useAuthStore((state) => state.sessionVersion);

  useEffect(() => {
    if (
      !hasHydrated
      || !isAuthenticated
      || !user?.is_active
      || !user.agency_id
      || !REALTIME_ROLES.has(user.role)
      || typeof WebSocket === "undefined"
    ) return;

    let disposed = false;
    let reconnectAttempt = 0;
    let reconnectTimer: number | null = null;
    let socket: WebSocket | null = null;
    const latestCursorByGroup = new Map<string, number>();

    const clearReconnectTimer = () => {
      if (reconnectTimer === null) return;
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    };

    const shouldConnect = () => (
      !disposed
      && document.visibilityState !== "hidden"
      && navigator.onLine !== false
    );

    const scheduleReconnect = (closeCode: number) => {
      clearReconnectTimer();
      if (!shouldConnect()) return;
      const delay = dashboardRealtimeReconnectDelayMs(reconnectAttempt, closeCode);
      reconnectAttempt = Math.min(reconnectAttempt + 1, 10);
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (!shouldConnect() || socket) return;
      const url = dashboardRealtimeWebSocketUrl(window.location);
      if (!url) return;

      const activeSocket = new WebSocket(url);
      let protocolReadyAt: number | null = null;
      socket = activeSocket;

      activeSocket.addEventListener("message", (event) => {
        const frame = parseDashboardRealtimeServerFrame(event.data);
        if (!frame) {
          activeSocket.close(1008, "Protocol mismatch");
          return;
        }
        if (frame.type === "ready") {
          if (protocolReadyAt !== null) {
            activeSocket.close(1008, "Duplicate ready frame");
            return;
          }
          protocolReadyAt = Date.now();
          return;
        }
        if (protocolReadyAt === null) {
          activeSocket.close(1008, "Ready frame required");
          return;
        }
        if (frame.type === "heartbeat") {
          if (activeSocket.readyState === WebSocket.OPEN) {
            activeSocket.send('{"type":"heartbeat_ack"}');
          }
          return;
        }
        const previousCursor = latestCursorByGroup.get(frame.trip_id) ?? 0;
        if (frame.cursor <= previousCursor) return;
        latestCursorByGroup.set(frame.trip_id, frame.cursor);
        if (shouldInvalidateAttendanceFromRealtime(frame)) {
          publishAttendanceInvalidationHint({
            groupId: frame.trip_id,
            source: "server-push",
          });
        }
        for (const queryKey of dashboardRealtimeQueryPrefixes(frame)) {
          void queryClient.invalidateQueries({ queryKey });
        }
      });

      activeSocket.addEventListener("error", () => {
        try {
          activeSocket.close();
        } catch {
          // The close event, or the adaptive polling fallback, owns recovery.
        }
      });

      activeSocket.addEventListener("close", (event) => {
        if (socket !== activeSocket) return;
        socket = null;
        if (disposed) return;
        if (protocolReadyAt !== null && Date.now() - protocolReadyAt >= STABLE_CONNECTION_MS) {
          reconnectAttempt = 0;
        }
        scheduleReconnect(event.code);
      });
    };

    const pause = () => {
      clearReconnectTimer();
      const activeSocket = socket;
      socket = null;
      if (activeSocket && activeSocket.readyState < WebSocket.CLOSING) {
        activeSocket.close(1000, "Dashboard paused");
      }
    };

    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        pause();
        return;
      }
      reconnectAttempt = 0;
      connect();
    };
    const handleOnline = () => {
      reconnectAttempt = 0;
      connect();
    };
    const handleOffline = () => pause();

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    connect();

    return () => {
      disposed = true;
      clearReconnectTimer();
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      const activeSocket = socket;
      socket = null;
      if (activeSocket && activeSocket.readyState < WebSocket.CLOSING) {
        activeSocket.close(1000, "Dashboard session changed");
      }
    };
  }, [hasHydrated, isAuthenticated, queryClient, sessionVersion, user]);

  return null;
}
