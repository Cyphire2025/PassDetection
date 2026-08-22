"use client";

import { useEffect, useMemo, useState } from "react";

import type { AttendanceSession } from "@/features/operations/api/operations.api";

import { publishBrowserAttendanceCloseoutCheckpoint } from "../services/attendance-closeout-checkpoint";

const CHECKPOINT_REFRESH_MS = 30_000;

export function useAttendanceCloseoutReporting({
  enabled,
  groupId,
  sessions,
}: {
  enabled: boolean;
  groupId: string;
  sessions: AttendanceSession[];
}) {
  const activeSessionIds = useMemo(
    () => sessions
      .filter((session) => session.status === "active")
      .map((session) => session.id)
      .sort(),
    [sessions],
  );
  const activityKey = activeSessionIds.join(":");
  const [lastReportedAt, setLastReportedAt] = useState<string | null>(null);
  const [reportingError, setReportingError] = useState(false);

  useEffect(() => {
    if (!enabled || !activityKey) return;
    let mounted = true;
    let inFlight = false;
    const reportSessionIds = activityKey.split(":");

    const publish = async () => {
      if (inFlight || !navigator.onLine || document.visibilityState !== "visible") return;
      inFlight = true;
      try {
        const responses = await Promise.all(
          reportSessionIds.map((sessionId) =>
            publishBrowserAttendanceCloseoutCheckpoint(groupId, sessionId)),
        );
        if (!mounted) return;
        setLastReportedAt(responses.at(-1)?.reported_at ?? new Date().toISOString());
        setReportingError(false);
      } catch {
        if (mounted) setReportingError(true);
      } finally {
        inFlight = false;
      }
    };

    const initial = window.setTimeout(() => void publish(), 0);
    const interval = window.setInterval(() => void publish(), CHECKPOINT_REFRESH_MS);
    const handleOnline = () => void publish();
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") void publish();
    };
    window.addEventListener("online", handleOnline);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      mounted = false;
      window.clearTimeout(initial);
      window.clearInterval(interval);
      window.removeEventListener("online", handleOnline);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [activityKey, enabled, groupId]);

  return { lastReportedAt, reportingError };
}
