"use client";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspaceHeaderContext,
  WorkspacePageHeader,
} from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  ArrowLeft,
  CalendarDays,
  Download,
  FileText,
  Loader2,
  MapPin,
  MoreVertical,
  UploadCloud,
  UsersRound,
} from "lucide-react";
import { createPortal } from "react-dom";
import type { PassportGroupController } from "./use-passport-group-controller";
export function PassportGroupHeaderPanel({
  importInputRef,
  setImportMessage,
  importMutation,
  setSelectedPassports,
  setSelectedPassportRevisions,
  setSelectionPreset,
  passportImportInputRef,
  handlePassportImportFiles,
  includeDeleted,
  groupDetails,
  submissionsView,
  exportImagesMutation,
  actionsMenuRef,
  actionsMenuButtonRef,
  isActionsMenuOpen,
  setIsActionsMenuOpen,
  setActionsMenuPosition,
  actionsMenuPosition,
  actionsMenuPopupRef,
  setExportDialogKind,
  passportPreviewMutation,
  passportSaveMutation,
  exportMutation,
}: Pick<
  PassportGroupController,
  | "importInputRef"
  | "setImportMessage"
  | "importMutation"
  | "setSelectedPassports"
  | "setSelectedPassportRevisions"
  | "setSelectionPreset"
  | "passportImportInputRef"
  | "handlePassportImportFiles"
  | "includeDeleted"
  | "groupDetails"
  | "submissionsView"
  | "exportImagesMutation"
  | "actionsMenuRef"
  | "actionsMenuButtonRef"
  | "isActionsMenuOpen"
  | "setIsActionsMenuOpen"
  | "setActionsMenuPosition"
  | "actionsMenuPosition"
  | "actionsMenuPopupRef"
  | "setExportDialogKind"
  | "passportPreviewMutation"
  | "passportSaveMutation"
  | "exportMutation"
>) {
  return (
    <>
      <input
        ref={importInputRef}
        type="file"
        accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          setImportMessage(null);
          importMutation.mutate(file, {
            onSuccess: (result) => {
              setSelectedPassports([]);
              setSelectedPassportRevisions({});
              setSelectionPreset("");
              setImportMessage(
                `Imported ${result.imported_count} new, updated ${result.updated_count}, skipped ${result.skipped_count} duplicate row${result.skipped_count === 1 ? "" : "s"}.`,
              );
            },
            onError: (error) => {
              const message =
                error instanceof Error ? error.message : "Import failed";
              setImportMessage(message);
            },
          });
        }}
      />
      <input
        ref={passportImportInputRef}
        type="file"
        multiple
        accept=".zip,image/jpeg,image/png,image/webp"
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          if (!files.length) return;
          void handlePassportImportFiles(files);
        }}
      />
      <WorkspacePageHeader
        title={groupDetails?.group_name ?? "Group Submissions"}
        description={includeDeleted ? "Review archived passenger records and group exports." : "Review passenger records, resolve issues, and manage confirmations and exports."}
        icon={UsersRound}
        accent={includeDeleted ? "amber" : "sky"}
        context={
          <>
            {groupDetails?.destination && (
              <WorkspaceHeaderContext icon={MapPin}>
                {groupDetails.destination}
              </WorkspaceHeaderContext>
            )}
            {groupDetails?.travel_date && (
              <WorkspaceHeaderContext icon={CalendarDays}>
                {groupDetails.travel_date}
              </WorkspaceHeaderContext>
            )}
            <WorkspaceHeaderContext icon={FileText}>
              {(
                submissionsView?.group_total ??
                groupDetails?.total_passports ??
                0
              ).toLocaleString()}{" "}
              passengers
            </WorkspaceHeaderContext>
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            {exportImagesMutation.isPending && (
              <div
                role="status"
                aria-live="polite"
                className="flex shrink-0 items-center gap-2 text-sm font-medium text-slate-100"
              >
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                <span className="hidden xl:inline">
                  Downloading passport images
                </span>
              </div>
            )}
            <IntentPrefetchLink
              href={ROUTES.dashboard.passports}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              All Groups
            </IntentPrefetchLink>
            <div ref={actionsMenuRef} className="relative">
              <Button
                ref={actionsMenuButtonRef}
                type="button"
                size="icon"
                aria-label="Open group actions"
                aria-haspopup="menu"
                aria-expanded={isActionsMenuOpen}
                className="border border-white/20 bg-white/10 text-white shadow-none hover:bg-white/15 active:bg-white/20"
                onClick={() => {
                  if (isActionsMenuOpen) {
                    setIsActionsMenuOpen(false);
                    setActionsMenuPosition(null);
                    return;
                  }
                  const rect =
                    actionsMenuButtonRef.current?.getBoundingClientRect();
                  if (!rect) return;
                  const menuWidth = 256;
                  const menuHeight = 224;
                  const top =
                    rect.bottom + 8 + menuHeight > window.innerHeight
                      ? Math.max(8, rect.top - menuHeight - 8)
                      : rect.bottom + 8;
                  setActionsMenuPosition({
                    left: Math.max(
                      8,
                      Math.min(
                        window.innerWidth - menuWidth - 8,
                        rect.right - menuWidth,
                      ),
                    ),
                    top,
                  });
                  setIsActionsMenuOpen(true);
                }}
              >
                <MoreVertical className="h-4 w-4" aria-hidden="true" />
              </Button>
              {isActionsMenuOpen &&
                actionsMenuPosition &&
                createPortal(
                  <div
                    ref={actionsMenuPopupRef}
                    role="menu"
                    className="fixed z-[70] w-64 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl"
                    style={{
                      left: actionsMenuPosition.left,
                      top: actionsMenuPosition.top,
                    }}
                  >
                    <button
                      type="button"
                      role="menuitem"
                      disabled={
                        exportImagesMutation.isPending ||
                        (submissionsView?.group_total ?? 0) === 0
                      }
                      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        setIsActionsMenuOpen(false);
                        setImportMessage(null);
                        setExportDialogKind("passport_images");
                      }}
                    >
                      <Download className="h-4 w-4 text-slate-500" />
                      {exportImagesMutation.isPending
                        ? "Preparing Images"
                        : "Download Passport Images"}
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={importMutation.isPending}
                      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        setIsActionsMenuOpen(false);
                        importInputRef.current?.click();
                      }}
                    >
                      <UploadCloud className="h-4 w-4 text-slate-500" />
                      {importMutation.isPending ? "Importing" : "Import Excel"}
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={
                        passportPreviewMutation.isPending ||
                        passportSaveMutation.isPending
                      }
                      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        setIsActionsMenuOpen(false);
                        passportImportInputRef.current?.click();
                      }}
                    >
                      <UploadCloud className="h-4 w-4 text-slate-500" />
                      {passportPreviewMutation.isPending
                        ? "Checking documents"
                        : "Import Passports"}
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={
                        exportMutation.isPending ||
                        (submissionsView?.group_total ?? 0) === 0
                      }
                      className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => {
                        setIsActionsMenuOpen(false);
                        setImportMessage(null);
                        setExportDialogKind("passport_excel");
                      }}
                    >
                      <Download className="h-4 w-4 text-slate-500" />
                      {exportMutation.isPending ? "Exporting" : "Export Excel"}
                    </button>
                  </div>,
                  document.body,
                )}
            </div>
          </div>
        }
      />
    </>
  );
}
