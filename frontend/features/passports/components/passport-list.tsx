"use client";

import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { WorkspaceEmptyState } from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ROUTES } from "@/constants/routes";
import { Link2 } from "lucide-react";
import { usePassportList } from "./use-passport-list";
import { PassportListOverview } from "./passport-list-overview";
import { PassportListFilters } from "./passport-list-filters";
import { PassportListExportControls } from "./passport-list-export-controls";
import { PassportListTable } from "./passport-list-table";

export function PassportList() {
  const {
    data,
    isLoading,
    isFetching,
    error,
    refetch,
    exportSelected,
    selectedGroups,
    setSelectedGroups,
    statusFilter,
    setStatusFilter,
    reviewFilter,
    setReviewFilter,
    destinationFilter,
    setDestinationFilter,
    isExportDialogOpen,
    setIsExportDialogOpen,
    selectedGroupSet,
    summary,
    filteredGroups,
    toggleGroup,
    resetFilters,
  } = usePassportList();
  return (
    <div className="flex flex-col gap-5">
      <PassportListOverview
        data={data}
        summary={summary}
        isLoading={isLoading}
        error={error}
        isFetching={isFetching}
        refetch={refetch}
      />

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="all-groups-heading"
      >
        <div className="border-b border-slate-200 px-4 py-3.5 sm:px-5">

          <h2 id="all-groups-heading" className="mt-0.5 font-semibold text-slate-950">
            Group passport workspaces
          </h2>
        </div>

        <PassportListFilters
          data={data}
          filteredGroups={filteredGroups}
          destinationFilter={destinationFilter}
          setDestinationFilter={setDestinationFilter}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          reviewFilter={reviewFilter}
          setReviewFilter={setReviewFilter}
        />

        <PassportListExportControls
          selectedGroups={selectedGroups}
          setSelectedGroups={setSelectedGroups}
          exportSelected={exportSelected}
          isExportDialogOpen={isExportDialogOpen}
          setIsExportDialogOpen={setIsExportDialogOpen}
        />

        {isLoading ? (
          <div className="grid gap-3 p-4 sm:p-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-20 w-full rounded-xl" />
            ))}
          </div>
        ) : !data ? (
          <p className="px-5 py-8 text-sm text-slate-600">Group workspaces are unavailable. Retry loading the groups to continue.</p>
        ) : data.length === 0 ? (
          <WorkspaceEmptyState
            title="Start the first passport group"
            description="Create a Group Link to collect passport details. Submitted records will appear here."
            action={(
              <IntentPrefetchLink
                href={ROUTES.dashboard.uploadLinks}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-700"
              >
                Create a Group Link
                <Link2 className="h-4 w-4" aria-hidden="true" />
              </IntentPrefetchLink>
            )}
          />
        ) : filteredGroups.length === 0 ? (
          <WorkspaceEmptyState
            filtered
            title="No groups match this working view"
            description="No groups match the selected filters. Reset the filters to view all groups."
            action={(
              <Button type="button" variant="secondary" onClick={resetFilters}>
                Reset filters
              </Button>
            )}
          />
        ) : (
          <PassportListTable filteredGroups={filteredGroups} selectedGroupSet={selectedGroupSet} toggleGroup={toggleGroup} />
        )}
      </section>


    </div>
  );
}
