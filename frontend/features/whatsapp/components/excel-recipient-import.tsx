"use client";

import { AlertTriangle, CheckCircle2, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { useId } from "react";
import type { RecipientImportState } from "../utils/recipient-import-state";
import { RejectedImportRows } from "./rejected-import-rows";

export function ExcelRecipientImport({
  state,
  onFile,
  label,
  onDismissError,
}: {
  state: RecipientImportState;
  onFile: (file: File) => Promise<void>;
  label: string;
  onDismissError?: () => void;
}) {
  const isLoading = state.status === "loading";
  const fileName = state.status === "idle" ? null : state.fileName;
  const rejectionTitleId = useId();

  return (
    <div className="space-y-2">
      <label
        className={`flex items-center justify-between gap-4 rounded-xl border border-dashed px-4 py-4 ${
          isLoading
            ? "cursor-wait border-blue-300 bg-blue-50/60"
            : "cursor-pointer border-slate-300 bg-white hover:bg-slate-50"
        }`}
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
            {isLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : state.status === "success" && state.rejectedCount > 0 ? (
              <AlertTriangle className="h-5 w-5 text-amber-600" />
            ) : state.status === "success" ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            ) : (
              <FileSpreadsheet className="h-5 w-5" />
            )}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-900">
              {fileName ?? label}
            </span>
            <span className="block text-sm text-slate-500">
              {isLoading
                ? "Reading and validating recipients..."
                : "Use .xlsx or .xlsm with name and phone/WhatsApp columns."}
            </span>
          </span>
        </span>
        <Upload className="h-5 w-5 shrink-0 text-slate-400" />
        <input
          type="file"
          accept=".xlsx,.xlsm"
          className="sr-only"
          disabled={isLoading}
          onChange={(event) => {
            const selectedFile = event.currentTarget.files?.[0] ?? null;
            event.currentTarget.value = "";
            if (selectedFile) void onFile(selectedFile);
          }}
        />
      </label>

      <div>
        {state.status === "success" && (
          <div className="space-y-3">
            <p
              role="status"
              className={`text-sm ${
                state.rejectedCount > 0
                  ? "text-amber-800"
                  : "text-emerald-700"
              }`}
            >
              {state.addedCount} new recipient
              {state.addedCount === 1 ? "" : "s"} added.
              {state.duplicateCount > 0
                ? ` ${state.duplicateCount} contact${state.duplicateCount === 1 ? " was" : "s were"} skipped because the number is already in this list or broadcast.`
                : " You can edit or remove the accepted recipients above before saving."}
              {state.matchingFieldCount > 0
                ? ` ${state.matchingFieldCount} Excel heading${state.matchingFieldCount === 1 ? "" : "s"} will be available for identification matching.`
                : ""}
            </p>
            {state.rejectedCount > 0 && (
              <section
                className="rounded-xl border border-amber-200 bg-amber-50/60 p-3"
                aria-labelledby={rejectionTitleId}
              >
                <h4
                  id={rejectionTitleId}
                  className="font-semibold text-amber-900"
                >
                  {state.rejectedCount} spreadsheet row
                  {state.rejectedCount === 1 ? "" : "s"} need attention
                </h4>
                <p className="mt-1 text-xs text-amber-800">
                  Valid recipients were kept. The rows shown below will be
                  saved with this broadcast for correction, but they cannot
                  receive messages.
                  {state.rejectedRowsTruncated &&
                    ` ${state.omittedRejectedCount} additional rejected row${state.omittedRejectedCount === 1 ? " was" : "s were"} counted but could not be included in this preview.`}
                  {state.retainedSourceFileCount > 0 && " The original workbook is retained in this open dialog so all shared-number source rows can be saved. Your edited recipient list remains authoritative for delivery."}
                </p>
                <RejectedImportRows rows={state.rejectedRows} />
              </section>
            )}
          </div>
        )}
        {state.status === "error" && (
          <div className="space-y-2"><p role="alert" className="text-sm text-red-700">{state.message}</p>{onDismissError && <button type="button" onClick={onDismissError} className="min-h-11 text-left text-sm font-medium text-slate-600 underline focus-visible:ring-2 focus-visible:ring-blue-600">Ignore this failed import and keep the existing list</button>}</div>
        )}
      </div>
    </div>
  );
}
