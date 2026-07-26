"use client";

import {
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  FileSpreadsheet,
  Images,
  Loader2,
  X,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import type {
  PassportGroupExportKind,
  PassportGroupExportMode,
} from "../api/passports.api";
import {
  usePassportGroupExportHistory,
  usePassportGroupExportFields,
  usePassportGroupExportHistoryDetail,
} from "../hooks/use-passports";
import { PassportExcelFieldChooser } from "./passport-excel-field-chooser";

interface PassportExportDialogProps {
  groupId: string;
  kind: PassportGroupExportKind;
  isDownloading: boolean;
  onClose: () => void;
  onDownload: (selection: {
    mode: PassportGroupExportMode;
    baselineExportId?: string;
    supplementalFields?: string[];
    groupByField?: string;
  }) => void;
}

export function PassportExportDialog({
  groupId,
  kind,
  isDownloading,
  onClose,
  onDownload,
}: PassportExportDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const downloadStartedRef = useRef(false);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(false);
  const [mode, setMode] = useState<PassportGroupExportMode>("all");
  const [historyPage, setHistoryPage] = useState(1);
  const [baselineExportId, setBaselineExportId] = useState<string>();
  const [detailHistoryId, setDetailHistoryId] = useState<string>();
  const [detailPage, setDetailPage] = useState(1);
  const [isStartingDownload, setIsStartingDownload] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [groupByField, setGroupByField] = useState("");
  const fieldsInitializedRef = useRef(false);
  const history = usePassportGroupExportHistory(groupId, kind, historyPage);
  const historyDetail = usePassportGroupExportHistoryDetail(
    groupId,
    detailHistoryId,
    detailPage,
  );
  const isImages = kind === "passport_images";
  const exportFields = usePassportGroupExportFields(groupId, !isImages);
  const isBusy = isDownloading || isStartingDownload;
  const selectedBaseline = history.data?.items.find(
    (item) => item.id === baselineExportId,
  );

  useEffect(() => {
    if (!exportFields.data || fieldsInitializedRef.current) return;
    fieldsInitializedRef.current = true;
    setSelectedFields(exportFields.data.default_selected_fields);
    setGroupByField(exportFields.data.default_group_by_field ?? "");
  }, [exportFields.data]);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    busyRef.current = isBusy;
  }, [isBusy]);

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(
      () => closeButtonRef.current?.focus(),
      0,
    );
    const handleKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (
        event.shiftKey
        && (active === first || !dialogRef.current?.contains(active))
      ) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyboard);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyboard);
      document.body.style.overflow = priorOverflow;
      previouslyFocused?.focus();
    };
  }, []);

  const canDownload = (
    !isBusy
    && !history.isLoading
    && (
      mode === "all"
      || Boolean(
        baselineExportId
        && selectedBaseline
        && selectedBaseline.compatible
        && selectedBaseline.new_submission_count > 0,
      )
    )
  );
  const isExcelFieldStep = !isImages && step === 2;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isBusy) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
              {isImages ? (
                <Images className="h-5 w-5" aria-hidden="true" />
              ) : (
                <FileSpreadsheet className="h-5 w-5" aria-hidden="true" />
              )}
            </span>
            <div>
              <h2 id={titleId} className="font-semibold text-slate-950">
                {isImages ? "Download passport images" : "Export passport Excel"}
              </h2>
              <p id={descriptionId} className="mt-1 text-sm text-slate-600">
                {isExcelFieldStep
                  ? "Choose the saved fields and grouping for this Excel file."
                  : "Choose the complete group or only uploads added after a recorded download."}
              </p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close export options"
            disabled={isBusy}
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="max-h-[calc(90vh-9rem)] space-y-3 overflow-y-auto p-5 sm:p-6">
          {isExcelFieldStep ? (
            exportFields.isLoading ? (
              <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-slate-600">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Loading saved Excel fields
              </div>
            ) : exportFields.error ? (
              <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                Saved Excel fields could not be loaded. Go back and try again.
              </div>
            ) : exportFields.data ? (
              <PassportExcelFieldChooser
                options={exportFields.data}
                selectedFields={selectedFields}
                onSelectedFieldsChange={setSelectedFields}
                groupByField={groupByField}
                onGroupByFieldChange={setGroupByField}
                heading="Step 2: Choose Excel columns"
              />
            ) : null
          ) : history.isLoading ? (
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
              <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-4 transition hover:border-blue-300 hover:bg-blue-50/40">
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

              <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-4 transition hover:border-blue-300 hover:bg-blue-50/40">
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
                    Download uploads after a previous download
                  </span>
                  <span className="mt-1 block text-sm text-slate-600">
                    Select any recorded checkpoint. Only people not present at that
                    time are included.
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
                        <label className={`flex items-start justify-between gap-4 p-3 ${
                          item.compatible
                            ? "cursor-pointer hover:bg-blue-50/50"
                            : "cursor-not-allowed opacity-70"
                        }`}>
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
                            className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${
                              item.new_submission_count > 0 && item.compatible
                                ? "bg-emerald-100 text-emerald-800"
                                : "bg-slate-200 text-slate-600"
                            }`}
                          >
                            {item.new_submission_count.toLocaleString()} new
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
                            {historyDetail.isLoading ? (
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
                            )}
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
          )}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
          <Button
            type="button"
            variant="secondary"
            disabled={isBusy}
            onClick={() => {
              if (isExcelFieldStep) {
                setStep(1);
              } else {
                onClose();
              }
            }}
          >
            {isExcelFieldStep ? "Back" : "Cancel"}
          </Button>
          <Button
            type="button"
            disabled={
              !canDownload
              || (isExcelFieldStep && (exportFields.isLoading || Boolean(exportFields.error)))
            }
            isLoading={isBusy}
            onClick={() => {
              if (!isImages && step === 1) {
                setStep(2);
                return;
              }
              if (downloadStartedRef.current || isDownloading) return;
              downloadStartedRef.current = true;
              setIsStartingDownload(true);
              try {
                onDownload({
                  mode,
                  ...(mode === "incremental" && baselineExportId
                    ? { baselineExportId }
                    : {}),
                  ...(!isImages ? {
                    supplementalFields: selectedFields,
                    groupByField: groupByField || "none",
                  } : {}),
                });
              } catch (downloadError) {
                downloadStartedRef.current = false;
                setIsStartingDownload(false);
                throw downloadError;
              }
            }}
          >
            {!isImages && step === 1 ? (
              <>
                Next
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </>
            ) : (
              <>
                <Download className="h-4 w-4" aria-hidden="true" />
                {mode === "all"
                  ? (isImages ? "Download all" : "Download Excel")
                  : `Download ${selectedBaseline?.new_submission_count ?? 0} new`}
              </>
            )}
          </Button>
        </div>
      </section>
    </div>
  );
}
