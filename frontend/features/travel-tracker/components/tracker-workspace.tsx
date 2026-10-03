"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, CalendarDays, CheckCircle2, Clock3, MapPin, Plane, RefreshCw, Undo2, UsersRound } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { WorkspaceEmptyState, WorkspaceErrorNotice, WorkspaceHeaderContext, WorkspacePageHeader, WorkspaceSummaryItem, WorkspaceSummaryStrip } from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/modal";
import { Skeleton } from "@/components/ui/skeleton";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { isDownloadCancelled } from "@/lib/api/download-destination";
import { travelTrackerApi } from "../api";
import { useTrackerActions, useTrackerRoster } from "../hooks";
import { formatTravelDate, isPassengerMarked, trackerError, TRACKER_COPY } from "../model";
import type { TrackerImportPreview, TrackerKind, TrackerPassenger, TrackerStatus } from "../types";
import { TrackerControls } from "./tracker-controls";
import { TrackerImportDialog } from "./tracker-import-dialog";
import { TrackerPagination } from "./tracker-pagination";
import { TrackerPassengerList } from "./tracker-passenger-list";

export function TrackerWorkspace({ groupId }: { groupId: string }) {
  const [track, setTrack] = useState<TrackerKind>("visa");
  const [status, setStatus] = useState<TrackerStatus>("pending");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [importOpen, setImportOpen] = useState(false);
  const [bulk, setBulk] = useState<{ marked: boolean; count: number; status: TrackerStatus; search: string; track: TrackerKind } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const query = useDebounce(search.trim(), 250);
  const roster = useTrackerRoster(groupId, { track, status, search: query, page, page_size: 50 });
  const actions = useTrackerActions(groupId);
  const exporting = useMutation({ mutationFn: (value: TrackerStatus) => travelTrackerApi.export(groupId, roster.data?.group.name ?? groupId, track, value) });
  const group = roster.data?.group;
  const counts = roster.data?.counts;
  const copy = TRACKER_COPY[track];
  const rowBusy = Object.keys(actions.pending).length > 0;
  const busy = actions.bulkBusy || rowBusy;
  const fetching = roster.isFetching || query !== search.trim();
  const lastPage = Math.max(1, Math.ceil((roster.data?.total ?? 0) / 50));
  if (roster.data && page > lastPage) setPage(lastPage);

  const markPassenger = async (passenger: TrackerPassenger) => {
    const buttons = Array.from(listRef.current?.querySelectorAll<HTMLButtonElement>("[data-passenger-row]") ?? []);
    const index = buttons.findIndex((button) => button.dataset.passengerId === passenger.id);
    const focused = buttons[index] === document.activeElement;
    const result = await actions.mark({ track, marked: !isPassengerMarked(passenger, track), passenger_ids: [passenger.id] }, passenger.full_name, true);
    if (result && focused && !buttons[index]?.isConnected && document.activeElement === document.body) {
      const remaining = listRef.current?.querySelectorAll<HTMLButtonElement>("[data-passenger-row]:not(:disabled)");
      if (remaining?.length) remaining[Math.min(index, remaining.length - 1)]?.focus();
    }
  };
  const applyImport = async (preview: TrackerImportPreview) => Boolean(await actions.mark({ track: preview.track, marked: preview.marked, passenger_ids: preview.passenger_ids }, "Reviewed list applied."));
  const confirmBulk = async () => {
    if (!bulk) return;
    await actions.mark({ track: bulk.track, marked: bulk.marked, selection: { status: bulk.status, search: bulk.search }, expected_count: bulk.count }, "Filtered list updated.");
    // Close after a failure as well so a changed roster cannot reuse an old count.
    setBulk(null);
  };
  const markPage = () => {
    if (!roster.data?.passengers.length) return;
    void actions.mark({ track, marked: status !== "marked", passenger_ids: roster.data.passengers.map((passenger) => passenger.id) }, "Current page updated.");
  };

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <WorkspacePageHeader className="[&_h1]:break-words" title={group?.name ?? "Visa / Flight Tracker"} description="Track visa applications and flight bookings for every passenger in this travel group." icon={Plane} context={group && <><WorkspaceHeaderContext icon={MapPin}>{group.destination || "Destination not set"}</WorkspaceHeaderContext><WorkspaceHeaderContext icon={CalendarDays}>{formatTravelDate(group.travel_date)}</WorkspaceHeaderContext><WorkspaceHeaderContext icon={UsersRound}>All link submissions and imported passengers</WorkspaceHeaderContext></>} actions={<><Button variant="secondary" disabled={fetching || busy} onClick={() => void roster.refetch()} aria-label="Refresh tracker" leftIcon={<RefreshCw className={`h-4 w-4 ${fetching ? "animate-spin" : ""}`} />}>Refresh</Button><IntentPrefetchLink href={ROUTES.dashboard.travelTracker} className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-700"><ArrowLeft className="h-4 w-4" />All groups</IntentPrefetchLink></>} />
      <WorkspaceSummaryStrip label={`${copy.label} tracking progress`} columns={3}>
        <WorkspaceSummaryItem label="Passengers" value={counts?.total.toLocaleString() ?? "—"} helper="whole group" icon={UsersRound} />
        <WorkspaceSummaryItem label={copy.marked} value={counts?.marked.toLocaleString() ?? "—"} helper={counts?.total ? `${Math.round((counts.marked / counts.total) * 100)}% complete` : "tracked separately"} icon={CheckCircle2} tone="success" />
        <WorkspaceSummaryItem label={copy.pending} value={counts?.pending.toLocaleString() ?? "—"} helper="left to process" icon={Clock3} tone="attention" />
      </WorkspaceSummaryStrip>
      {actions.notice && <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"><span>{actions.notice}</span>{actions.undo && <Button variant="ghost" size="sm" disabled={busy} onClick={actions.undoLast} leftIcon={<Undo2 className="h-3.5 w-3.5" />}>Undo last change</Button>}</div>}
      {actions.error && <WorkspaceErrorNotice>{actions.error} <button type="button" onClick={actions.clearError} className="ml-2 font-semibold underline">Dismiss</button></WorkspaceErrorNotice>}
      {exporting.error && !isDownloadCancelled(exporting.error) && <WorkspaceErrorNotice>{trackerError(exporting.error)}</WorkspaceErrorNotice>}
      {exporting.isPending && <p role="status" className="text-sm text-slate-500">Preparing {exporting.variables} Excel export…</p>}
      <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-label="Passenger tracking workspace">
        <TrackerControls track={track} status={status} search={search} count={roster.data?.total ?? 0} pageCount={roster.data?.passengers.length ?? 0} busy={busy} fetching={fetching} exportBusy={exporting.isPending} onTrack={(value) => { setTrack(value); setPage(1); }} onStatus={(value) => { setStatus(value); setPage(1); }} onSearch={(value) => { setSearch(value); setPage(1); }} onBulk={(marked) => setBulk({ marked, count: roster.data?.total ?? 0, status, search: query, track })} onPageMark={markPage} onImport={() => setImportOpen(true)} onExport={(value) => exporting.mutate(value)} />
        <div id="tracker-roster-panel" role="tabpanel" aria-labelledby={`tracker-tab-${track}`}>
          {roster.error ? <div className="space-y-3 p-4"><WorkspaceErrorNotice>{trackerError(roster.error)}</WorkspaceErrorNotice><Button variant="secondary" onClick={() => void roster.refetch()}>Retry loading passengers</Button></div> : roster.isLoading ? <div className="space-y-2 p-4">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-20 rounded-xl" />)}</div> : !roster.data?.passengers.length ? <WorkspaceEmptyState filtered={Boolean(query) || status !== "all"} title={status === "pending" && !query && counts?.total ? `All ${copy.label.toLowerCase()} passengers are marked` : "No passengers in this view"} description={query ? "Try another name, passport number or contact, or clear the search." : status !== "all" ? "Choose All to see every passenger, or switch to the other tracker." : "Passengers submitted through the group link or added by import will appear here."} /> : <div ref={listRef} aria-busy={actions.bulkBusy}><TrackerPassengerList passengers={roster.data.passengers} track={track} pending={actions.pending} disabled={actions.bulkBusy} onMark={(passenger) => void markPassenger(passenger)} /></div>}
        </div>
        {roster.data && <TrackerPagination page={page} pageSize={50} total={roster.data.total} busy={fetching || busy} onChange={setPage} />}
      </section>
      <ConfirmDialog isOpen={Boolean(bulk)} title={bulk?.marked ? `Mark ${bulk.count.toLocaleString()} passengers` : `Move ${bulk?.count.toLocaleString() ?? 0} passengers to pending`} description={`This updates every passenger matching the ${bulk?.status ?? status} filter${bulk?.search ? ` and search “${bulk.search}”` : ""}, across all pages of this group. Set their ${bulk?.track === "flight" ? "flight booking" : "visa application"} status to ${bulk?.marked ? "marked" : "pending"}.`} confirmLabel={bulk?.marked ? "Mark filtered passengers" : "Move to pending"} isLoading={actions.bulkBusy} onConfirm={() => void confirmBulk()} onClose={() => setBulk(null)} />
      {importOpen && group && <TrackerImportDialog groupId={groupId} groupName={group.name} track={track} onClose={() => setImportOpen(false)} onApply={applyImport} />}
    </div>
  );
}
