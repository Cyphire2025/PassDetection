"use client";

import { useCallback, useEffect, useRef } from "react";
import { useAuthStore } from "@/stores/auth.store";
import {
  countPendingAttendanceScans,
  syncPendingAttendanceScans,
} from "../services/attendance-scan-queue";

const RETRY_INTERVAL_MS = 15_000;

/**
 * Replays this coordinator's durable scan queue while any coordinator route is
 * mounted. Scanner-specific pending/rejected UI remains in the scanner hook.
 */
export function CoordinatorOfflineScanDrain() {
  const hasHydrated = useAuthStore((state) => state.hasHydrated);
  const coordinatorUserId = useAuthStore((state) => (
    state.user?.role === "agency_coordinator" ? state.user.id : null
  ));
  const drainPromiseRef = useRef<Promise<void> | null>(null);

  const drain = useCallback(() => {
    if (
      !hasHydrated
      || !coordinatorUserId
      || !navigator.onLine
    ) {
      return Promise.resolve();
    }
    if (drainPromiseRef.current) return drainPromiseRef.current;

    const request = countPendingAttendanceScans()
      .then((pending) => (
        pending > 0 ? syncPendingAttendanceScans() : undefined
      ))
      .then(() => undefined)
      .catch(() => {
        // Connectivity and server failures remain queued for the next retry.
      })
      .finally(() => {
        if (drainPromiseRef.current === request) drainPromiseRef.current = null;
      });
    drainPromiseRef.current = request;
    return request;
  }, [coordinatorUserId, hasHydrated]);

  useEffect(() => {
    if (!hasHydrated || !coordinatorUserId) return;

    const handleReconnect = () => {
      void drain();
    };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") void drain();
    };
    const initialDrain = window.setTimeout(handleReconnect, 0);
    const retryTimer = window.setInterval(handleReconnect, RETRY_INTERVAL_MS);

    window.addEventListener("online", handleReconnect);
    window.addEventListener("pageshow", handleReconnect);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      window.clearTimeout(initialDrain);
      window.clearInterval(retryTimer);
      window.removeEventListener("online", handleReconnect);
      window.removeEventListener("pageshow", handleReconnect);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [coordinatorUserId, drain, hasHydrated]);

  return null;
}
