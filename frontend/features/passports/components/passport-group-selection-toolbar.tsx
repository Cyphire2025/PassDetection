"use client";

import { Button, Input } from "@/components/ui";
import { Loader2, Search } from "lucide-react";
import type { PassportGroupController } from "./use-passport-group-controller";
import { PassportGroupFilterControls } from "./passport-group-filter-controls";
import { PassportGroupSelectedActions } from "./passport-group-selected-actions";

export type PassportGroupSelectionToolbarProps = Pick<
  PassportGroupController,
  | "documentFollowUp"
  | "canEditDisplayName"
  | "setDisplayNameEditorId"
  | "search"
  | "setSearch"
  | "setPage"
  | "isFetching"
  | "isLoading"
  | "sortBy"
  | "setSortBy"
  | "submissionFilter"
  | "setSubmissionFilter"
  | "sortOrder"
  | "setSortOrder"
  | "selectionPreset"
  | "submissionsView"
  | "handleSelectionPreset"
  | "customSelectionCount"
  | "setCustomSelectionCount"
  | "customSelectionIsValid"
  | "selectFirstPassports"
  | "parsedCustomSelectionCount"
  | "selectedPassports"
  | "bulkActionsMenuRef"
  | "bulkActionsButtonRef"
  | "isBulkActionsMenuOpen"
  | "bulkActionsDisclosureId"
  | "setIsBulkActionsMenuOpen"
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
  | "viewMode"
  | "setViewMode"
>;

export function PassportGroupSelectionToolbar(props: PassportGroupSelectionToolbarProps) {
  const { search, setSearch, setPage, isFetching, isLoading, viewMode, setViewMode, selectedPassports } = props;
  return (<>
    <div className="relative max-w-md">
      <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
      <Input
        aria-label="Search group passengers"
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(1);
        }}
        placeholder="Search name, email, phone, passport number"
        className="h-10 pl-9"
      />
      {isFetching && !isLoading && (
        <Loader2
          className="absolute right-3 top-3 h-4 w-4 animate-spin text-blue-600"
          aria-label="Updating submissions"
        />
      )}
    </div>
    <div
      data-workspace-toolbar=""
      className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm"
    >
      <PassportGroupFilterControls {...props} />
      {selectedPassports.length > 0 && <PassportGroupSelectedActions {...props} />}
      <Button
        type="button"
        variant={viewMode === "docs" ? "primary" : "secondary"}
        size="sm"
        className="shrink-0 whitespace-nowrap"
        onClick={() =>
          setViewMode((current) => (current === "docs" ? "table" : "docs"))
        }
      >
        {viewMode === "docs" ? "Table view" : "DOCS view"}
      </Button>
    </div>
  </>);
}
