"use client";

import { EmptyState } from "@/components/shared/empty-state";
import { Button, Skeleton } from "@/components/ui";
import { FileText, UploadCloud } from "lucide-react";
import { PassportDocumentMatrix } from "./passport-group-model";
import type { PassportGroupController } from "./use-passport-group-controller";
import { PassportGroupRosterTable } from "./passport-group-roster-table";

export function PassportGroupRosterPanel({
  error,
  isLoading,
  submissionsView,
  groupDetails,
  data,
  setSearch,
  setDebouncedSearch,
  setSubmissionFilter,
  setSortBy,
  setSortOrder,
  setPage,
  viewMode,
  filteredPassports,
  canEditImages,
  includeDeleted,
  imageRevisions,
  setImageEditor,
  debouncedSearch,
  selectedPassportIdSet,
  togglePassport,
  passportDetailHref,
  persistNavigationContext,
  page,
  isFetching,
}: Pick<
  PassportGroupController,
  | "error"
  | "isLoading"
  | "submissionsView"
  | "groupDetails"
  | "data"
  | "setSearch"
  | "setDebouncedSearch"
  | "setSubmissionFilter"
  | "setSortBy"
  | "setSortOrder"
  | "setPage"
  | "viewMode"
  | "filteredPassports"
  | "canEditImages"
  | "includeDeleted"
  | "imageRevisions"
  | "setImageEditor"
  | "debouncedSearch"
  | "selectedPassportIdSet"
  | "togglePassport"
  | "passportDetailHref"
  | "persistNavigationContext"
  | "page"
  | "isFetching"
>) {
  return (
    <>
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load passport submissions for this group.
        </div>
      )}
      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : error ? null : (submissionsView?.group_total ?? 0) === 0 ? (
        <EmptyState
          icon={<UploadCloud className="h-5 w-5" />}
          title={groupDetails?.import_only ? "Your group is ready for Excel import" : "Drop passport here"}
          description={groupDetails?.import_only ? "Choose Import Excel above to add your final passenger list to this group." : "Share this group link with clients or upload a passport through the client page. Submitted passports will appear here."}
        />
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No passports match these filters"
          description="Adjust the search or submission filter to find more submissions."
          action={{
            label: "Reset Filters",
            onClick: () => {
              setSearch("");
              setDebouncedSearch("");
              setSubmissionFilter("all");
              setSortBy("name");
              setSortOrder("asc");
              setPage(1);
            },
          }}
        />
      ) : viewMode === "docs" ? (
        <PassportDocumentMatrix
          passports={filteredPassports}
          canEdit={canEditImages && !includeDeleted}
          revisions={imageRevisions}
          onEdit={(submissionId, imageType, label, returnFocusTarget) => {
            setImageEditor({
              submissionId,
              imageType,
              label,
              returnFocusTarget,
            });
          }}
        />
      ) : (
        <PassportGroupRosterTable
            filteredPassports={filteredPassports}
            debouncedSearch={debouncedSearch}
            selectedPassportIdSet={selectedPassportIdSet}
            togglePassport={togglePassport}
            passportDetailHref={passportDetailHref}
            persistNavigationContext={persistNavigationContext}
          />
      )}
      {submissionsView && submissionsView.total > 0 && (
        <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-slate-600">
            Showing {submissionsView.items.length.toLocaleString()} of{" "}
            {submissionsView.total.toLocaleString()} matching submissions
            {submissionsView.cluster_boundaries_preserved
              ? " · duplicate sets stay together"
              : " · large duplicate sets continue across pages"}
            {submissionsView.duplicate_clusters?.filter((cluster) => cluster.first_page !== cluster.last_page).map((cluster) => (
              <span key={cluster.cluster_id} className="block text-xs text-amber-900">
                Duplicate set: {cluster.visible_member_ids.length} of {cluster.matching_members} matching members on this page · pages {cluster.first_page}–{cluster.last_page}
              </span>
            ))}
          </p>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={page <= 1 || isFetching}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </Button>
            <span className="min-w-24 text-center text-sm font-medium text-slate-700">
              Page {submissionsView.page} of{" "}
              {Math.max(1, submissionsView.total_pages)}
            </span>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={page >= submissionsView.total_pages || isFetching}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
