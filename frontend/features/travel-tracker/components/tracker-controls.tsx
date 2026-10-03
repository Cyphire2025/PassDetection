import { FileDown, FileSpreadsheet, Plane, Stamp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { TRACKER_COPY } from "../model";
import type { TrackerKind, TrackerStatus } from "../types";

export function TrackerControls({ track, status, search, count, pageCount, busy, fetching, exportBusy, onTrack, onStatus, onSearch, onBulk, onPageMark, onImport, onExport }: {
  track: TrackerKind; status: TrackerStatus; search: string; count: number; pageCount: number;
  busy: boolean; fetching: boolean; exportBusy: boolean;
  onTrack: (value: TrackerKind) => void; onStatus: (value: TrackerStatus) => void;
  onSearch: (value: string) => void; onBulk: (marked: boolean) => void;
  onPageMark: () => void; onImport: () => void; onExport: (status: TrackerStatus) => void;
}) {
  const copy = TRACKER_COPY[track];
  const canMutate = !busy && !fetching && count > 0;
  return (
    <>
      <div className="flex flex-col justify-between gap-3 border-b border-slate-200 p-4 sm:flex-row sm:items-center">
        <div role="tablist" aria-label="Tracking type" className="inline-grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1">{(["visa", "flight"] as const).map((value) => { const Icon = value === "visa" ? Stamp : Plane; return <button type="button" key={value} id={`tracker-tab-${value}`} role="tab" aria-selected={track === value} aria-controls="tracker-roster-panel" tabIndex={track === value ? 0 : -1} disabled={busy} onClick={() => onTrack(value)} onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === "Home" ? "visa" : event.key === "End" ? "flight" : value === "visa" ? "flight" : "visa";
          onTrack(next);
          document.getElementById(`tracker-tab-${next}`)?.focus();
        }} className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:px-5 ${track === value ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:bg-white/60"}`}><Icon className="h-4 w-4 shrink-0" aria-hidden="true" />{value === "visa" ? "Visa applications" : "Flight bookings"}</button>; })}</div>
        <Button variant="secondary" className="min-h-11" onClick={onImport} disabled={busy} leftIcon={<FileSpreadsheet className="h-4 w-4" />}>Update from Excel / list</Button>
      </div>
      <WorkspaceToolbar query={search} onQueryChange={onSearch} searchLabel="Search tracker passengers" placeholder="Search name, passport, phone or email" resultLabel={fetching ? "Refreshing passengers…" : `${count.toLocaleString()} passengers`}>
        <div role="group" aria-label="Passenger status filter" className="inline-flex gap-1 rounded-lg border border-slate-200 bg-white p-1">{(["all", "pending", "marked"] as const).map((value) => <button key={value} type="button" aria-pressed={status === value} onClick={() => onStatus(value)} disabled={busy} className={`min-h-8 rounded-md px-3 text-xs font-semibold capitalize ${status === value ? "bg-blue-50 text-blue-700" : "text-slate-500 hover:bg-slate-50"}`}>{value === "marked" ? "Marked" : value === "pending" ? "Pending" : "All"}</button>)}</div>
      </WorkspaceToolbar>
      <div className="flex flex-col justify-between gap-3 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-center">
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={!canMutate || count > 20_000} onClick={() => onBulk(status !== "marked")} className="min-h-10">{status === "marked" ? "Move filtered to pending" : "Mark filtered"} ({count.toLocaleString()})</Button>
          <Button variant="secondary" disabled={!canMutate || !pageCount} onClick={onPageMark} className="min-h-10">{status === "marked" ? "Reset this page" : "Mark this page"} ({pageCount})</Button>
        </div>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`${copy.label} Excel exports`}>
          <FileDown className="hidden h-4 w-4 text-slate-400 sm:block" aria-hidden="true" />
          {(["marked", "pending", "all"] as const).map((value) => <Button key={value} variant="outline" size="sm" className="min-h-9" disabled={exportBusy} onClick={() => onExport(value)}>{value === "marked" ? "Marked Excel" : value === "pending" ? "Pending Excel" : "All Excel"}</Button>)}
        </div>
      </div>
      {count > 20_000 && <p className="border-b border-slate-200 bg-amber-50 px-4 py-2 text-xs leading-5 text-amber-800">Filtered updates support up to 20,000 passengers at once. Narrow the search or mark one page at a time.</p>}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50/50 px-4 py-2.5 text-xs leading-5 text-slate-500"><span>Tap anywhere on a passenger row to mark or undo. <span className="hidden sm:inline">Use ↑ / ↓ to move and Enter / Space to mark.</span></span><span>Excel exports include the whole group and all passenger details.</span></div>
    </>
  );
}
