"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  acknowledgeRejectedAttendanceScans,
  countPendingAttendanceScans,
  countRejectedAttendanceScans,
  syncPendingAttendanceScans,
  tryRecordAttendanceScan,
  type AttendanceScanSyncResult,
  type AttendanceScanInput,
} from "../services/attendance-scan-queue";
import { useNetworkStatus } from "./use-network-status";

type ScanInput = AttendanceScanInput;

export function useAttendanceScanSync(
  groupId: string,
  sessionId: string | null,
) {
  const [pendingCount, setPendingCount] = useState(0);
  const [rejectedCount, setRejectedCount] = useState(0);
  const isOnline = useNetworkStatus();
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [lastSyncResult, setLastSyncResult] = useState<(AttendanceScanSyncResult & { pending: number; rejected: number }) | null>(null);
  const pendingCountRef = useRef(0);
  const rejectedCountRef = useRef(0);
  const syncPromiseRef = useRef<Promise<AttendanceScanSyncResult & { pending: number; rejected: number }> | null>(null);

  const refreshQueueCounts = useCallback(async () => {
    try {
      const [pending, rejected] = await Promise.all([
        countPendingAttendanceScans(groupId),
        countRejectedAttendanceScans(groupId, sessionId),
      ]);
      pendingCountRef.current = pending;
      rejectedCountRef.current = rejected;
      setPendingCount(pending);
      setRejectedCount(rejected);
      return { pending, rejected };
    } catch {
      setSyncError("Offline scan storage is unavailable on this device.");
      return {
        pending: pendingCountRef.current,
        rejected: rejectedCountRef.current,
      };
    }
  }, [groupId, sessionId]);

  const syncNow = useCallback(() => {
    if (syncPromiseRef.current) return syncPromiseRef.current;
    if (!navigator.onLine) {
      return Promise.resolve({
        synced: 0,
        failed: 0,
        discarded: 0,
        updates: [],
        pending: pendingCountRef.current,
        rejected: rejectedCountRef.current,
      });
    }

    setIsSyncing(true);
    setSyncError(null);
    const request = syncPendingAttendanceScans()
      .then(async (result) => {
        const queueCounts = await refreshQueueCounts();
        const completedResult = {
          ...result,
          ...queueCounts,
        };
        setLastSyncResult(completedResult);
        return completedResult;
      })
      .catch((error) => {
        setSyncError("Saved scans could not be synchronized yet.");
        throw error;
      })
      .finally(() => {
        syncPromiseRef.current = null;
        setIsSyncing(false);
      });
    syncPromiseRef.current = request;
    return request;
  }, [refreshQueueCounts]);

  const recordScan = useCallback(
    async (scan: ScanInput) => {
      const result = await tryRecordAttendanceScan(scan);
      await refreshQueueCounts();
      return result;
    },
    [refreshQueueCounts],
  );

  const acknowledgeRejectedScans = useCallback(async () => {
    const acknowledged = await acknowledgeRejectedAttendanceScans(
      groupId,
      sessionId,
    );
    await refreshQueueCounts();
    return acknowledged;
  }, [groupId, refreshQueueCounts, sessionId]);

  useEffect(() => {
    const initialRefresh = window.setTimeout(() => {
      void refreshQueueCounts().then(({ pending }) => {
        if (navigator.onLine && pending > 0) void syncNow();
      });
    }, 0);

    const handleOnline = () => {
      void syncNow();
    };

    window.addEventListener("online", handleOnline);
    const timer = window.setInterval(() => {
      if (navigator.onLine && pendingCountRef.current > 0) void syncNow();
    }, 15_000);

    return () => {
      window.clearTimeout(initialRefresh);
      window.removeEventListener("online", handleOnline);
      window.clearInterval(timer);
    };
  }, [refreshQueueCounts, syncNow]);

  return {
    isOnline,
    isSyncing,
    syncError,
    lastSyncResult,
    pendingCount,
    rejectedCount,
    acknowledgeRejectedScans,
    recordScan,
    syncNow,
  };
}
