"use client";

import { Download, FileSpreadsheet, Loader2, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui";
import { useSelectedGroupsExportFields } from "../hooks/use-passports";
import { PassportExcelFieldChooser } from "./passport-excel-field-chooser";

interface PassportSelectedGroupsExportDialogProps {
  groupIds: string[];
  isDownloading: boolean;
  hasDownloadError: boolean;
  onClose: () => void;
  onDownload: (selection: {
    supplementalFields: string[];
    groupByField: string;
  }) => Promise<void>;
}

export function PassportSelectedGroupsExportDialog({
  groupIds,
  isDownloading,
  hasDownloadError,
  onClose,
  onDownload,
}: PassportSelectedGroupsExportDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const downloadStartedRef = useRef(false);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(false);
  const fieldsInitializedRef = useRef(false);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [groupByField, setGroupByField] = useState("");
  const [isStartingDownload, setIsStartingDownload] = useState(false);
  const exportFields = useSelectedGroupsExportFields(groupIds);
  const isBusy = isDownloading || isStartingDownload;

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
    const previouslyFocused = (
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    );
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
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
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
              <FileSpreadsheet className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h2 id={titleId} className="font-semibold text-slate-950">
                Export selected groups
              </h2>
              <p id={descriptionId} className="mt-1 text-sm text-slate-600">
                Choose the combined saved fields and grouping for all{" "}
                {groupIds.length.toLocaleString()} selected groups.
              </p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close selected groups export options"
            disabled={isBusy}
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="max-h-[calc(90vh-9rem)] space-y-4 overflow-y-auto p-5 sm:p-6">
          {exportFields.isLoading ? (
            <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-slate-600">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Loading combined Excel fields
            </div>
          ) : exportFields.error ? (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              Combined Excel fields could not be loaded. Close this box and try again.
            </div>
          ) : exportFields.data ? (
            <PassportExcelFieldChooser
              options={exportFields.data}
              selectedFields={selectedFields}
              onSelectedFieldsChange={setSelectedFields}
              groupByField={groupByField}
              onGroupByFieldChange={setGroupByField}
            />
          ) : null}

          {hasDownloadError && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
            >
              The Excel file could not be created. Review the selected options and try again.
            </div>
          )}
        </div>

        <div className="flex flex-col-reverse gap-2 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
          <Button
            type="button"
            variant="secondary"
            disabled={isBusy}
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={
              isBusy
              || exportFields.isLoading
              || Boolean(exportFields.error)
              || !exportFields.data
            }
            isLoading={isBusy}
            onClick={async () => {
              if (downloadStartedRef.current || isDownloading) return;
              downloadStartedRef.current = true;
              setIsStartingDownload(true);
              try {
                await onDownload({
                  supplementalFields: selectedFields,
                  groupByField: groupByField || "none",
                });
              } catch {
                downloadStartedRef.current = false;
                setIsStartingDownload(false);
              }
            }}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            Download Excel
          </Button>
        </div>
      </section>
    </div>
  );
}
