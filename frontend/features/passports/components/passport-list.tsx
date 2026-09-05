"use client";

import {
  useDeferredValue,
  useMemo,
  useState,
} from "react";
import dynamic from "next/dynamic";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  FolderKanban,
  FolderOpen,
  Link2,
  MapPin,
  UsersRound,
} from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import {
  WorkspaceEmptyState,
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
  WorkspaceToolbar,
} from "@/components/shared/workspace-ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import type { PassportGroupSummary } from "@/types/passport.types";
import { useExportSelectedGroups, usePassportGroups } from "../hooks/use-passports";

const loadSelectedGroupsExportDialog = () =>
  import("./passport-selected-groups-export-dialog");

const PassportSelectedGroupsExportDialog = dynamic(
  () => import("./passport-selected-groups-export-dialog").then(
    (module) => module.PassportSelectedGroupsExportDialog,
  ),
  { loading: () => null },
);

export function PassportList() {
  const { data, isLoading, error } = usePassportGroups();
  const exportSelected = useExportSelectedGroups();
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [reviewFilter, setReviewFilter] = useState("all");
  const [destinationFilter, setDestinationFilter] = useState("");
  const deferredDestinationFilter = useDeferredValue(destinationFilter);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);

  const selectedGroupSet = useMemo(() => new Set(selectedGroups), [selectedGroups]);
  const summary = useMemo(() => {
    const groups = data ?? [];
    return groups.reduce(
      (totals, group) => ({
        passports: totals.passports + group.total_passports,
        review: totals.review + group.pending_review_count,
        confirmedGroups:
          totals.confirmedGroups
          + (group.total_passports > 0 && group.confirmed_count === group.total_passports ? 1 : 0),
      }),
      { passports: 0, review: 0, confirmedGroups: 0 },
    );
  }, [data]);

  const filteredGroups = useMemo(() => {
    const destinationQuery = deferredDestinationFilter.trim().toLocaleLowerCase();
    return (data ?? []).filter((group) => {
      if (statusFilter !== "all" && group.group_status !== statusFilter) return false;
      if (reviewFilter === "needs_review" && group.pending_review_count === 0) return false;
      if (reviewFilter === "has_passports" && group.total_passports === 0) return false;
      if (
        reviewFilter === "confirmed_only"
        && (group.total_passports === 0 || group.confirmed_count !== group.total_passports)
      ) {
        return false;
      }
      if (
        destinationQuery
        && !(group.destination ?? "").toLocaleLowerCase().includes(destinationQuery)
      ) {
        return false;
      }
      return true;
    });
  }, [data, deferredDestinationFilter, reviewFilter, statusFilter]);

  const toggleGroup = (groupId: string) => {
    setSelectedGroups((current) =>
      current.includes(groupId)
        ? current.filter((id) => id !== groupId)
        : [...current, groupId],
    );
  };

  const resetFilters = () => {
    setStatusFilter("all");
    setReviewFilter("all");
    setDestinationFilter("");
  };

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="All Groups"
        description="Review passport submissions and confirm passenger records by group."
        icon={FolderKanban}
        accent="sky"
        context={(
          <>
            <WorkspaceHeaderContext icon={FolderOpen}>
              {(data?.length ?? 0).toLocaleString()} groups
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={UsersRound}>
              {summary.passports.toLocaleString()} passport records
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.uploadLinks}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-white px-4 text-sm font-semibold text-[#123f73] shadow-sm transition hover:bg-sky-50 active:bg-sky-100"
          >
            Manage Group Links
            <Link2 className="h-4 w-4" aria-hidden="true" />
          </IntentPrefetchLink>
        )}
      />

      {error && (
        <WorkspaceErrorNotice>
          All Groups could not be refreshed. Your current filters and navigation remain available while you retry.
        </WorkspaceErrorNotice>
      )}

      <WorkspaceSummaryStrip label="All Groups readiness summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Active portfolio"
              value={(data?.length ?? 0).toLocaleString()}
              helper="groups in scope"
              icon={FolderKanban}
            />
            <WorkspaceSummaryItem
              label="Passport records"
              value={summary.passports.toLocaleString()}
              helper="submitted"
              icon={FileText}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Needs review"
              value={summary.review.toLocaleString()}
              helper="records"
              icon={AlertTriangle}
              tone={summary.review > 0 ? "attention" : "success"}
            />
            <WorkspaceSummaryItem
              label="Fully confirmed"
              value={summary.confirmedGroups.toLocaleString()}
              helper="groups"
              icon={CheckCircle2}
              tone="success"
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="all-groups-heading"
      >
        <div className="border-b border-slate-200 px-4 py-3.5 sm:px-5">

          <h2 id="all-groups-heading" className="mt-0.5 font-semibold text-slate-950">
            Group passport workspaces
          </h2>
        </div>

        <WorkspaceToolbar
          query={destinationFilter}
          onQueryChange={setDestinationFilter}
          searchLabel="Filter groups by destination"
          placeholder="Filter by destination"
          resultLabel={`${filteredGroups.length.toLocaleString()} of ${(data?.length ?? 0).toLocaleString()} groups`}
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

        {selectedGroups.length > 0 && (
          <div className="flex flex-col gap-3 border-b border-blue-100 bg-blue-50/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
            <p className="text-sm font-medium text-blue-900" aria-live="polite">
              {selectedGroups.length.toLocaleString()} group{selectedGroups.length === 1 ? "" : "s"} selected for export
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                isLoading={exportSelected.isPending}
                onMouseEnter={() => void loadSelectedGroupsExportDialog()}
                onFocus={() => void loadSelectedGroupsExportDialog()}
                onPointerDown={() => void loadSelectedGroupsExportDialog()}
                onClick={() => {
                  exportSelected.reset();
                  setIsExportDialogOpen(true);
                }}
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                Export Selected
              </Button>
              <Button type="button" variant="ghost" onClick={() => setSelectedGroups([])}>
                Clear selection
              </Button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="grid gap-3 p-4 sm:p-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-20 w-full rounded-xl" />
            ))}
          </div>
        ) : !data || data.length === 0 ? (
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
          <>
            <div className="grid gap-3 p-4 lg:hidden">
              {filteredGroups.map((group) => (
                <PassportGroupMobileCard
                  key={group.group_id}
                  group={group}
                  selected={selectedGroupSet.has(group.group_id)}
                  onToggle={() => toggleGroup(group.group_id)}
                />
              ))}
            </div>

            <div className="hidden overflow-x-auto lg:block">
              <table className="w-full min-w-[980px] text-left text-sm">
                <caption className="sr-only">Group passport workspace readiness</caption>
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50/70 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                    <th scope="col" className="px-5 py-3">Group</th>
                    <th scope="col" className="px-5 py-3">Trip</th>
                    <th scope="col" className="px-5 py-3">Status</th>
                    <th scope="col" className="px-5 py-3">Passports</th>
                    <th scope="col" className="px-5 py-3">Needs review</th>
                    <th scope="col" className="px-5 py-3">Latest intake</th>
                    <th scope="col" className="px-5 py-3 text-right">Workspace</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredGroups.map((group) => {
                    const selected = selectedGroupSet.has(group.group_id);
                    return (
                      <tr
                        key={group.group_id}
                        className={selected
                          ? "cursor-pointer bg-blue-50/65 outline-none transition-colors hover:bg-blue-50"
                          : "cursor-pointer outline-none transition-colors hover:bg-slate-50/70"
                        }
                        onClick={() => toggleGroup(group.group_id)}
                      >
                        <td className="px-5 py-4">
                          <div className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={() => toggleGroup(group.group_id)}
                              onClick={(event) => event.stopPropagation()}
                              aria-label={`Select ${group.group_name}`}
                              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            />
                            <div className="min-w-0">
                              <div className="font-semibold text-slate-950">{group.group_name}</div>
                              <div className="mt-1 text-xs text-slate-500">
                                {group.confirmed_count.toLocaleString()} confirmed · {group.failed_count.toLocaleString()} failed
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-4">
                          <div className="font-medium text-slate-800">{group.destination || "Destination not set"}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            {group.travel_date || "No Travel/Departure date"}
                          </div>
                        </td>
                        <td className="px-5 py-4">
                          <GroupStatusBadge status={group.group_status} />
                        </td>
                        <td className="px-5 py-4 font-medium tabular-nums text-slate-800">
                          {group.total_passports.toLocaleString()}
                        </td>
                        <td className="px-5 py-4">
                          <span className={group.pending_review_count > 0 ? "font-semibold tabular-nums text-amber-700" : "font-medium tabular-nums text-emerald-700"}>
                            {group.pending_review_count.toLocaleString()}
                          </span>
                        </td>
                        <td className="px-5 py-4 text-slate-600">
                          {group.total_passports > 0
                            ? formatDateTime(group.latest_submission_at)
                            : "No uploads yet"}
                        </td>
                        <td className="px-5 py-4 text-right">
                          <IntentPrefetchLink
                            href={ROUTES.dashboard.passportGroup(group.group_id)}
                            onClick={(event) => event.stopPropagation()}
                            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
                          >
                            <Eye className="h-4 w-4" aria-hidden="true" />
                            Open Group
                          </IntentPrefetchLink>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {isExportDialogOpen && selectedGroups.length > 0 && (
        <PassportSelectedGroupsExportDialog
          groupIds={selectedGroups}
          isDownloading={exportSelected.isPending}
          hasDownloadError={exportSelected.isError}
          onClose={() => {
            if (!exportSelected.isPending) {
              setIsExportDialogOpen(false);
              exportSelected.reset();
            }
          }}
          onDownload={async ({ supplementalFields, groupByField }) => {
            await exportSelected.mutateAsync({
              groupIds: selectedGroups,
              supplementalFields,
              groupByField,
            });
            setIsExportDialogOpen(false);
          }}
        />
      )}
    </div>
  );
}

function PassportGroupMobileCard({
  group,
  selected,
  onToggle,
}: {
  group: PassportGroupSummary;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <Card
      className={selected ? "rounded-xl border-blue-300 bg-blue-50/50" : "rounded-xl"}
      onClick={onToggle}
      style={{ contentVisibility: "auto", containIntrinsicSize: "0 270px" }}
    >
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 gap-3">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              onClick={(event) => event.stopPropagation()}
              aria-label={`Select ${group.group_name}`}
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <div className="min-w-0">
              <h3 className="truncate text-base font-semibold text-slate-950">{group.group_name}</h3>
              <p className="mt-1 text-xs text-slate-500">
                {group.total_passports > 0
                  ? formatDateTime(group.latest_submission_at)
                  : "No uploads yet"}
              </p>
            </div>
          </div>
          <GroupStatusBadge status={group.group_status} />
        </div>

        <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-y border-slate-100 py-3 text-sm">
          <InfoPair label="Passports" value={group.total_passports.toLocaleString()} />
          <InfoPair label="Destination" value={group.destination || "Not set"} icon={MapPin} />
          <InfoPair label="Needs review" value={group.pending_review_count.toLocaleString()} />
          <InfoPair label="Confirmed" value={group.confirmed_count.toLocaleString()} />
        </div>

        <IntentPrefetchLink
          href={ROUTES.dashboard.passportGroup(group.group_id)}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white text-sm font-semibold text-slate-700 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
          onClick={(event) => event.stopPropagation()}
        >
          <FolderOpen className="h-4 w-4" aria-hidden="true" />
          Open Group
        </IntentPrefetchLink>
      </CardContent>
    </Card>
  );
}

function InfoPair({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon?: typeof MapPin;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {Icon && <Icon className="h-3 w-3" aria-hidden="true" />}
        {label}
      </div>
      <div className="mt-1 truncate font-medium text-slate-800">{value}</div>
    </div>
  );
}

function GroupStatusBadge({ status }: { status: string }) {
  const variant = status === "active" ? "secondary" : status === "closed" ? "outline" : "default";
  return (
    <Badge variant={variant} dot>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}
