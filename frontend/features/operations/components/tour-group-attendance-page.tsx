"use client";

import Link from "next/link";
import { useDeferredValue, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  QrCode,
  RefreshCw,
  UserRoundCheck,
  Users,
  UsersRound,
  X,
} from "lucide-react";
import { Badge, Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useGroupAttendanceOverview } from "../hooks/use-operations";
import type { AttendanceSessionSummary } from "../api/operations.api";
import {
  OperationsEmptyState,
  OperationsErrorNotice,
  OperationsPageHeader,
  OperationsSummaryItem,
  OperationsSummaryStrip,
  OperationsToolbar,
} from "./operations-workspace-ui";

export function TourGroupAttendancePage({ groupId }: { groupId: string }) {
  const { data, isLoading, error, isFetching } = useGroupAttendanceOverview(groupId);
  const [missingSession, setMissingSession] = useState<AttendanceSessionSummary | null>(null);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const visibleSessions = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    if (!normalized) return data?.sessions ?? [];
    return (data?.sessions ?? []).filter((session) => [
      session.name,
      session.status,
      ...session.coordinators.map((coordinator) => coordinator.coordinator_name),
    ].some((value) => value.toLocaleLowerCase().includes(normalized)));
  }, [data?.sessions, deferredQuery]);
  const activeSessions = (data?.sessions ?? []).filter((session) => session.status !== "completed").length;
  const totalScans = (data?.sessions ?? []).reduce((total, session) => total + session.scanned_count, 0);
  const totalMissing = (data?.sessions ?? []).reduce((total, session) => total + (session.missing_passengers?.length ?? 0), 0);

  return (
    <div className="flex flex-col gap-5">
      <OperationsPageHeader
        eyebrow="Attendance control"
        title={data?.group_name ? `${data.group_name} attendance` : "Attendance"}
        description="Monitor coordinator activity, completion, and the passengers still missing from each live or completed attendance session."
        icon={Activity}
        context={(
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200">
            <RefreshCw className={`h-3.5 w-3.5 text-sky-300 ${isFetching ? "animate-spin" : ""}`} aria-hidden="true" />
            Refreshes every 10 seconds
          </span>
        )}
        actions={(
          <>
            <Link href={ROUTES.dashboard.tourOperationsGroupAssignments as never} className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3.5 text-sm font-semibold text-white transition hover:bg-white/15">
              <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Groups
            </Link>
            <Link href={ROUTES.dashboard.tourOperationsGroupQrCodes(groupId) as never} className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-white px-3.5 text-sm font-semibold text-slate-950 transition hover:bg-sky-50">
              <QrCode className="h-4 w-4 text-blue-700" aria-hidden="true" /> QR codes
            </Link>
          </>
        )}
      />

      {error && (
        <OperationsErrorNotice>
          Attendance could not be refreshed. Previously loaded activity remains visible where available.
        </OperationsErrorNotice>
      )}

      <OperationsSummaryStrip label="Attendance activity summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />)
        ) : (
          <>
            <OperationsSummaryItem label="Activities" value={data?.sessions.length ?? 0} helper="attendance sessions" icon={Activity} />
            <OperationsSummaryItem label="Live now" value={activeSessions} helper="not completed" icon={Clock3} tone={activeSessions > 0 ? "attention" : "default"} />
            <OperationsSummaryItem label="Scans recorded" value={totalScans.toLocaleString()} helper="across activities" icon={CheckCircle2} />
            <OperationsSummaryItem label="Missing" value={totalMissing.toLocaleString()} helper="across activities" icon={UsersRound} tone={totalMissing > 0 ? "attention" : "success"} />
          </>
        )}
      </OperationsSummaryStrip>

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="attendance-activities-heading">
        <div className="border-b border-slate-200 px-4 py-4 sm:px-5">
          <h2 id="attendance-activities-heading" className="font-semibold text-slate-950">Attendance activities</h2>
          <p className="mt-0.5 text-sm text-slate-500">Each activity shows the shared roster count and contribution from every coordinator.</p>
        </div>
        <OperationsToolbar
          query={query}
          onQueryChange={setQuery}
          searchLabel="Search attendance activities"
          placeholder="Search activity, status, or coordinator"
          resultLabel={isLoading ? "Loading activities" : `${visibleSessions.length} of ${data?.sessions.length ?? 0} activities`}
        />

        {isLoading ? (
          <div className="space-y-px bg-slate-100">
            {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-36 rounded-none bg-white" />)}
          </div>
        ) : !data || data.sessions.length === 0 ? (
          <OperationsEmptyState
            title="No attendance activity has started"
            description="When a coordinator starts an activity for this group, live progress and missing passengers will appear here automatically."
          />
        ) : visibleSessions.length === 0 ? (
          <OperationsEmptyState
            filtered
            title="No attendance activity matches this search"
            description="Search by activity name, status, or coordinator, or clear the search to restore all sessions."
            action={<button type="button" onClick={() => setQuery("")} className="text-sm font-semibold text-blue-700 hover:text-blue-900">Clear search</button>}
          />
        ) : (
          <div className="divide-y divide-slate-100">
            {visibleSessions.map((session) => {
              const progress = session.assigned_count === 0 ? 0 : Math.min(100, Math.round((session.scanned_count / session.assigned_count) * 100));
              const missingCount = session.missing_passengers?.length ?? 0;
              return (
                <article key={session.id} className="px-4 py-5 sm:px-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold text-slate-950">{session.name}</h3>
                        <Badge variant={session.status === "completed" ? "success" : "secondary"} dot>{session.status}</Badge>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                        <span className="inline-flex items-center gap-1.5"><UsersRound className="h-3.5 w-3.5" aria-hidden="true" />{session.scanned_count.toLocaleString()} of {session.assigned_count.toLocaleString()} counted</span>
                        <span className="inline-flex items-center gap-1.5"><UserRoundCheck className="h-3.5 w-3.5" aria-hidden="true" />{session.coordinators.length} coordinator{session.coordinators.length === 1 ? "" : "s"}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-lg font-semibold tabular-nums text-slate-950">{progress}%</span>
                      <Button type="button" variant={missingCount > 0 ? "secondary" : "ghost"} size="sm" disabled={missingCount === 0} onClick={() => setMissingSession(session)}>
                        <Users className="h-4 w-4" aria-hidden="true" /> Missing ({missingCount})
                      </Button>
                    </div>
                  </div>
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" aria-label={`${progress}% complete`} role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
                    <div className={`h-full rounded-full transition-[width] ${progress === 100 ? "bg-emerald-500" : "bg-blue-600"}`} style={{ width: `${progress}%` }} />
                  </div>
                  {session.coordinators.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {session.coordinators.map((coordinator) => (
                        <span key={coordinator.coordinator_id} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs">
                          <span className="font-medium text-slate-700">{coordinator.coordinator_name}</span>
                          <span className="font-semibold tabular-nums text-slate-950">{coordinator.scanned_count}/{coordinator.assigned_count}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {missingSession && <MissingPeopleDialog session={missingSession} onClose={() => setMissingSession(null)} />}
    </div>
  );
}

function MissingPeopleDialog({ session, onClose }: { session: AttendanceSessionSummary; onClose: () => void }) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
      if (controls.length === 0) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} className="max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Attendance exception list</p>
            <h2 id={titleId} className="mt-1 font-semibold text-slate-950">Missing people · {session.name}</h2>
            <p className="mt-1 text-sm text-slate-500">{session.scanned_count} of {session.assigned_count} counted</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close missing people list">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="max-h-[65vh] overflow-y-auto p-4">
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
            {session.missing_passengers.map((passenger) => (
              <li key={passenger.passenger_id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-950">{passenger.client_name}</p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">{[passenger.client_phone, passenger.client_email].filter(Boolean).join(" · ") || "No contact details"}</p>
                </div>
                <Badge variant="outline">{passenger.coordinator_name ?? "Shared group roster"}</Badge>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
