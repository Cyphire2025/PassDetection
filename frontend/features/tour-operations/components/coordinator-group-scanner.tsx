"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  CloudOff,
  Flashlight,
  FlashlightOff,
  RotateCw,
  ScanLine,
  SwitchCamera,
  Wifi,
  XCircle,
} from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { QUERY_KEYS } from "@/constants";
import {
  useCompleteMyAttendanceSession,
  useMyAttendanceSessions,
} from "@/features/operations/hooks/use-operations";
import { useContinuousQrScanner } from "../hooks/use-continuous-qr-scanner";
import {
  selectHasHydrated,
  selectIsAuthenticated,
  selectUser,
  useAuthStore,
} from "@/stores/auth.store";
import { ROUTES } from "@/constants/routes";
import { useAttendanceScanSync } from "../hooks/use-attendance-scan-sync";
import {
  mergeAttendanceSessionProgress,
  reconcileAttendanceSessionProgress,
  writeAttendanceSessionProgress,
} from "../services/attendance-session-progress";
import {
  offlineSnapshotKeys,
  readOfflineSnapshot,
  writeOfflineSnapshot,
} from "../services/offline-snapshot";
import type { AttendanceScanSyncUpdate } from "../services/attendance-scan-queue";
import type { AttendanceSession } from "@/features/operations/api/operations.api";
import { CoordinatorHydrationState } from "./coordinator-mobile-shell";
import {
  getAttendanceCompletionBlocker,
  getAuthoritativeAttendanceCount,
  getLatestSessionSyncUpdate,
  selectVisibleAttendanceSessions,
} from "../services/attendance-sync-policy";

const EMPTY_SESSIONS: AttendanceSession[] = [];

