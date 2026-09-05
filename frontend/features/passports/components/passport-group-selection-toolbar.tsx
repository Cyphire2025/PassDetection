"use client";
import { Button, Input } from "@/components/ui";
import {
  Download,
  FileSpreadsheet,
  Loader2,
  MoreVertical,
  Search,
  Trash2,
  UserCheck,
} from "lucide-react";
import type {
  PassportGroupSubmissionFilter,
  PassportGroupSubmissionSort,
} from "../api/passports.api";
import {
  MAX_BULK_SELECTION,
  MAX_SELECTED_IMAGE_DOWNLOAD,
} from "./passport-group-bindings";
import type { PassportGroupController } from "./use-passport-group-controller";
export function PassportGroupSelectionToolbar({
  search,
  setSearch,
  setPage,
  isFetching,
  isLoading,
  sortBy,
  setSortBy,
  submissionFilter,
  setSubmissionFilter,
  sortOrder,
  setSortOrder,
  selectionPreset,
  submissionsView,
  handleSelectionPreset,
  customSelectionCount,
  setCustomSelectionCount,
  customSelectionIsValid,
  selectFirstPassports,
  parsedCustomSelectionCount,
  selectedPassports,
  bulkActionsMenuRef,
  bulkActionsButtonRef,
  isBulkActionsMenuOpen,
  bulkActionsDisclosureId,
  setIsBulkActionsMenuOpen,
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
  resetBulkSelection,
  viewMode,
  setViewMode,
}: Pick<
  PassportGroupController,
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
>) {
  return (
    <>
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
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <label className="sr-only" htmlFor="group-submission-sort">
          Sort submissions by
        </label>
        <select
          id="group-submission-sort"
          value={sortBy}
          onChange={(event) => {
            setSortBy(event.target.value as PassportGroupSubmissionSort);
            setPage(1);
          }}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="name">Sort by: Name</option>
          <option value="updated_at">Sort by: Updated</option>
          <option value="verification_confidence">
            Sort by: Verification confidence
          </option>
        </select>
        <label className="sr-only" htmlFor="group-submission-filter">
          Filter submissions
        </label>
        <select
          id="group-submission-filter"
          value={submissionFilter}
          onChange={(event) => {
            setSubmissionFilter(
              event.target.value as PassportGroupSubmissionFilter,
            );
            setPage(1);
          }}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="all">All submissions</option>
          <option value="pending_ai">Pending AI Verification</option>
          <option value="ai_approved">AI Approved</option>
          <option value="needs_review">Needs Review</option>
          <option value="staff_approved">Staff Approved</option>
          <option value="duplicates">Duplicates</option>
        </select>
        <label className="sr-only" htmlFor="group-submission-sort-order">
          Sort direction
        </label>
        <select
          id="group-submission-sort-order"
          value={sortOrder}
          onChange={(event) => {
            setSortOrder(event.target.value as "asc" | "desc");
            setPage(1);
          }}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="asc">Ascending</option>
          <option value="desc">Descending</option>
        </select>
        <label className="sr-only" htmlFor="group-submission-selection">
          Select submissions
        </label>
        <select
          id="group-submission-selection"
          value={selectionPreset}
          disabled={(submissionsView?.total ?? 0) === 0}
          onChange={(event) => handleSelectionPreset(event.target.value)}
          className="h-9 shrink-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <option value="">Select passengers</option>
          <option value="all">
            {(submissionsView?.total ?? 0) > MAX_BULK_SELECTION
              ? "First 1,500 (maximum)"
              : "All"}
          </option>
          <option value="50">First 50</option>
          <option value="100">First 100</option>
          <option value="200">First 200</option>
          <option value="custom">Custom number</option>
        </select>
        {selectionPreset === "custom" && (
          <div className="flex shrink-0 items-center gap-2">
            <label
              className="sr-only"
              htmlFor="group-submission-custom-selection"
            >
              Number of submissions to select
            </label>
            <Input
              id="group-submission-custom-selection"
              type="number"
              min={1}
              max={Math.min(
                MAX_BULK_SELECTION,
                Math.max(1, submissionsView?.total ?? 1),
              )}
              value={customSelectionCount}
              onChange={(event) => setCustomSelectionCount(event.target.value)}
              className="h-9 w-28"
              placeholder="Count"
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={!customSelectionIsValid}
              onClick={() => {
                if (customSelectionIsValid) {
                  selectFirstPassports(parsedCustomSelectionCount);
                }
              }}
            >
              Apply
            </Button>
          </div>
        )}
        {selectedPassports.length > 0 && (
          <>
            <span
              className="shrink-0 text-sm font-medium text-slate-700"
              aria-live="polite"
            >
              {selectedPassports.length.toLocaleString()} selected
            </span>
            <div ref={bulkActionsMenuRef} className="relative shrink-0">
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
              {isBulkActionsMenuOpen && (
                <div
                  id={bulkActionsDisclosureId}
                  aria-label="Bulk submission actions"
                  className="absolute right-0 top-11 z-40 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-xl"
                >
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
                </div>
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
          </>
        )}
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
    </>
  );
}
