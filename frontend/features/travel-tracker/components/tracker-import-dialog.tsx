"use client";

import { useId, useRef, useState } from "react";
import { FileSpreadsheet, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { travelTrackerApi } from "../api";
import { pastedNamesFile, trackerError, TRACKER_COPY } from "../model";
import type { TrackerImportPreview, TrackerKind } from "../types";
import { TrackerImportResults } from "./tracker-import-preview";

export function TrackerImportDialog({ groupId, groupName, track, onClose, onApply }: {
  groupId: string; groupName: string; track: TrackerKind; onClose: () => void;
  onApply: (preview: TrackerImportPreview) => Promise<boolean>;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [source, setSource] = useState<"excel" | "paste">("excel");
  const [file, setFile] = useState<File | null>(null);
  const [names, setNames] = useState("");
  const [marked, setMarked] = useState(true);
  const [preview, setPreview] = useState<TrackerImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keyDown = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: !busy, onClose });
  const copy = TRACKER_COPY[track];

  const runPreview = async () => {
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      const input = source === "paste" ? pastedNamesFile(names) : file;
      if (!input) throw new Error("Choose an Excel or CSV file first.");
      if (input.size > 8 * 1024 * 1024) throw new Error("Choose an Excel or CSV file smaller than 8 MB.");
      setPreview(await travelTrackerApi.preview(groupId, input, track, marked));
    } catch (reason) { setError(trackerError(reason)); }
    finally { setBusy(false); }
  };
  const applyPreview = async () => {
    if (!preview?.passenger_ids.length) return;
    setBusy(true);
    setError(null);
    try {
      if (await onApply(preview)) onClose();
      else setError("The update could not be confirmed. The passenger list has been refreshed; you can retry this batch.");
    } catch (reason) { setError(trackerError(reason)); }
    finally { setBusy(false); }
  };

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={keyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-3 backdrop-blur-sm sm:p-5">
      <div className="flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 p-4 sm:px-5"><div><h2 id={titleId} className="flex items-center gap-2 text-lg font-semibold text-slate-950"><FileSpreadsheet className="h-5 w-5 text-blue-600" />Update {copy.label.toLowerCase()} from a list</h2><p className="mt-1 break-words text-xs text-slate-500">{groupName} · Match first, then apply the reviewed passengers.</p></div><button type="button" aria-label="Close import" onClick={onClose} disabled={busy} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"><X className="h-5 w-5" /></button></div>
        <div className="space-y-4 overflow-y-auto p-4 sm:p-5">
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1" role="group" aria-label="Import source">{(["excel", "paste"] as const).map((option) => <button type="button" key={option} aria-pressed={source === option} disabled={busy} onClick={() => { setSource(option); setPreview(null); setError(null); }} className={`min-h-10 rounded-md text-sm font-medium ${source === option ? "bg-white text-blue-700 shadow-sm" : "text-slate-600 hover:bg-white/60"}`}>{option === "excel" ? "Excel / CSV" : "Paste names"}</button>)}</div>
          <label className="block text-sm font-medium text-slate-700">Set matched passengers to<select aria-label="Status for matched passengers" value={marked ? "marked" : "pending"} disabled={busy} onChange={(event) => { setMarked(event.target.value === "marked"); setPreview(null); }} className="mt-1.5 min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm"><option value="marked">{copy.marked}</option><option value="pending">{copy.pending}</option></select></label>
          {source === "excel" ? <div className="rounded-xl border border-dashed border-blue-300 bg-blue-50/40 p-4"><label className="block text-sm font-medium text-slate-800" htmlFor="tracker-import-file">Choose Excel or CSV<input id="tracker-import-file" aria-label="Excel or CSV passenger file" type="file" accept=".xlsx,.csv" disabled={busy} onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); setError(null); }} className="mt-3 block w-full text-xs text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-blue-100 file:px-3 file:py-2 file:font-semibold file:text-blue-800" /></label><p className="mt-3 text-xs leading-5 text-slate-500">Use a passenger ID, passport number or full name column. Tracker exports can be uploaded directly. Up to 1,000 passenger rows and 8 MB per batch.</p></div> : <label className="block text-sm font-medium text-slate-700">Passenger names<textarea aria-label="Passenger names to match" value={names} disabled={busy} onChange={(event) => { setNames(event.target.value); setPreview(null); setError(null); }} rows={6} placeholder={"Paste one full name per line\nAsha Mehta\nRavi Shah"} className="mt-1.5 w-full resize-y rounded-lg border border-slate-300 p-3 text-sm font-normal text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100" /><span className="mt-1 block text-xs font-normal leading-5 text-slate-500">Exact, unique full names are matched within this group. Duplicate names need a passport number or passenger ID in Excel.</span></label>}
          {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm leading-6 text-red-800">{error}</p>}
          {preview && <TrackerImportResults key={`${preview.total_rows}-${source}-${marked}`} preview={preview} />}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 p-4">
          <Button variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button>
          {preview ? <Button isLoading={busy} disabled={!preview.passenger_ids.length} onClick={() => void applyPreview()}>{`Apply ${preview.passenger_ids.length.toLocaleString()} matches`}</Button> : <Button isLoading={busy} disabled={source === "excel" ? !file : !names.trim()} onClick={() => void runPreview()} leftIcon={<Upload className="h-4 w-4" />}>Preview matches</Button>}
        </div>
      </div>
    </div>
  );
}
