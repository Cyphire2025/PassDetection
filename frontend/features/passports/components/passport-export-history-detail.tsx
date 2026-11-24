import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import type { PassportExportDialogState } from "./use-passport-export-dialog";

export function PassportExportHistoryDetail({ state }: { state: PassportExportDialogState }) {
  const { historyDetail, detailPage, setDetailPage } = state;
  return (historyDetail.isLoading ? (
    <div className="flex items-center gap-2 py-3 text-xs text-slate-500">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      Loading exact download contents
    </div>
  ) : historyDetail.error ? (
    <p className="py-2 text-xs text-red-700">
      The exact download contents could not be loaded.
    </p>
  ) : (
    <>
      <ul className="divide-y divide-slate-100">
        {historyDetail.data?.items.map((person) => (
          <li
            key={person.submission_id}
            className="flex flex-col gap-0.5 py-2 text-xs sm:flex-row sm:items-center sm:justify-between sm:gap-3"
          >
            <span className="font-semibold text-slate-800">
              {person.client_name || "Unnamed upload"}
            </span>
            <span className="text-slate-500">
              {[
                person.client_phone,
                person.passport_number,
                person.client_email,
              ].filter(Boolean).join(" · ") || "No extra details"}
              {!person.record_available && (
                <span className="ml-1 text-amber-700">
                  · Original record later deleted
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {(historyDetail.data?.total_pages ?? 0) > 1 && (
        <div className="mt-2 flex items-center justify-end gap-2">
          <button
            type="button"
            aria-label="Previous history detail page"
            disabled={detailPage <= 1}
            onClick={() => setDetailPage((page) => page - 1)}
            className="rounded-md border border-slate-200 p-1.5 text-slate-600 disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <span className="text-xs text-slate-500">
            {detailPage}/{historyDetail.data?.total_pages}
          </span>
          <button
            type="button"
            aria-label="Next history detail page"
            disabled={
              detailPage >= (historyDetail.data?.total_pages ?? 0)
            }
            onClick={() => setDetailPage((page) => page + 1)}
            className="rounded-md border border-slate-200 p-1.5 text-slate-600 disabled:opacity-40"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </>
  ));
}
