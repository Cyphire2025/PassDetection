"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  acknowledgeRejectedAttendanceScans,
  countPendingAttendanceDiscardAudits,
  countPendingAttendanceScans,
  countRejectedAttendanceScans,
  listRejectedAttendanceScans,
  subscribeAttendanceQueueScheduleChanges,
  syncAttendanceDiscardTombstones,
  syncPendingAttendanceScans,
  tryRecordAttendanceScan,
  type AttendanceScanSyncResult,
  type AttendanceScanInput,
  type RejectedAttendanceScan,
} from "../services/attendance-scan-queue";
import { useNetworkStatus } from "./use-network-status";
import { publishAttendanceInvalidationHint } from "@/features/operations/services/attendance-invalidation";

type ScanInput = AttendanceScanInput;

export function useAttendanceScanSync(
  groupId: string,
  sessionId: string | null,
) {
  const [pendingCount, setPendingCount] = useState(0);
  const [rejectedCount, setRejectedCount] = useState(0);
  const [rejectedIssues, setRejectedIssues] = useState<RejectedAttendanceScan[]>([]);
  const [discardAuditPending, setDiscardAuditPending] = useState(0);
  const isOnline = useNetworkStatus();
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [lastSyncResult, setLastSyncResult] = useState<(AttendanceScanSyncResult & { pending: number; rejected: number }) | null>(null);
  const pendingCountRef = useRef(0);
  const rejectedCountRef = useRef(0);
  const discardAuditPendingRef = useRef(0);
  const syncPromiseRef = useRef<Promise<AttendanceScanSyncResult & { pending: number; rejected: number }> | null>(null);

  const refreshQueueCounts = useCallback(async () => {
    try {
      const [pending, rejected, issues, discardPending] = await Promise.all([
        countPendingAttendanceScans(groupId),
        countRejectedAttendanceScans(groupId, sessionId),
        listRejectedAttendanceScans(groupId, sessionId),
        countPendingAttendanceDiscardAudits(groupId, sessionId ?? undefined),
      ]);
      pendingCountRef.current = pending;
      rejectedCountRef.current = rejected;
      discardAuditPendingRef.current = discardPending;
      setPendingCount(pending);
      setRejectedCount(rejected);
      setRejectedIssues(issues);
      setDiscardAuditPending(discardPending);
      return { pending, rejected, discardPending };
    } catch {
      setSyncError("Offline scan storage is unavailable on this device.");
      return {
        pending: pendingCountRef.current,
        rejected: rejectedCountRef.current,
        discardPending: discardAuditPendingRef.current,
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
        let discardSyncFailed = false;
        try {
          await syncAttendanceDiscardTombstones();
        } catch {
          discardSyncFailed = true;
        }
        const queueCounts = await refreshQueueCounts();
        const completedResult = {
          ...result,
          ...queueCounts,
        };
        if (
          result.updates.some((update) => sessionId === null || update.sessionId === sessionId)
        ) {
          publishAttendanceInvalidationHint({
            groupId,
            ...(sessionId === null ? {} : { sessionId }),
            source: "queue-sync",
          });
        }
        setLastSyncResult(completedResult);
        if (discardSyncFailed) {
          setSyncError("Scan discard audit evidence is saved and will retry automatically.");
        }
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
  }, [groupId, refreshQueueCounts, sessionId]);

  const recordScan = useCallback(
    async (scan: ScanInput) => {
      const result = await tryRecordAttendanceScan(scan);
      if (result.mode === "online") {
        publishAttendanceInvalidationHint({
          groupId: scan.groupId,
          sessionId: scan.sessionId,
          source: "local-mutation",
        });
      }
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
      void refreshQueueCounts().then(({ pending, discardPending }) => {
        if (navigator.onLine && (pending > 0 || discardPending > 0)) void syncNow();
      });
    }, 0);

    const handleOnline = () => {
      void syncNow();
    };

    window.addEventListener("online", handleOnline);
    const unsubscribeSchedule = subscribeAttendanceQueueScheduleChanges(() => {
      void refreshQueueCounts();
    });

    return () => {
      window.clearTimeout(initialRefresh);
      window.removeEventListener("online", handleOnline);
      unsubscribeSchedule();
    };
  }, [refreshQueueCounts, syncNow]);

  return {
    isOnline,
    isSyncing,
    syncError,
    lastSyncResult,
    pendingCount,
    rejectedCount,
    rejectedIssues,
    discardAuditPending,
    acknowledgeRejectedScans,
    recordScan,
    syncNow,
  };
}
