"use client";

import { useCallback, useEffect, useRef } from "react";
import { useAuthStore } from "@/stores/auth.store";
import {
  getNextPendingAttendanceAttemptAt,
  subscribeAttendanceQueueScheduleChanges,
  syncAttendanceDiscardTombstones,
  syncPendingAttendanceScans,
} from "../services/attendance-scan-queue";

const MAX_TIMER_DELAY_MS = 2_147_000_000;

/**
 * Replays this coordinator's durable queue from one exact persisted wakeup.
 * Queue mutations and cross-tab updates reschedule the earliest eligible row;
 * there is intentionally no blind polling interval.
 */
export function CoordinatorOfflineScanDrain() {
  const hasHydrated = useAuthStore((state) => state.hasHydrated);
  const coordinatorUserId = useAuthStore((state) => (
    state.user?.role === "agency_coordinator" ? state.user.id : null
  ));
  const drainPromiseRef = useRef<Promise<void> | null>(null);
  const wakeupTimerRef = useRef<number | null>(null);
  const drainRef = useRef<() => void>(() => undefined);

  const clearWakeup = useCallback(() => {
    if (wakeupTimerRef.current !== null) {
      window.clearTimeout(wakeupTimerRef.current);
      wakeupTimerRef.current = null;
    }
  }, []);

  const scheduleWakeup = useCallback(async (hint?: string | null) => {
    clearWakeup();
    if (!hasHydrated || !coordinatorUserId || !navigator.onLine) return;
    const nextAttemptAt = hint === undefined
      ? await getNextPendingAttendanceAttemptAt()
      : hint;
    if (!nextAttemptAt) return;
    const attemptAtMs = Date.parse(nextAttemptAt);
    const delayMs = Number.isFinite(attemptAtMs)
      ? Math.max(0, attemptAtMs - Date.now())
      : 0;
    wakeupTimerRef.current = window.setTimeout(
      () => drainRef.current(),
      Math.min(MAX_TIMER_DELAY_MS, delayMs),
    );
  }, [clearWakeup, coordinatorUserId, hasHydrated]);

  const drain = useCallback(() => {
    if (!hasHydrated || !coordinatorUserId || !navigator.onLine) {
      return Promise.resolve();
    }
    if (drainPromiseRef.current) return drainPromiseRef.current;

    // Scan delivery and discard-evidence delivery are independent. A backend
    // or schema error in one lane must not starve the other durable queue.
    const request = Promise.allSettled([
      syncPendingAttendanceScans(),
      syncAttendanceDiscardTombstones(),
    ])
      .then(() => scheduleWakeup())
      .finally(() => {
        if (drainPromiseRef.current === request) drainPromiseRef.current = null;
      });
    drainPromiseRef.current = request;
    return request;
  }, [coordinatorUserId, hasHydrated, scheduleWakeup]);

  useEffect(() => {
    drainRef.current = () => {
      void drain();
    };
  }, [drain]);

  useEffect(() => {
    if (!hasHydrated || !coordinatorUserId) return;
    const handleReconnect = () => void drain();
    const handleVisibility = () => {
      if (document.visibilityState === "visible") void drain();
    };
    const handleScheduleChange = () => void scheduleWakeup();
    const initialDrain = window.setTimeout(handleReconnect, 0);
    const unsubscribeSchedule = subscribeAttendanceQueueScheduleChanges(
      handleScheduleChange,
    );

    window.addEventListener("online", handleReconnect);
    window.addEventListener("offline", clearWakeup);
    window.addEventListener("pageshow", handleReconnect);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      window.clearTimeout(initialDrain);
      clearWakeup();
      unsubscribeSchedule();
      window.removeEventListener("online", handleReconnect);
      window.removeEventListener("offline", clearWakeup);
      window.removeEventListener("pageshow", handleReconnect);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [clearWakeup, coordinatorUserId, drain, hasHydrated, scheduleWakeup]);

  return null;
}
