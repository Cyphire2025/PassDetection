"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { Button, Card, CardContent, Input } from "@/components/ui";
import type { EcrBatch, EcrBatchStatus, EcrItem } from "@/types/ecr-checker.types";

type Filter = "all" | "ECR" | "NA" | "review" | "failed" | "pending";
const PAGE_SIZE = 50;

export function ecrBatchStatusLabel(status: EcrBatchStatus) {
  return {
    uploading: "Upload incomplete",
    queued: "Queued for checking",
    processing: "Checking images",
    completed: "Check complete",
    completed_with_errors: "Complete · attention needed",
  }[status] ?? status;
}

export function ecrItemDisplay(item: Pick<EcrItem, "status" | "result">) {
  if (item.status === "failed") return { label: "Failed", className: "text-rose-700", filter: "failed" } as const;
  if (item.status !== "completed") return { label: item.status === "processing" ? "Checking…" : "Queued", className: "text-slate-500", filter: "pending" } as const;
  if (item.result === "ECR") return { label: "ECR present", className: "font-bold text-red-600", filter: "ECR" } as const;
  if (item.result === "NA") return { label: "NA · ECR not present", className: "text-black", filter: "NA" } as const;
  return { label: "Needs review", className: "font-semibold text-amber-800", filter: "review" } as const;
}

export function EcrResults({ batch, action, onAction }: {
  batch: EcrBatch;
  action: "retry" | "export" | null;
  onAction: (action: "retry" | "export") => Promise<void>;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const active = ["queued", "processing"].includes(batch.status);
  const terminal = ["completed", "completed_with_errors"].includes(batch.status);
  const percent = batch.expected_count ? Math.min(100, Math.floor(100 * batch.processed_count / batch.expected_count)) : 0;
  const filtered = useMemo(() => batch.items.filter((item) =>
    (filter === "all" || ecrItemDisplay(item).filter === filter)
    && (!deferredSearch || item.original_filename.toLowerCase().includes(deferredSearch)),
  ), [batch.items, filter, deferredSearch]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const visiblePage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(visiblePage * PAGE_SIZE, (visiblePage + 1) * PAGE_SIZE);
  const pending = Math.max(0, batch.expected_count - batch.processed_count);
  const tabs: { key: Filter; label: string; count: number }[] = [
    { key: "all", label: "All", count: batch.total_count },
    { key: "ECR", label: "ECR", count: batch.ecr_count },
    { key: "NA", label: "NA", count: batch.na_count },
    { key: "review", label: "Needs review", count: batch.review_count },
    { key: "failed", label: "Failed", count: batch.failed_count },
    { key: "pending", label: "Pending", count: pending },
  ];

  return (
    <Card>
      <CardContent className="p-0">
        <div className="space-y-4 border-b border-slate-100 p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0"><h2 className="break-words text-lg font-semibold text-slate-950">{batch.title}</h2><p className="mt-1 text-sm text-slate-600">{batch.processed_count.toLocaleString()} of {batch.expected_count.toLocaleString()} checked · {ecrBatchStatusLabel(batch.status)}</p></div>
            <div className="flex flex-wrap gap-2">
              {batch.failed_count > 0 && terminal && <Button variant="secondary" onClick={() => void onAction("retry")} disabled={action !== null} isLoading={action === "retry"}><RefreshCw className="h-4 w-4" aria-hidden="true" />Retry failed checks</Button>}
              <Button onClick={() => void onAction("export")} disabled={!terminal || action !== null} isLoading={action === "export"}><Download className="h-4 w-4" aria-hidden="true" />Download Excel</Button>
            </div>
          </div>
          {active && (
            <div className="space-y-2 rounded-xl bg-blue-50 p-4" role="status">
              <p className="text-sm font-medium text-blue-950">{percent}% complete · Multiple images are checked at the same time.</p>
              <div role="progressbar" aria-label="ECR checking progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="h-2 overflow-hidden rounded-full bg-white"><div className="h-full bg-blue-600 transition-all" style={{ width: `${percent}%` }} /></div>
              <p className="text-xs text-blue-800">You can leave this page. Reopen this saved batch to see progress and download the final report.</p>
            </div>
          )}
          {(batch.review_count > 0 || batch.failed_count > 0) && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
              {batch.review_count} need manual review and {batch.failed_count} failed. These appear as REVIEW or ERROR in Excel. Check their original images before using the results.
            </div>
          )}
          <p className="text-xs leading-5 text-slate-500">Excel contains two columns: File name and ECR. Confirmed ECR is red; NA is black. NA means the wording was not visible on a clear, complete back page.</p>
          <p className="text-xs leading-5 text-slate-500">Source images are kept for retries for a limited period (7 days by default). Saved results remain available after the images expire.</p>
          <div className="flex flex-wrap gap-2" aria-label="Filter ECR results">
            {tabs.map((tab) => <button key={tab.key} type="button" aria-pressed={filter === tab.key} onClick={() => { setFilter(tab.key); setPage(0); }} className={`rounded-full border px-3 py-2 text-xs font-semibold transition ${filter === tab.key ? "border-blue-300 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}>{tab.label} ({tab.count})</button>)}
          </div>
          <div className="max-w-md"><Input label="Search filenames" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} placeholder="Find an image in this batch" /></div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Passport back-page ECR results</caption>
            <thead><tr className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><th scope="col" className="w-12 px-5 py-3">#</th><th scope="col" className="px-5 py-3">File name</th><th scope="col" className="min-w-44 px-5 py-3">ECR</th><th scope="col" className="px-5 py-3">Details</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {visible.map((item, index) => {
                const display = ecrItemDisplay(item);
                return <tr key={item.id}><td className="px-5 py-3 text-xs text-slate-400">{visiblePage * PAGE_SIZE + index + 1}</td><td className="max-w-96 break-words px-5 py-3 font-medium text-slate-800">{item.original_filename}</td><td className={`px-5 py-3 ${display.className}`}>{display.label}</td><td className="max-w-md break-words px-5 py-3 text-xs leading-5 text-slate-500">{item.reason || "—"}</td></tr>;
              })}
            </tbody>
          </table>
          {!visible.length && <p className="p-8 text-center text-sm text-slate-500">No images match this filter.</p>}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 p-4 text-xs text-slate-500">
          <span>{filtered.length ? visiblePage * PAGE_SIZE + 1 : 0}–{Math.min((visiblePage + 1) * PAGE_SIZE, filtered.length)} of {filtered.length} images</span>
          <div className="flex items-center gap-3"><Button variant="secondary" size="sm" disabled={visiblePage === 0} onClick={() => setPage(visiblePage - 1)}>Previous</Button><span>Page {visiblePage + 1} of {pageCount}</span><Button variant="secondary" size="sm" disabled={visiblePage + 1 >= pageCount} onClick={() => setPage(visiblePage + 1)}>Next</Button></div>
        </div>
      </CardContent>
    </Card>
  );
}