export function CoordinatorGroupScanner({ groupId, sessionId }: { groupId: string; sessionId: string | null }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const hasHydrated = useAuthStore(selectHasHydrated);
  const clearSession = useAuthStore((state) => state.clearSession);
  const isCoordinator = isAuthenticated && user?.role === "agency_coordinator";
  const {
    devices,
    isTorchOn,
    videoRef,
    status,
    errorMessage,
    latestScan,
    startScanner,
    stopScanner,
    selectedDeviceId,
    setSelectedDeviceId,
    supportsTorch,
    toggleTorch,
  } = useContinuousQrScanner();
  const userId = user?.id;
  const sessionsQuery = useMyAttendanceSessions(groupId, hasHydrated && isCoordinator);
  const sessions = sessionsQuery.data ?? EMPTY_SESSIONS;
  const cachedSessions = useMemo<AttendanceSession[]>(
    () => userId ? readOfflineSnapshot(offlineSnapshotKeys.mySessions(groupId), []) : [],
    [groupId, userId],
  );
  const visibleSessions = useMemo(
    () => selectVisibleAttendanceSessions(
      sessionsQuery.isSuccess,
      sessions,
      cachedSessions,
      mergeAttendanceSessionProgress,
    ),
    [cachedSessions, sessions, sessionsQuery.isSuccess],
  );
  const {
    acknowledgeRejectedScans,
    isOnline,
    isSyncing,
    lastSyncResult,
    pendingCount,
    rejectedCount,
    recordScan,
    syncError,
    syncNow,
  } = useAttendanceScanSync(sessionId);
  const completeMutation = useCompleteMyAttendanceSession();
  const processedScanIdRef = useRef<string | null>(null);
  const autoStartedRef = useRef(false);
  const scannedCountRef = useRef<number | null>(null);
  const scanPipelineRef = useRef<Promise<void>>(Promise.resolve());
  const mountedRef = useRef(true);
  const [lastResult, setLastResult] = useState<{ status: string; message: string } | null>(null);
  const [optimisticScannedCount, setOptimisticScannedCount] = useState<number | null>(null);
  const [isCompleting, setIsCompleting] = useState(false);
  const [isAcknowledgingRejected, setIsAcknowledgingRejected] = useState(false);
  const session = visibleSessions.find((item) => item.id === sessionId) ?? null;
  const isSessionCompleted = session?.status === "completed";
  const counts = useMemo(
    () => ({
      scanned: optimisticScannedCount ?? session?.scanned_count ?? 0,
      assigned: session?.assigned_count ?? 0,
    }),
    [optimisticScannedCount, session?.assigned_count, session?.scanned_count],
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!sessionsQuery.isSuccess) return;
    reconcileAttendanceSessionProgress(sessions);
    writeOfflineSnapshot(offlineSnapshotKeys.mySessions(groupId), sessions);
  }, [groupId, sessions, sessionsQuery.isSuccess]);

  useEffect(() => {
    if (optimisticScannedCount !== null) return;
    scannedCountRef.current = session?.scanned_count ?? 0;
  }, [optimisticScannedCount, session?.scanned_count]);

  const updateSessionProgress = useCallback((
    scannedCount: number,
    assignedCount: number,
    status?: string,
    authoritative = false,
  ) => {
    if (!sessionId) return;
    writeAttendanceSessionProgress(sessionId, {
      scanned_count: scannedCount,
      assigned_count: assignedCount,
      status,
    });
    queryClient.setQueryData(
      [...QUERY_KEYS.operations.tourGroupPassengers(groupId), "sessions"],
      (current: unknown) => Array.isArray(current)
        ? current.map((item) => item?.id === sessionId
          ? {
              ...item,
              scanned_count: authoritative
                ? scannedCount
                : Math.max(Number(item.scanned_count ?? 0), scannedCount),
              assigned_count: authoritative
                ? assignedCount
                : Math.max(Number(item.assigned_count ?? 0), assignedCount),
              status: status ?? item.status,
            }
          : item)
        : current,
    );
  }, [groupId, queryClient, sessionId]);

  const applySyncUpdates = useCallback((updates: AttendanceScanSyncUpdate[]) => {
    if (!sessionId) return null;
    const update = getLatestSessionSyncUpdate(updates, sessionId);
    if (!update) return null;
    const authoritativeCount = getAuthoritativeAttendanceCount(update);
    scannedCountRef.current = authoritativeCount;
    setOptimisticScannedCount(authoritativeCount);
    updateSessionProgress(authoritativeCount, update.assignedCount, undefined, true);
    return update;
  }, [sessionId, updateSessionProgress]);

  useEffect(() => {
    if (!lastSyncResult) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const update = applySyncUpdates(lastSyncResult.updates);
      if (update && !isCompleting) {
        setLastResult({ status: update.status, message: update.message });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [applySyncUpdates, isCompleting, lastSyncResult]);

  useEffect(() => {
    if (isCompleting || isSessionCompleted) return;
    if (!latestScan || !sessionId || processedScanIdRef.current === latestScan.id) return;
    processedScanIdRef.current = latestScan.id;
    const scan = {
        sessionId,
        qrPayload: latestScan.text,
        clientEventId: latestScan.id,
        scannedAt: latestScan.scannedAt,
        deviceId: getDeviceId(),
    };

    scanPipelineRef.current = scanPipelineRef.current
      .catch(() => undefined)
      .then(async () => {
        const result = await recordScan(scan);
        if (!mountedRef.current) return;
        if (result.mode === "queued") {
          setLastResult({
            status: result.duplicate ? "duplicate" : "queued",
            message: result.duplicate
              ? "Already saved offline for this activity."
              : "Saved offline as pending. The counted total updates only after server validation.",
          });
          return;
        }
        scannedCountRef.current = result.response.scanned_count;
        setOptimisticScannedCount(result.response.scanned_count);
        updateSessionProgress(result.response.scanned_count, result.response.assigned_count, undefined, true);
        setLastResult({ status: result.response.status, message: result.response.message });
      })
      .catch(() => {
        if (mountedRef.current) {
          setLastResult({ status: "invalid", message: "Scan could not be recorded." });
        }
      });
  }, [
    isCompleting,
    isSessionCompleted,
    latestScan,
    recordScan,
    session?.assigned_count,
    session?.scanned_count,
    sessionId,
    updateSessionProgress,
  ]);

  const isScanning = status === "scanning";

  useEffect(() => {
    if (
      !hasHydrated
      || !isCoordinator
      || !sessionId
      || !session
      || isSessionCompleted
      || isCompleting
      || autoStartedRef.current
    ) return;
    const timer = window.setTimeout(() => {
      autoStartedRef.current = true;
      void startScanner();
    }, 150);
    return () => window.clearTimeout(timer);
  }, [hasHydrated, isCompleting, isCoordinator, isSessionCompleted, session, sessionId, startScanner]);

  useEffect(() => {
    if (isSessionCompleted) stopScanner();
  }, [isSessionCompleted, stopScanner]);

  const completeSession = async () => {
    if (!sessionId || !session || isSessionCompleted || isCompleting) return;
    if (!isOnline) {
      setLastResult({
        status: "offline",
        message: "Reconnect before completing so every saved scan can sync first.",
      });
      return;
    }

    setIsCompleting(true);
    setLastResult(null);
    stopScanner();

    try {
      await scanPipelineRef.current;
      const syncResult = await syncNow();
      applySyncUpdates(syncResult.updates);
      const blocker = getAttendanceCompletionBlocker({
        isOnline: navigator.onLine,
        pending: syncResult.pending,
        failed: syncResult.failed,
        rejected: syncResult.rejected,
      });
      if (blocker) {
        const message = blocker === "rejected"
          ? "A saved scan was rejected. Review the authoritative count, rescan if needed, then confirm the review below."
          : "Some saved scans have not synchronized yet. Check the connection and try again.";
        setLastResult({ status: "sync_required", message });
        setIsCompleting(false);
        void startScanner();
        return;
      }

      await completeMutation.mutateAsync(sessionId);
      updateSessionProgress(scannedCountRef.current ?? counts.scanned, counts.assigned, "completed", true);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId), "sessions"] }),
        queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId), "mine"] }),
        queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroups, "mine"] }),
      ]);
      router.replace(`/coordinator/groups/${groupId}` as never);
    } catch {
      if (!mountedRef.current) return;
      setIsCompleting(false);
      setLastResult({ status: "error", message: "Activity could not be completed. Please try again." });
      void startScanner();
    }
  };

  const switchCamera = () => {
    if (devices.length < 2 || isSessionCompleted) return;
    const currentIndex = devices.findIndex((device) => device.deviceId === selectedDeviceId);
    const nextDevice = devices[(currentIndex + 1 + devices.length) % devices.length];
    stopScanner();
    setSelectedDeviceId(nextDevice.deviceId);
    void startScanner();
  };

  if (!hasHydrated) {
    return <CoordinatorHydrationState label="Loading activity scanner" />;
  }

  if (!isCoordinator) {
    return (
      <div data-coordinator-shell className="flex items-center justify-center bg-slate-100 p-[max(1.25rem,env(safe-area-inset-top))] text-slate-950">
        <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-5 text-center shadow-sm">
          <h1 className="text-lg font-bold">Coordinator login required</h1>
          <p className="mt-2 text-sm text-slate-500">
            Sign in with a coordinator account to use the activity scanner.
          </p>
          <Button
            type="button"
            className="mt-5 h-12 w-full"
            onClick={() => {
              if (isAuthenticated) {
                void clearSession();
                return;
              }
              const scannerPath = sessionId
                ? `/coordinator/groups/${groupId}/scanner?sessionId=${encodeURIComponent(sessionId)}`
                : `/coordinator/groups/${groupId}/scanner`;
              router.push(ROUTES.auth.coordinatorLogin(scannerPath) as never);
            }}
          >
            {isAuthenticated ? "Switch Account" : "Login"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      data-coordinator-fixed-viewport
      className="bg-slate-950 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] text-white"
    >
      <div className="mx-auto flex h-full w-full max-w-lg flex-col overflow-hidden">
        <header className="shrink-0 bg-slate-950 px-4 pb-2 pt-[max(0.65rem,env(safe-area-inset-top))]">
          <div className="mb-2 flex items-center justify-between gap-3">
            <Link href={`/coordinator/groups/${groupId}` as never} className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-white/15 bg-white/10 text-white">
              <ArrowLeft className="h-5 w-5" aria-hidden="true" />
              <span className="sr-only">Back</span>
            </Link>
            <Badge variant={isSessionCompleted ? "success" : isScanning ? "success" : "outline"} className="bg-white/10 text-white">
              {isSessionCompleted ? "completed" : status}
            </Badge>
          </div>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase text-slate-400">Activity Scanner</p>
              <h1 className="truncate text-lg font-bold text-white">{session?.name ?? "Attendance"}</h1>
            </div>
          </div>
        </header>

        <main
          data-coordinator-scanner-main
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <section
            data-coordinator-scanner-camera
            className="relative min-h-0 flex-[1_1_auto] overflow-hidden bg-black"
          >
            <video ref={videoRef} className="h-full w-full object-cover" muted playsInline autoPlay />
            {!isSessionCompleted && session && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 py-3">
                <div className="relative size-[min(82vw,20rem,42dvh)] rounded-3xl border-4 border-white/85 shadow-[0_0_0_999px_rgba(2,6,23,0.42)]">
                  <ScanLine className="absolute left-1/2 top-1/2 h-11 w-11 -translate-x-1/2 -translate-y-1/2 text-white/85" aria-hidden="true" />
                </div>
              </div>
            )}

            {(isSessionCompleted || (!session && !sessionsQuery.isLoading)) && (
              <div className="absolute inset-0 grid place-items-center bg-slate-950/90 p-5 text-center">
                <div>
                  <CheckCircle2 className={`mx-auto h-12 w-12 ${isSessionCompleted ? "text-emerald-400" : "text-slate-500"}`} aria-hidden="true" />
                  <p className="mt-3 text-lg font-bold">
                    {isSessionCompleted ? "Activity completed" : "Activity unavailable"}
                  </p>
                  <p className="mt-1 text-sm text-slate-300">
                    {isSessionCompleted
                      ? "Completed activities are read-only and cannot accept more scans."
                      : "Return to the group and open an active activity."}
                  </p>
                </div>
              </div>
            )}

            {lastResult && (
              <div aria-live="polite" className="absolute bottom-3 left-3 right-3 rounded-xl border border-white/20 bg-white/95 p-3 text-slate-950 shadow-lg">
                <div className="flex items-start gap-3">
                  {lastResult.status === "counted" ? (
                    <CheckCircle2 className="h-5 w-5 shrink-0 text-green-600" aria-hidden="true" />
                  ) : (
                    <XCircle className="h-5 w-5 shrink-0 text-amber-600" aria-hidden="true" />
                  )}
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{lastResult.status}</p>
                    <p className="text-xs text-slate-600">{lastResult.message}</p>
                  </div>
                </div>
              </div>
            )}
          </section>

          <section
            data-coordinator-scanner-controls
            className="max-h-[62dvh] shrink-0 space-y-2 overflow-y-auto overscroll-contain bg-white px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 text-slate-950"
          >
            {!sessionId && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                Missing activity session. Go back and start an activity first.
              </div>
            )}
            {errorMessage && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                <p>{errorMessage}</p>
                {!isSessionCompleted && session && (
                  <button
                    type="button"
                    className="mt-2 min-h-11 rounded-lg border border-red-200 bg-white px-3 font-semibold text-red-700"
                    onClick={() => void startScanner()}
                  >
                    Retry camera
                  </button>
                )}
              </div>
            )}
            {sessionsQuery.error && !session && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                <p>The activity could not be loaded.</p>
                <button
                  type="button"
                  className="mt-2 min-h-11 rounded-lg border border-amber-200 bg-white px-3 font-semibold"
                  onClick={() => void sessionsQuery.refetch()}
                >
                  Retry activity
                </button>
              </div>
            )}
            {syncError && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                {syncError}
              </div>
            )}
            {rejectedCount > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
                <p>
                  {rejectedCount} saved scan{rejectedCount === 1 ? " was" : "s were"} rejected by the server.
                  Review the authoritative count above and rescan any missing passenger.
                </p>
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-2 h-11 w-full"
                  isLoading={isAcknowledgingRejected}
                  onClick={async () => {
                    setIsAcknowledgingRejected(true);
                    try {
                      await acknowledgeRejectedScans();
                      setLastResult({
                        status: "reviewed",
                        message: "Rejected scans acknowledged. Complete when the authoritative count is correct.",
                      });
                    } catch {
                      setLastResult({
                        status: "error",
                        message: "The rejected-scan review could not be saved. Please try again.",
                      });
                    } finally {
                      setIsAcknowledgingRejected(false);
                    }
                  }}
                >
                  I reviewed the count
                </Button>
              </div>
            )}

            {!isSessionCompleted && session && (supportsTorch || devices.length > 1) && (
              <div className="grid grid-cols-2 gap-2">
                {supportsTorch && (
                  <Button
                    type="button"
                    variant="secondary"
                    className="h-11"
                    leftIcon={isTorchOn
                      ? <FlashlightOff className="h-4 w-4" aria-hidden="true" />
                      : <Flashlight className="h-4 w-4" aria-hidden="true" />}
                    onClick={() => {
                      void toggleTorch().catch(() => {
                        setLastResult({ status: "camera", message: "Torch could not be changed on this device." });
                      });
                    }}
                  >
                    {isTorchOn ? "Torch off" : "Torch on"}
                  </Button>
                )}
                {devices.length > 1 && (
                  <Button
                    type="button"
                    variant="secondary"
                    className={`h-11 ${supportsTorch ? "" : "col-span-2"}`}
                    leftIcon={<SwitchCamera className="h-4 w-4" aria-hidden="true" />}
                    onClick={switchCamera}
                  >
                    Switch camera
                  </Button>
                )}
              </div>
            )}

            <div className="grid grid-cols-3 gap-2">
              <Metric label="Counted" value={counts.scanned} />
              <Metric label="Total" value={counts.assigned} />
              <Metric label="Pending" value={pendingCount} />
            </div>

            <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
              <span className="inline-flex items-center gap-2">
                {isOnline ? <Wifi className="h-4 w-4 text-green-600" /> : <CloudOff className="h-4 w-4 text-amber-600" />}
                {isOnline ? "Online" : "Offline mode"}
              </span>
              <button
                type="button"
                className="inline-flex min-h-11 items-center gap-1 rounded-lg px-2 font-medium text-blue-700 disabled:text-slate-400"
                disabled={!isOnline || isSyncing || pendingCount === 0}
                onClick={() => void syncNow()}
              >
                <RotateCw className={`h-4 w-4 ${isSyncing ? "animate-spin" : ""}`} aria-hidden="true" />
                Sync
              </button>
            </div>

            {session?.status === "completed" ? (
              <Button
                type="button"
                onClick={async () => {
                  stopScanner();
                  await queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId), "sessions"] });
                  router.replace(`/coordinator/groups/${groupId}` as never);
                }}
                className="h-12 w-full text-base"
              >
                Done
              </Button>
            ) : (
              <Button
                type="button"
                disabled={!sessionId || !session || !isOnline || rejectedCount > 0 || isCompleting}
                isLoading={isCompleting || completeMutation.isPending}
                onClick={() => void completeSession()}
                className="h-12 w-full text-base"
              >
                {isOnline ? "Complete" : "Reconnect to complete"}
              </Button>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <p className="text-[11px] font-semibold uppercase text-slate-500">{label}</p>
      <p className="text-xl font-bold text-slate-950">{value}</p>
    </div>
  );
}

function getDeviceId() {
  const key = "passdetection-coordinator-device-id";
  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const next = typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    window.localStorage.setItem(key, next);
    return next;
  } catch {
    return `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}
