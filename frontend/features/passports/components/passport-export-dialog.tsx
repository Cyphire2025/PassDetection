"use client";

import { FileSpreadsheet, Images, X } from "lucide-react";
import type { PassportGroupExportKind, PassportGroupExportMode } from "../api/passports.api";
import { usePassportExportDialog } from "./use-passport-export-dialog";
import { PassportExportFields } from "./passport-export-fields";
import { PassportExportOptions } from "./passport-export-options";
import { PassportExportFooter } from "./passport-export-footer";

export interface PassportExportDialogProps {
  groupId: string;
  kind: PassportGroupExportKind;
  isDownloading: boolean;
  onClose: () => void;
  onDownload: (selection: {
    mode: PassportGroupExportMode;
    baselineExportId?: string;
    supplementalFields?: string[];
    groupByField?: string;
    agencyMatchField?: string;
  }) => Promise<void>;
}

export function PassportExportDialog({
  groupId,
  kind,
  isDownloading,
  onClose,
  onDownload,
}: PassportExportDialogProps) {
  const state = usePassportExportDialog({ groupId, kind, isDownloading, onClose, onDownload });
  const { isImages, titleId, descriptionId, isExcelFieldStep, isBusy, dialogRef, handleKeyDown } = state;
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
        onKeyDown={handleKeyDown}
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
                  : "Choose the complete group or changes since a recorded download."}
              </p>
            </div>
          </div>
          <button
            data-dialog-initial-focus
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
          {isExcelFieldStep ? <PassportExportFields state={state} /> : <PassportExportOptions state={state} />}
        </div>

        <PassportExportFooter state={state} />
      </section>
    </div>
  );
}
