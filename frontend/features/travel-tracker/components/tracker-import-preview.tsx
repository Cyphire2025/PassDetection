import { useState } from "react";
import type { TrackerImportPreview } from "../types";
import { TrackerPagination } from "./tracker-pagination";

export function TrackerImportResults({ preview }: { preview: TrackerImportPreview }) {
  const [page, setPage] = useState(1);
  const [issuesOnly, setIssuesOnly] = useState(false);
  const rows = issuesOnly ? preview.rows.filter((row) => row.status !== "matched") : preview.rows;
  const visible = rows.slice((page - 1) * 25, page * 25);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Import match summary">
        {([
          ["Matched", preview.matched_count, "text-emerald-700 bg-emerald-50 border-emerald-200"],
          ["Ambiguous", preview.ambiguous_count, "text-amber-800 bg-amber-50 border-amber-200"],
          ["Unmatched", preview.unmatched_count, "text-red-700 bg-red-50 border-red-200"],
          ["Duplicates", preview.duplicate_count, "text-slate-600 bg-slate-50 border-slate-200"],
        ] as const).map(([label, count, tone]) => <div key={label} className={`rounded-lg border p-3 ${tone}`}><p className="text-xs font-medium">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums">{count.toLocaleString()}</p></div>)}
      </div>
      <p className="text-xs leading-5 text-slate-500">Only unique matches can be applied. Ambiguous names, unmatched records and repeated rows are skipped. A passenger ID or passport number gives the strongest match.</p>
      <div className="overflow-hidden rounded-xl border border-slate-200">
        <div className="flex items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 p-3"><h3 className="text-sm font-semibold text-slate-800">Review matches</h3><button type="button" className="rounded-lg px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50" onClick={() => { setIssuesOnly((value) => !value); setPage(1); }}>{issuesOnly ? "Show all rows" : "Show issues only"}</button></div>
        <div className="max-h-80 overflow-y-auto divide-y divide-slate-100">
          {!visible.length && <p className="p-4 text-sm text-slate-500">No issues in this batch.</p>}
          {visible.map((row) => <div key={row.row_number} className="flex items-start justify-between gap-3 px-3 py-2.5"><div className="min-w-0"><p className="break-words text-sm font-medium text-slate-900"><span className="mr-2 text-xs tabular-nums text-slate-400">Row {row.row_number}</span>{row.name || row.passport_number || "Empty identity"}</p>{row.passenger_name && <p className="mt-0.5 text-xs text-emerald-700">Matches {row.passenger_name}</p>}<p className="mt-0.5 break-words text-xs leading-5 text-slate-500">{row.reason}</p></div><span className={`shrink-0 rounded-md px-2 py-1 text-[11px] font-medium capitalize ${row.status === "matched" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>{row.status}</span></div>)}
        </div>
        <TrackerPagination page={page} pageSize={25} total={rows.length} busy={false} onChange={setPage} />
      </div>
    </div>
  );
}
