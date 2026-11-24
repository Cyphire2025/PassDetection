import { ChevronLeft, ChevronRight, Eye, Loader2 } from "lucide-react";
import { formatDateTime } from "@/lib/utils/format";
import { PassportExportHistoryDetail } from "./passport-export-history-detail";
import type { PassportExportDialogState } from "./use-passport-export-dialog";

export function PassportExportOptions({ state }: { state: PassportExportDialogState }) {
  const {
    history,
    kind,
    mode,
    setMode,
    baselineExportId,
    setBaselineExportId,
    setDetailPage,
    setDetailHistoryId,
    detailHistoryId,
    historyPage,
    setHistoryPage
  } = state;
  return (history.isLoading ? (
    <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-slate-600">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      Loading download history
    </div>
  ) : history.error ? (
    <div
      role="alert"
      className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
    >
      Download history could not be loaded. Close this box and try again.
    </div>
  ) : (
    <>
      <label
        className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-4 transition hover:border-blue-300 hover:bg-blue-50/40"
      >
        <input
          type="radio"
          name={`passport-export-${kind}`}
          value="all"
          checked={mode === "all"}
          onChange={() => setMode("all")}
          className="mt-1 h-4 w-4 accent-blue-600"
        />
        <span>
          <span className="block font-semibold text-slate-900">Download all</span>
          <span className="mt-1 block text-sm text-slate-600">
            Includes all{" "}
            {history.data?.current_submission_count.toLocaleString() ?? 0}{" "}
            current uploads.
          </span>
        </span>
      </label>

      <label
        className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-4 transition hover:border-blue-300 hover:bg-blue-50/40"
      >
        <input
          type="radio"
          name={`passport-export-${kind}`}
          value="incremental"
          checked={mode === "incremental"}
          disabled={!history.data?.total_count}
          onChange={() => setMode("incremental")}
          className="mt-1 h-4 w-4 accent-blue-600"
        />
        <span>
          <span className="block font-semibold text-slate-900">
            Download changes since a previous download
          </span>
          <span className="mt-1 block text-sm text-slate-600">
            Include added and updated records, with a change log identifying removed records.
          </span>
        </span>
      </label>

      {mode === "incremental" && (
        <div className="space-y-2 sm:ml-7">
          {history.data?.items.length ? (
            <>
              {history.data.items.map((item) => (
                <div
                  key={item.id}
                  className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50"
                >
                  <label
                    className={`flex items-start justify-between gap-4 p-3 ${item.compatible
                      ? "cursor-pointer hover:bg-blue-50/50"
                      : "cursor-not-allowed opacity-70"
                      }`}
                  >
                    <span className="flex min-w-0 items-start gap-3">
                      <input
                        type="radio"
                        name={`passport-export-baseline-${kind}`}
                        value={item.id}
                        checked={baselineExportId === item.id}
                        disabled={!item.compatible}
                        onChange={() => setBaselineExportId(item.id)}
                        className="mt-1 h-4 w-4 shrink-0 accent-blue-600"
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold text-slate-900">
                          {formatDateTime(item.completed_at)}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-500">
                          {item.total_available_count.toLocaleString()} uploads
                          existed · file contained{" "}
                          {item.exported_count.toLocaleString()}
                        </span>
                        {item.actor_email && (
                          <span className="mt-0.5 block truncate text-xs text-slate-400">
                            Downloaded by {item.actor_email}
                          </span>
                        )}
                        {!item.compatible && (
                          <span className="mt-1 block text-xs font-medium text-red-700">
                            This checkpoint failed its integrity check.
                          </span>
                        )}
                      </span>
                    </span>
                    <span
                      className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${(item.new_submission_count + (item.changed_submission_count ?? 0) + (item.removed_submission_count ?? 0)) > 0 && item.compatible
                        ? "bg-emerald-100 text-emerald-800"
                        : "bg-slate-200 text-slate-600"
                        }`}
                    >
                      {item.new_submission_count.toLocaleString()} added · {(item.changed_submission_count ?? 0).toLocaleString()} changed · {(item.removed_submission_count ?? 0).toLocaleString()} removed
                    </span>
                  </label>
                  <div className="border-t border-slate-200 bg-white px-3 py-2">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-700 hover:text-blue-800 hover:underline"
                      onClick={() => {
                        setDetailPage(1);
                        setDetailHistoryId((current) => (
                          current === item.id ? undefined : item.id
                        ));
                      }}
                    >
                      <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                      {detailHistoryId === item.id
                        ? "Hide downloaded people"
                        : "View downloaded people"}
                    </button>
                  </div>
                  {detailHistoryId === item.id && (
                    <div className="border-t border-slate-200 bg-white p-3">
                      {<PassportExportHistoryDetail state={state} />}
                    </div>
                  )}
                </div>
              ))}
              {(history.data.total_pages ?? 0) > 1 && (
                <div className="flex items-center justify-end gap-2 pt-1">
                  <button
                    type="button"
                    aria-label="Newer download history page"
                    disabled={historyPage <= 1 || history.isFetching}
                    onClick={() => setHistoryPage((page) => page - 1)}
                    className="rounded-md border border-slate-200 p-1.5 text-slate-600 disabled:opacity-40"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  <span className="text-xs text-slate-500">
                    Download history {historyPage}/{history.data.total_pages}
                  </span>
                  <button
                    type="button"
                    aria-label="Older download history page"
                    disabled={
                      historyPage >= history.data.total_pages
                      || history.isFetching
                    }
                    onClick={() => setHistoryPage((page) => page + 1)}
                    className="rounded-md border border-slate-200 p-1.5 text-slate-600 disabled:opacity-40"
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">
              No downloads have been recorded since download history was
              enabled. Use Download all once to create the first checkpoint.
            </div>
          )}
        </div>
      )}
    </>
  ));
}
