"use client";

import { useEffect, useId, useState } from "react";
import { AlertTriangle, RotateCw, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui";
import {
  subscribeToQueueSafeSignOutReview,
} from "@/features/auth/services/queue-safe-sign-out-events";
import {
  getBrowserAttendanceQueueSafetySnapshot,
  syncPendingAttendanceScans,
} from "@/features/tour-operations/services/attendance-scan-queue";
import {
  hasUnsafeBrowserAttendanceQueue,
  type BrowserAttendanceQueueSafetySnapshot,
} from "@/features/tour-operations/services/attendance-queue-safety-contract";
import { useAuthStore } from "@/stores/auth.store";

type DestructiveStage = "blocked" | "discard-warning" | "discard-final";

export function QueueSafeSignOutGuard() {
  const titleId = useId();
  const descriptionId = useId();
  const clearSession = useAuthStore((state) => state.clearSession);
  const [snapshot, setSnapshot] = useState<BrowserAttendanceQueueSafetySnapshot | null>(null);
  const [stage, setStage] = useState<DestructiveStage>("blocked");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => subscribeToQueueSafeSignOutReview((next) => {
    setSnapshot(next);
    setStage("blocked");
    setError(null);
  }), []);

  if (!snapshot) return null;

  const close = () => {
    if (busy) return;
    setSnapshot(null);
    setStage("blocked");
    setError(null);
  };

  const syncThenSignOut = async () => {
    setBusy(true);
    setError(null);
    try {
      if (!navigator.onLine) {
        setError("This device is offline. Reconnect to sync, or use the explicit discard path.");
        return;
      }
      await syncPendingAttendanceScans();
      const refreshed = await getBrowserAttendanceQueueSafetySnapshot();
      if (hasUnsafeBrowserAttendanceQueue(refreshed)) {
        setSnapshot(refreshed);
        setError(
          refreshed.review > 0
            ? "Some scans still require operator review. Return to the scanner to review them, or explicitly discard them."
            : "Saved scans are waiting for their permitted retry time or could not synchronize yet.",
        );
        return;
      }
      await clearSession("logout");
    } catch {
      setError("Saved scans could not be synchronized. Nothing was deleted.");
    } finally {
      setBusy(false);
    }
  };

  const discardAndSignOut = async () => {
    setBusy(true);
    setError(null);
    try {
      await clearSession("logout", { queueDisposition: "discard" });
    } catch {
      setError("The saved queue could not be safely discarded. Sign-out remains blocked.");
      setStage("blocked");
    } finally {
      setBusy(false);
    }
  };

  const total = snapshot.pending + snapshot.retryable + snapshot.review;
  const heading = stage === "blocked"
    ? "Saved scans prevent sign-out"
    : stage === "discard-warning"
      ? "Discard saved scan data?"
      : "Final discard confirmation";
  const description = stage === "blocked"
    ? "Sign-out is blocked until this account's durable attendance work is synchronized, reviewed, or explicitly discarded."
    : stage === "discard-warning"
      ? "Discarding removes this account's unsynchronized and review records from this browser. Server-confirmed attendance is not changed."
      : "This cannot be undone. Any scan that has not reached the server may need to be scanned again.";

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" aria-hidden="true" />
            <div>
              <h2 id={titleId} className="text-lg font-semibold text-slate-950">{heading}</h2>
              <p id={descriptionId} className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={close}
            disabled={busy}
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:opacity-50"
            aria-label="Keep working"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-4 px-6 py-5">
          {snapshot.storageUnavailable ? (
            <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              Offline scan storage could not be inspected. Sign-out fails closed so saved work is not silently destroyed.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <QueueCount label="Pending" value={snapshot.pending} />
              <QueueCount label="Sending" value={snapshot.sending} />
              <QueueCount label="Retryable" value={snapshot.retryable} />
              <QueueCount label="Review" value={snapshot.review} />
            </div>
          )}
          {error ? (
            <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{error}</p>
          ) : null}
          {stage !== "blocked" ? (
            <p className="text-sm font-medium text-red-700">
              {total.toLocaleString()} local record{total === 1 ? "" : "s"} will be removed only for this account.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-slate-100 px-6 py-4 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={stage === "blocked" ? close : () => setStage("blocked")} disabled={busy}>
            {stage === "blocked" ? "Keep working" : "Back"}
          </Button>
          {stage === "blocked" ? (
            <>
              <Button type="button" variant="danger" onClick={() => setStage("discard-warning")} disabled={busy} leftIcon={<Trash2 className="h-4 w-4" aria-hidden="true" />}>
                Discard instead
              </Button>
              <Button type="button" onClick={() => void syncThenSignOut()} isLoading={busy} leftIcon={<RotateCw className="h-4 w-4" aria-hidden="true" />}>
                Sync then sign out
              </Button>
            </>
          ) : stage === "discard-warning" ? (
            <Button type="button" variant="danger" onClick={() => setStage("discard-final")} disabled={busy}>
              Continue to final confirmation
            </Button>
          ) : (
            <Button type="button" variant="danger" onClick={() => void discardAndSignOut()} isLoading={busy}>
              Permanently discard and sign out
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function QueueCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-center">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-slate-950">{value.toLocaleString()}</p>
    </div>
  );
}
