"use client";

import { WorkspaceToolbar } from "@/components/shared/workspace-ui";
import type { PassportListModel } from "./use-passport-list";

type Props = Pick<
  PassportListModel,
  | "data"
  | "filteredGroups"
  | "destinationFilter"
  | "setDestinationFilter"
  | "statusFilter"
  | "setStatusFilter"
  | "reviewFilter"
  | "setReviewFilter"
>;


export function PassportListFilters({
  data,
  filteredGroups,
  destinationFilter,
  setDestinationFilter,
  statusFilter,
  setStatusFilter,
  reviewFilter,
  setReviewFilter,
}: Props) {
  return (
    <WorkspaceToolbar
      query={destinationFilter}
      onQueryChange={setDestinationFilter}
      searchLabel="Filter groups by destination"
      placeholder="Filter by destination"
      resultLabel={data ? `${filteredGroups.length.toLocaleString()} of ${data.length.toLocaleString()} groups` : "Group counts unavailable"}
    >
      <label className="sr-only" htmlFor="all-groups-status-filter">
        Filter by group status
      </label>
      <select
        id="all-groups-status-filter"
        value={statusFilter}
        onChange={(event) => setStatusFilter(event.target.value)}
        className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      >
        <option value="all">All statuses</option>
        <option value="active">Active</option>
        <option value="closed">Closed</option>
        <option value="archived">Archived</option>
      </select>
      <label className="sr-only" htmlFor="all-groups-review-filter">
        Filter by review readiness
      </label>
      <select
        id="all-groups-review-filter"
        value={reviewFilter}
        onChange={(event) => setReviewFilter(event.target.value)}
        className="h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      >
        <option value="all">All readiness</option>
        <option value="needs_review">Needs review</option>
        <option value="has_passports">Has passports</option>
        <option value="confirmed_only">Fully confirmed</option>
      </select>
    </WorkspaceToolbar>
  );
}
