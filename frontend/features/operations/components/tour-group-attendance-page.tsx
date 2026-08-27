"use client";

import Link from "next/link";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
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
import { Badge, Button, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import {
  useCompleteManagedAttendanceSession,
  useCreateManagedAttendanceSession,
  useGroupAttendanceMissingPassengers,
  useGroupAttendanceSummary,
} from "../hooks/use-operations";
import {
  operationsApi,
  type AttendanceActivitySummary,
} from "../api/operations.api";
import {
  OperationsEmptyState,
  OperationsErrorNotice,
  OperationsPageHeader,
  OperationsSummaryItem,
  OperationsSummaryStrip,
  OperationsToolbar,
} from "./operations-workspace-ui";

export function TourGroupAttendancePage({ groupId }: { groupId: string }) {
  const role = useAuthStore(selectUserRole);
  const { data, isLoading, error, isFetching, refetch } = useGroupAttendanceSummary(groupId);
  const closeMutation = useCompleteManagedAttendanceSession();
  const createMutation = useCreateManagedAttendanceSession();
  const [missingSessionId, setMissingSessionId] = useState<string | null>(null);
  const [attendanceNotice, setAttendanceNotice] = useState<{ kind: "error" | "success"; message: string } | null>(null);
  const [activityName, setActivityName] = useState("");
  const [closeoutExceptionReasons, setCloseoutExceptionReasons] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const visibleSessions = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    if (!normalized) return data?.sessions ?? [];
    return (data?.sessions ?? []).filter((session) => [
      session.name,
      session.status,
      ...session.coordinators.map((coordinator) => coordinator.coordinator_name),
    ]
      .some((value) => value.toLocaleLowerCase().includes(normalized)));
  }, [data?.sessions, deferredQuery]);
  const openSessions = (data?.sessions ?? []).filter(
    (session) => session.status === "draft" || session.status === "active",
  ).length;
  const totalScans = (data?.sessions ?? []).reduce((total, session) => total + session.present_count, 0);
  const totalMissing = (data?.sessions ?? []).reduce((total, session) => total + session.missing_count, 0);
  const missingSession = data?.sessions.find((session) => session.id === missingSessionId) ?? null;
  const canCloseActivity = role === "super_admin"
    || role === "agency_admin"
    || role === "agency_manager";
  const closeMissingPeople = useCallback(() => setMissingSessionId(null), []);
  const refreshAttendance = useCallback(() => {
    void refetch();
  }, [refetch]);

  const prepareActivity = async () => {
    const normalizedName = activityName.trim();
    if (!canCloseActivity || normalizedName.length < 2 || createMutation.isPending) return;
    setAttendanceNotice(null);
    let prepared: Awaited<ReturnType<typeof createMutation.mutateAsync>>;
    try {
      prepared = await createMutation.mutateAsync({ groupId, name: normalizedName });
    } catch {
      setAttendanceNotice({
        kind: "error",
        message: "The attendance activity could not be created. Check the name and try again.",
      });
      return;
    }
    setActivityName("");
    try {
      const refreshed = await refetch();
      setAttendanceNotice(refreshed.error
        ? {
            kind: "error",
            message: `${prepared.name} is ready, but the latest activity list could not be loaded.`,
          }
        : {
            kind: "success",
            message: `${prepared.name} is ready. Coordinators can now select its stable activity ID.`,
          });
    } catch {
      setAttendanceNotice({
        kind: "error",
        message: `${prepared.name} is ready, but the latest activity list could not be loaded.`,
      });
    }
  };

  const closeForEveryone = async (
    candidate: AttendanceActivitySummary,
    requestedExceptionReason?: string,
  ) => {
    if (!canCloseActivity || closeMutation.isPending) return;
    setAttendanceNotice(null);

    const refreshed = await refetch().catch(() => null);
    if (!refreshed) {
      setAttendanceNotice({
        kind: "error",
        message: "The authoritative server count could not be refreshed, so the activity was not closed.",
      });
      return;
    }
    const authoritative = refreshed.data?.sessions.find((session) => session.id === candidate.id);
    if (refreshed.error || !authoritative) {
      setAttendanceNotice({
        kind: "error",
        message: "The authoritative server count could not be refreshed, so the activity was not closed.",
      });
      return;
    }
    if (authoritative.status !== "active") {
      setAttendanceNotice({
        kind: "success",
        message: "This activity is already closed. The latest server status is now displayed.",
      });
      return;
    }

    let closeout: Awaited<ReturnType<typeof operationsApi.managedAttendanceCloseoutStatus>>;
    try {
      closeout = await operationsApi.managedAttendanceCloseoutStatus(groupId, authoritative.id);
    } catch {
      setAttendanceNotice({
        kind: "error",
        message: "Coordinator checkpoint evidence could not be refreshed, so the activity was not closed.",
      });
      return;
    }

    const exceptionReason = requestedExceptionReason?.trim().replace(/\s+/g, " ") ?? "";
    const exceptionRequired = !closeout.ready;
    if (exceptionRequired && (exceptionReason.length < 10 || exceptionReason.length > 500)) {
      setAttendanceNotice({
        kind: "error",
        message: "Enter a specific closeout exception reason between 10 and 500 characters.",
      });
      return;
    }

    const reviewed = window.confirm(
      exceptionRequired
        ? closeout.active_assignment_count === 0
          ? `OVERRIDE REQUIRED: no coordinator account is assigned, so no affirmative checkpoint evidence exists. Exception reason: "${exceptionReason}".`
          : `OVERRIDE REQUIRED: ${closeout.blocked_assignment_count} of ${closeout.active_assignment_count} coordinator checkpoints are blocked, missing, or stale, with ${closeout.unresolved_count} unresolved scans reported. Exception reason: "${exceptionReason}".`
        : `The server confirms ${authoritative.present_count} of ${authoritative.present_count + authoritative.missing_count} passengers and all ${closeout.active_assignment_count} participating coordinator checkpoints are recent and clear. Queued scans captured before closure can still reconcile.`,
    );
    if (!reviewed) return;
    const confirmed = window.confirm(
      exceptionRequired
        ? "Final warning: close for every coordinator despite coordinator checkpoint blockers and permanently audit this manager exception?"
        : "Close this shared activity for every coordinator? New camera capture will stop. This does not discard scans already saved before closure.",
    );
    if (!confirmed) return;

    try {
      await closeMutation.mutateAsync({
        groupId,
        sessionId: authoritative.id,
        exceptionReason: exceptionRequired ? exceptionReason : undefined,
      });
      if (exceptionRequired) {
        setCloseoutExceptionReasons((current) => ({ ...current, [authoritative.id]: "" }));
      }
    } catch {
      setAttendanceNotice({ kind: "error", message: "The shared activity could not be closed." });
      return;
    }

    try {
      const afterClose = await refetch();
      setAttendanceNotice(afterClose.error
        ? {
            kind: "error",
            message: "The shared activity was closed, but the latest status could not be loaded.",
          }
        : {
            kind: "success",
            message: exceptionRequired
              ? "The shared activity is closed with an audited manager exception."
              : "The shared activity is closed for every coordinator.",
          });
    } catch {
      setAttendanceNotice({
        kind: "error",
        message: "The shared activity was closed, but the latest status could not be loaded.",
      });
    }
  };

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
            {openSessions > 0
              ? "Targeted updates with 5–7 second repair"
              : "Targeted updates with 30–40 second repair"}
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
          Attendance could not be refreshed. Any visible counts are the last confirmed snapshot and are not current authority.
        </OperationsErrorNotice>
      )}

      {attendanceNotice && (
        <div
          role={attendanceNotice.kind === "error" ? "alert" : "status"}
          className={`rounded-xl border px-4 py-3 text-sm ${
            attendanceNotice.kind === "error"
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : "border-emerald-200 bg-emerald-50 text-emerald-900"
          }`}
        >
          {attendanceNotice.message}
        </div>
      )}

      {canCloseActivity && (
        <section className="rounded-xl border border-blue-200 bg-blue-50/60 p-4 shadow-sm" aria-labelledby="prepare-attendance-heading">
          <div className="mb-3">
            <h2 id="prepare-attendance-heading" className="font-semibold text-slate-950">Prepare attendance activity</h2>
            <p className="mt-1 text-sm text-slate-600">
              Create the canonical name and UUID before coordinators scan. Repeating the same open name reuses its stable ID.
            </p>
          </div>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              void prepareActivity();
            }}
          >
            <div className="min-w-0 flex-1">
              <Input
                id="managed-attendance-activity-name"
                label="Activity name"
                value={activityName}
                onChange={(event) => setActivityName(event.target.value)}
                placeholder="Airport reporting count"
                autoComplete="off"
                minLength={2}
                maxLength={160}
                required
                disabled={createMutation.isPending}
              />
            </div>
            <Button
              type="submit"
              className="h-11 sm:min-w-44"
              disabled={activityName.trim().length < 2 || createMutation.isPending}
              isLoading={createMutation.isPending}
            >
              Create activity
            </Button>
          </form>
        </section>
      )}

      <OperationsSummaryStrip label="Attendance activity summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />)
        ) : (
          <>
            <OperationsSummaryItem label="Activities" value={data?.sessions.length ?? 0} helper="attendance sessions" icon={Activity} />
            <OperationsSummaryItem label="Open now" value={openSessions} helper="draft or active" icon={Clock3} tone={openSessions > 0 ? "attention" : "default"} />
            <OperationsSummaryItem label="Scans recorded" value={totalScans.toLocaleString()} helper="across activities" icon={CheckCircle2} />
            <OperationsSummaryItem label="Missing" value={totalMissing.toLocaleString()} helper="across activities" icon={UsersRound} tone={totalMissing > 0 ? "attention" : "success"} />
          </>
        )}
      </OperationsSummaryStrip>

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="attendance-activities-heading">
        <div className="border-b border-slate-200 px-4 py-4 sm:px-5">
          <h2 id="attendance-activities-heading" className="font-semibold text-slate-950">Attendance activities</h2>
          <p className="mt-0.5 text-sm text-slate-500">Each activity shows the shared roster count and bounded coordinator contribution without loading the passenger roster.</p>
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
            title="No attendance activity is prepared"
            description={canCloseActivity
              ? "Create the canonical activity above before coordinators begin scanning."
              : "An authorized manager or administrator must create the canonical activity before scanning begins."}
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
              const passengerCount = session.present_count + session.missing_count;
              const progress = passengerCount === 0
                ? 0
                : Math.min(100, Math.round((session.present_count / passengerCount) * 100));
              const missingCount = session.missing_count;
              return (
                <article key={session.id} className="px-4 py-5 sm:px-5">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold text-slate-950">{session.name}</h3>
                        <Badge variant={session.status === "completed" ? "success" : "secondary"} dot>{session.status}</Badge>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
                        <span className="inline-flex items-center gap-1.5"><UsersRound className="h-3.5 w-3.5" aria-hidden="true" />{session.present_count.toLocaleString()} of {passengerCount.toLocaleString()} counted</span>
                        <span className="inline-flex items-center gap-1.5"><UserRoundCheck className="h-3.5 w-3.5" aria-hidden="true" />{session.coordinator_count} coordinator{session.coordinator_count === 1 ? "" : "s"}</span>
                        <span>Canonical update {new Date(session.last_canonical_update_at).toLocaleTimeString()}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-lg font-semibold tabular-nums text-slate-950">{progress}%</span>
                      <Button type="button" variant={missingCount > 0 ? "secondary" : "ghost"} size="sm" disabled={missingCount === 0} onClick={() => setMissingSessionId(session.id)}>
                        <Users className="h-4 w-4" aria-hidden="true" /> Missing ({missingCount})
                      </Button>
                      {canCloseActivity && session.status === "active" && session.closeout.ready && (
                        <Button
                          type="button"
                          variant="danger"
                          size="sm"
                          disabled={closeMutation.isPending}
                          isLoading={closeMutation.isPending && closeMutation.variables?.sessionId === session.id}
                          onClick={() => void closeForEveryone(session)}
                        >
                          Close after clear checkpoints
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" aria-label={`${progress}% complete`} role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
                    <div className={`h-full rounded-full transition-[width] ${progress === 100 ? "bg-emerald-500" : "bg-blue-600"}`} style={{ width: `${progress}%` }} />
                  </div>
                  {session.status === "active" && (
                    <div className={`mt-4 rounded-xl border p-3 ${
                      session.closeout.ready
                        ? "border-emerald-200 bg-emerald-50/70"
                        : "border-amber-300 bg-amber-50"
                    }`}>
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className={`text-sm font-semibold ${session.closeout.ready ? "text-emerald-900" : "text-amber-950"}`}>
                            {session.closeout.ready
                              ? "Coordinator checkpoints clear"
                              : "Coordinator checkpoints blocked"}
                          </p>
                          <p className="mt-1 text-xs leading-5 text-slate-700">
                            {session.closeout.ready
                              ? `${session.closeout.ready_participant_count} of ${session.closeout.active_participant_count} participating coordinators published a recent zero-queue checkpoint.`
                              : session.closeout.active_participant_count === 0
                                ? "No coordinator account is assigned. Closing requires an audited manager exception."
                                : `${session.closeout.blocked_participant_count} of ${session.closeout.active_participant_count} participant checkpoints are missing, stale, or nonzero; ${session.closeout.unresolved_count} unresolved scans are reported.`}
                          </p>
                        </div>
                        <span className="rounded-full border border-current/20 px-2.5 py-1 text-xs font-semibold text-slate-700">
                          {session.exception_count.toLocaleString()} rejected or review issue{session.exception_count === 1 ? "" : "s"}
                        </span>
                      </div>
                      {session.coordinators.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {session.coordinators.map((coordinator) => {
                            const unresolved = coordinator.pending_count
                              + coordinator.sending_count
                              + coordinator.retryable_count
                              + coordinator.needs_review_count
                              + coordinator.unreviewed_rejected_count;
                            return (
                              <span
                                key={coordinator.coordinator_id}
                                className={`rounded-lg border px-2.5 py-1.5 text-xs ${
                                  coordinator.checkpoint_state === "ready"
                                    ? "border-emerald-200 bg-white text-emerald-800"
                                    : "border-amber-300 bg-white text-amber-900"
                                }`}
                              >
                                <span className="font-semibold">{coordinator.coordinator_name}</span>
                                {` · ${coordinator.checkpoint_state}`}
                                {unresolved > 0 ? ` · ${unresolved} unresolved` : ""}
                                {coordinator.runtime_count > 1
                                  ? ` · ${coordinator.active_runtime_count}/${coordinator.runtime_count} active runtimes`
                                  : ""}
                              </span>
                            );
                          })}
                        </div>
                      )}
                      {session.coordinators_truncated && (
                        <p className="mt-2 text-xs font-medium text-amber-900" role="status">
                          Showing {session.coordinators.length} of {session.coordinator_count} coordinators in this bounded live summary.
                        </p>
                      )}
                      {canCloseActivity && !session.closeout.ready && (
                        <div className="mt-4 rounded-lg border border-red-200 bg-white p-3">
                          <p className="text-sm font-semibold text-red-900">Manager exception</p>
                          <p className="mt-1 text-xs leading-5 text-red-800">
                            Use only when an operational emergency requires closing despite missing, stale, or nonzero coordinator evidence. The reason and full count snapshot are permanently audited.
                            Enter an operational reason only; do not include passenger names, QR values, passport details, or other personal information.
                          </p>
                          <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
                            <Input
                              id={`closeout-exception-${session.id}`}
                              label="Exception reason"
                              value={closeoutExceptionReasons[session.id] ?? ""}
                              onChange={(event) => setCloseoutExceptionReasons((current) => ({
                                ...current,
                                [session.id]: event.target.value,
                              }))}
                              minLength={10}
                              maxLength={500}
                              autoComplete="off"
                              placeholder="Document the specific emergency and approval"
                              disabled={closeMutation.isPending}
                            />
                            <Button
                              type="button"
                              variant="danger"
                              disabled={
                                closeMutation.isPending
                                || (closeoutExceptionReasons[session.id]?.trim().length ?? 0) < 10
                              }
                              isLoading={closeMutation.isPending && closeMutation.variables?.sessionId === session.id}
                              onClick={() => void closeForEveryone(
                                session,
                                closeoutExceptionReasons[session.id],
                              )}
                            >
                              Override and close
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
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

      {missingSession && (
        <MissingPeopleDialog
          groupId={groupId}
          session={missingSession}
          onClose={closeMissingPeople}
          onRefresh={refreshAttendance}
        />
      )}
    </div>
  );
}

function MissingPeopleDialog({
  groupId,
  session,
  onClose,
  onRefresh,
}: {
  groupId: string;
  session: AttendanceActivitySummary;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const missingQuery = useGroupAttendanceMissingPassengers({
    groupId,
    sessionId: session.id,
    revision: session.revision,
    search: deferredSearch,
    enabled: true,
  });
  const passengers = useMemo(() => {
    const seen = new Set<string>();
    return (missingQuery.data?.pages ?? []).flatMap((page) => page.items).filter((item) => {
      if (seen.has(item.passenger_id)) return false;
      seen.add(item.passenger_id);
      return true;
    });
  }, [missingQuery.data?.pages]);

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
      const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
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
            <p className="mt-1 text-sm text-slate-500">{session.present_count} of {session.present_count + session.missing_count} counted · revision-fenced roster</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close missing people list">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="border-b border-slate-100 p-4">
          <Input
            id={`missing-passenger-search-${session.id}`}
            label="Search missing passengers"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by passenger name"
            maxLength={120}
            autoComplete="off"
          />
          <p className="mt-2 text-xs text-slate-500">
            {passengers.length.toLocaleString()} loaded{deferredSearch ? " for this filter" : ` of ${session.missing_count.toLocaleString()} missing`}. Contact and family details are not stored in this view.
          </p>
        </div>
        <div className="max-h-[55vh] overflow-y-auto p-4">
          {missingQuery.error ? (
            <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
              <p className="font-semibold">The missing-passenger snapshot changed or could not be loaded.</p>
              <p className="mt-1">Refresh authoritative counts and reopen this list. No attendance record was changed.</p>
              <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={onRefresh}>
                Refresh counts
              </Button>
            </div>
          ) : missingQuery.isLoading ? (
            <div className="grid gap-2" aria-label="Loading missing passengers">
              {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-14 rounded-lg" />)}
            </div>
          ) : passengers.length === 0 ? (
            <div className="rounded-xl border border-slate-200 p-6 text-center text-sm text-slate-600">
              {deferredSearch ? "No missing passenger matches this search." : "No passengers are missing in this revision."}
            </div>
          ) : (
            <>
              <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                {passengers.map((passenger) => (
                  <li
                    key={passenger.passenger_id}
                    className="flex items-center justify-between gap-3 px-4 py-3"
                    style={{ contentVisibility: "auto", containIntrinsicSize: "0 52px" }}
                  >
                    <p className="min-w-0 truncate text-sm font-semibold text-slate-950">{passenger.display_name}</p>
                    <Badge variant="outline">Shared group roster</Badge>
                  </li>
                ))}
              </ul>
              {missingQuery.hasNextPage && (
                <Button
                  type="button"
                  variant="secondary"
                  className="mt-3 w-full"
                  disabled={missingQuery.isFetchingNextPage}
                  isLoading={missingQuery.isFetchingNextPage}
                  onClick={() => { void missingQuery.fetchNextPage(); }}
                >
                  Load next page
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
