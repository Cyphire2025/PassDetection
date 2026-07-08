"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, CloudOff, RotateCw, ScanLine, Wifi, XCircle } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { QUERY_KEYS } from "@/constants";
import {
  useCompleteMyAttendanceSession,
  useMyAttendanceSessions,
} from "@/features/operations/hooks/use-operations";
import { useContinuousQrScanner } from "../hooks/use-continuous-qr-scanner";
import { selectIsAuthenticated, selectUser, useAuthStore } from "@/stores/auth.store";
import { ROUTES } from "@/constants/routes";
import { useAttendanceScanSync } from "../hooks/use-attendance-scan-sync";
import { writeAttendanceSessionProgress } from "../services/attendance-session-progress";

export function CoordinatorGroupScanner({ groupId, sessionId }: { groupId: string; sessionId: string | null }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore(selectUser);
  const isAuthenticated = useAuthStore(selectIsAuthenticated);
  const clearSession = useAuthStore((state) => state.clearSession);
  const isCoordinator = isAuthenticated && user?.role === "agency_coordinator";
  const {
    videoRef,
    status,
    errorMessage,
    latestScan,
    startScanner,
    stopScanner,
  } = useContinuousQrScanner();
  const { data: sessions = [] } = useMyAttendanceSessions(groupId, isCoordinator);
  const { isOnline, isSyncing, pendingCount, recordScan, syncNow } = useAttendanceScanSync();
  const completeMutation = useCompleteMyAttendanceSession();
  const processedScanIds = useRef(new Set<string>());
  const autoStartedRef = useRef(false);
  const [lastResult, setLastResult] = useState<{ status: string; message: string } | null>(null);
  const [optimisticScannedCount, setOptimisticScannedCount] = useState<number | null>(null);
  const [isCompleting, setIsCompleting] = useState(false);
  const session = sessions.find((item) => item.id === sessionId) ?? null;
  const counts = useMemo(
    () => ({
      scanned: optimisticScannedCount ?? session?.scanned_count ?? 0,
      assigned: session?.assigned_count ?? 0,
    }),
    [optimisticScannedCount, session?.assigned_count, session?.scanned_count],
  );

  const updateSessionProgress = useCallback((scannedCount: number, assignedCount: number, status?: string) => {
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
              scanned_count: Math.max(Number(item.scanned_count ?? 0), scannedCount),
              assigned_count: Math.max(Number(item.assigned_count ?? 0), assignedCount),
              status: status ?? item.status,
            }
          : item)
        : current,
    );
  }, [groupId, queryClient, sessionId]);

  useEffect(() => {
    if (isCompleting) return;
    if (!latestScan || !sessionId || processedScanIds.current.has(latestScan.id)) return;
    processedScanIds.current.add(latestScan.id);
    void recordScan({
        sessionId,
        qrPayload: latestScan.text,
        clientEventId: latestScan.id,
        scannedAt: latestScan.scannedAt,
        deviceId: getDeviceId(),
      })
      .then((result) => {
        if (result.mode === "queued") {
          if (!result.duplicate) {
            const nextCount = (optimisticScannedCount ?? session?.scanned_count ?? 0) + 1;
            setOptimisticScannedCount(nextCount);
            updateSessionProgress(nextCount, session?.assigned_count ?? 0);
          }
          setLastResult({
            status: result.duplicate ? "duplicate" : "queued",
            message: result.duplicate ? "Already saved offline for this activity." : "Saved offline. It will sync automatically.",
          });
          return;
        }
        setOptimisticScannedCount(result.response.scanned_count);
        updateSessionProgress(result.response.scanned_count, result.response.assigned_count);
        setLastResult({ status: result.response.status, message: result.response.message });
      })
      .catch(() => setLastResult({ status: "invalid", message: "Scan could not be recorded." }));
  }, [isCompleting, latestScan, optimisticScannedCount, recordScan, session?.assigned_count, session?.scanned_count, sessionId, updateSessionProgress]);

  const isScanning = status === "scanning";

  useEffect(() => {
    if (!isCoordinator || !sessionId || isCompleting || autoStartedRef.current || session?.status === "completed") return;
    autoStartedRef.current = true;
    const timer = window.setTimeout(() => {
      void startScanner();
    }, 150);
    return () => window.clearTimeout(timer);
  }, [isCompleting, isCoordinator, session?.status, sessionId, startScanner]);

  const completeSession = () => {
    if (!sessionId || isCompleting) return;

    setIsCompleting(true);
    setLastResult(null);
    stopScanner();

    completeMutation.mutate(sessionId, {
      onSuccess: async () => {
        updateSessionProgress(counts.scanned, counts.assigned, "completed");
        await syncNow();
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId), "sessions"] }),
          queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId), "mine"] }),
          queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroups, "mine"] }),
        ]);
        router.replace(`/coordinator/groups/${groupId}` as never);
      },
      onError: () => {
        setIsCompleting(false);
        setLastResult({ status: "error", message: "Activity could not be completed. Please try again." });
        void startScanner();
      },
    });
  };

  if (!isCoordinator) {
    return (
      <div className="flex min-h-[100svh] items-center justify-center bg-slate-100 p-5 text-slate-950">
        <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-5 text-center shadow-sm">
          <h1 className="text-lg font-bold">Coordinator login required</h1>
          <p className="mt-2 text-sm text-slate-500">
            Sign in with a coordinator account to use the activity scanner.
          </p>
          <Button
            type="button"
            className="mt-5 h-12 w-full"
            onClick={() => {
              clearSession();
              router.push(ROUTES.auth.login as never);
            }}
          >
            Switch Account
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[100svh] overflow-hidden bg-slate-950 text-white">
      <div className="mx-auto flex h-[100svh] w-full max-w-md flex-col overflow-hidden">
        <header className="shrink-0 bg-slate-950 px-4 pb-2 pt-[max(0.65rem,env(safe-area-inset-top))]">
          <div className="mb-2 flex items-center justify-between gap-3">
            <Link href="/coordinator" className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-white/15 bg-white/10 text-white">
              <ArrowLeft className="h-5 w-5" aria-hidden="true" />
              <span className="sr-only">Back</span>
            </Link>
            <Badge variant={isScanning ? "success" : "outline"} className="bg-white/10 text-white">
              {status}
            </Badge>
          </div>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase text-slate-400">Activity Scanner</p>
              <h1 className="truncate text-lg font-bold text-white">{session?.name ?? "Attendance"}</h1>
            </div>
          </div>
        </header>

        <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <section className="relative min-h-0 flex-[1_1_auto] overflow-hidden bg-black">
            <video ref={videoRef} className="h-full w-full object-cover" muted playsInline autoPlay />
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 py-3">
              <div className="relative aspect-square w-[82vw] max-w-80 rounded-3xl border-4 border-white/85 shadow-[0_0_0_999px_rgba(2,6,23,0.42)]">
                <ScanLine className="absolute left-1/2 top-1/2 h-11 w-11 -translate-x-1/2 -translate-y-1/2 text-white/85" aria-hidden="true" />
              </div>
            </div>

            {lastResult && (
              <div className="absolute bottom-3 left-3 right-3 rounded-xl border border-white/20 bg-white/95 p-3 text-slate-950 shadow-lg">
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

          <section className="shrink-0 space-y-2 bg-white px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 text-slate-950">
            {!sessionId && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                Missing activity session. Go back and start an activity first.
              </div>
            )}
            {errorMessage && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700">{errorMessage}</div>
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
                className="inline-flex items-center gap-1 font-medium text-blue-700 disabled:text-slate-400"
                disabled={!isOnline || isSyncing || pendingCount === 0}
                onClick={() => void syncNow()}
              >
                <RotateCw className={`h-4 w-4 ${isSyncing ? "animate-spin" : ""}`} aria-hidden="true" />
                Sync
              </button>
            </div>

            <Button
              type="button"
              disabled={!sessionId || isCompleting || session?.status === "completed"}
              isLoading={isCompleting || completeMutation.isPending}
              onClick={completeSession}
              className="h-12 w-full text-base"
            >
              Complete
            </Button>
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
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const next = crypto.randomUUID();
  window.localStorage.setItem(key, next);
  return next;
}
