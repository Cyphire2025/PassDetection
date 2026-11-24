import { createPortal } from "react-dom";
import { usePassportBulkMenuPosition } from "./use-passport-bulk-menu-position";
import { Button } from "@/components/ui";
import { Download, FileSpreadsheet, MoreVertical, Trash2, UserCheck } from "lucide-react";
import { MAX_SELECTED_IMAGE_DOWNLOAD } from "./passport-group-bindings";
import { DocumentFollowUpActions } from "./passport-document-follow-up";
import { PassportDisplayNameAction } from "./passport-display-name-action";
import type { PassportGroupSelectionToolbarProps } from "./passport-group-selection-toolbar";

type Props = Pick<
  PassportGroupSelectionToolbarProps,
  | "selectedPassports"
  | "bulkActionsMenuRef"
  | "bulkActionsButtonRef"
  | "isBulkActionsMenuOpen"
  | "bulkActionsDisclosureId"
  | "setIsBulkActionsMenuOpen"
  | "documentFollowUp"
  | "canEditDisplayName"
  | "setDisplayNameEditorId"
  | "canBulkStaffApprove"
  | "includeDeleted"
  | "bulkStaffApprove"
  | "setBulkDeleteFeedback"
  | "setIsBulkApprovalConfirmationOpen"
  | "exportSelected"
  | "exportSelectedImages"
  | "handleSelectedPassportDownload"
  | "canPermanentlyDelete"
  | "bulkDelete"
  | "setIsBulkDeleteConfirmationOpen"
  | "resetBulkSelection"
>;

export function PassportGroupSelectedActions({
  selectedPassports,
  bulkActionsMenuRef,
  bulkActionsButtonRef,
  isBulkActionsMenuOpen,
  bulkActionsDisclosureId,
  setIsBulkActionsMenuOpen,
  documentFollowUp,
  canEditDisplayName,
  setDisplayNameEditorId,
  canBulkStaffApprove,
  includeDeleted,
  bulkStaffApprove,
  setBulkDeleteFeedback,
  setIsBulkApprovalConfirmationOpen,
  exportSelected,
  exportSelectedImages,
  handleSelectedPassportDownload,
  canPermanentlyDelete,
  bulkDelete,
  setIsBulkDeleteConfirmationOpen,
  resetBulkSelection
}: Props) {
  const position = usePassportBulkMenuPosition(isBulkActionsMenuOpen, bulkActionsButtonRef, bulkActionsMenuRef);
  return (<>
    <span
      className="shrink-0 text-sm font-medium text-slate-700"
      aria-live="polite"
    >
      {selectedPassports.length.toLocaleString()} selected
    </span>
    <div className="relative shrink-0">
      <Button
        ref={bulkActionsButtonRef}
        type="button"
        variant="secondary"
        size="icon"
        aria-label={`Open bulk actions for ${selectedPassports.length} selected submissions`}
        aria-expanded={isBulkActionsMenuOpen}
        aria-controls={bulkActionsDisclosureId}
        onClick={() => setIsBulkActionsMenuOpen((open) => !open)}
      >
        <MoreVertical className="h-4 w-4" />
      </Button>
      {isBulkActionsMenuOpen && typeof document !== "undefined" && createPortal(
        <div
          ref={bulkActionsMenuRef}
          id={bulkActionsDisclosureId}
          aria-label="Bulk submission actions"
          role="group"
          tabIndex={-1}
          style={position ?? { left: 0, top: 0, visibility: "hidden" }}
          className="fixed z-[70] max-h-[calc(100dvh-1rem)] w-64 max-w-[calc(100vw-1rem)] overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-xl"
        >
          <DocumentFollowUpActions followUp={documentFollowUp} selectedCount={selectedPassports.length} />
          <PassportDisplayNameAction
            canEdit={canEditDisplayName}
            selectedIds={selectedPassports}
            onEdit={(id) => { setIsBulkActionsMenuOpen(false); setDisplayNameEditorId(id); }}
          />
          {canBulkStaffApprove && !includeDeleted && (
            <button
              type="button"
              disabled={bulkStaffApprove.isPending}
              className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => {
                setIsBulkActionsMenuOpen(false);
                setBulkDeleteFeedback(null);
                setIsBulkApprovalConfirmationOpen(true);
              }}
            >
              <UserCheck className="h-4 w-4 text-emerald-600" />
              Staff approve all selected ({selectedPassports.length})
            </button>
          )}
          <button
            type="button"
            disabled={exportSelected.isPending}
            className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => {
              setIsBulkActionsMenuOpen(false);
              exportSelected.mutate(selectedPassports);
            }}
          >
            <FileSpreadsheet className="h-4 w-4 text-slate-500" />
            Export Excel ({selectedPassports.length})
          </button>
          <button
            type="button"
            disabled={
              exportSelectedImages.isPending ||
              selectedPassports.length > MAX_SELECTED_IMAGE_DOWNLOAD
            }
            className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => {
              setIsBulkActionsMenuOpen(false);
              handleSelectedPassportDownload();
            }}
          >
            <Download className="h-4 w-4 text-slate-500" />
            {selectedPassports.length > MAX_SELECTED_IMAGE_DOWNLOAD
              ? `Download Passport Images (select up to ${MAX_SELECTED_IMAGE_DOWNLOAD})`
              : `Download Passport Images (${selectedPassports.length})`}
          </button>
          {canPermanentlyDelete && !includeDeleted && (
            <button
              type="button"
              disabled={bulkDelete.isPending}
              className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => {
                setIsBulkActionsMenuOpen(false);
                setBulkDeleteFeedback(null);
                setIsBulkDeleteConfirmationOpen(true);
              }}
            >
              <Trash2 className="h-4 w-4" />
              Delete selected ({selectedPassports.length})
            </button>
          )}
        </div>,
        document.body,
      )}
    </div>
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="shrink-0 whitespace-nowrap"
      onClick={resetBulkSelection}
    >
      Clear selection
    </Button>
  </>);
}
