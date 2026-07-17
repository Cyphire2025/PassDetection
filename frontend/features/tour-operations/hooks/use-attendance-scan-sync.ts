"use client";

import { useCallback, useEffect, useState } from "react";
import {
  countPendingAttendanceScans,
  syncPendingAttendanceScans,
  tryRecordAttendanceScan,
  type AttendanceScanInput,
} from "../services/attendance-scan-queue";

type ScanInput = AttendanceScanInput;

export function useAttendanceScanSync() {
  const [pendingCount, setPendingCount] = useState(0);
  const [isOnline, setIsOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  const [isSyncing, setIsSyncing] = useState(false);

  const refreshPendingCount = useCallback(async () => {
    setPendingCount(await countPendingAttendanceScans());
  }, []);

  const syncNow = useCallback(async () => {
    if (!navigator.onLine) return { synced: 0, failed: 0 };
    setIsSyncing(true);
    try {
      const result = await syncPendingAttendanceScans();
      await refreshPendingCount();
      return result;
    } finally {
      setIsSyncing(false);
    }
  }, [refreshPendingCount]);

  const recordScan = useCallback(
    async (scan: ScanInput) => {
      const result = await tryRecordAttendanceScan(scan);
      await refreshPendingCount();
      return result;
    },
    [refreshPendingCount],
  );

  useEffect(() => {
    window.setTimeout(() => {
      void refreshPendingCount();
    }, 0);

    const handleOnline = () => {
      setIsOnline(true);
      void syncNow();
    };
    const handleOffline = () => setIsOnline(false);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    const timer = window.setInterval(() => {
      setIsOnline(navigator.onLine);
      if (navigator.onLine) void syncNow();
    }, 15_000);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.clearInterval(timer);
    };
  }, [refreshPendingCount, syncNow]);

  return {
    isOnline,
    isSyncing,
    pendingCount,
    recordScan,
    syncNow,
  };
}
