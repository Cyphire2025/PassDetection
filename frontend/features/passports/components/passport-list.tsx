"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Download, Eye, FileText, FolderOpen, Link2 } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import type { PassportGroupSummary } from "@/types/passport.types";
import type {
  PassportGroupSummaryReviewFilter,
  PassportGroupSummaryStatus,
} from "../api/passports.api";
import {
  useExportSelectedGroups,
  usePassportGroupSummaries,
} from "../hooks/use-passports";

const PassportSelectedGroupsExportDialog = dynamic(() =>
  import("./passport-selected-groups-export-dialog").then(
    (module) => module.PassportSelectedGroupsExportDialog,
  ),
);

const GROUPS_PAGE_SIZE = 50;

export function PassportList() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] =
    useState<"all" | PassportGroupSummaryStatus>("all");
  const [reviewFilter, setReviewFilter] =
    useState<PassportGroupSummaryReviewFilter>("all");
  const [destinationFilter, setDestinationFilter] = useState("");
  const [debouncedDestinationFilter, setDebouncedDestinationFilter] = useState("");
  const { data, isLoading, isFetching, error } = usePassportGroupSummaries({
    page,
    page_size: GROUPS_PAGE_SIZE,
    ...(statusFilter !== "all" ? { group_status: statusFilter } : {}),
    ...(reviewFilter !== "all" ? { review_filter: reviewFilter } : {}),
    ...(debouncedDestinationFilter
      ? { destination: debouncedDestinationFilter }
      : {}),
  });
  const exportSelected = useExportSelectedGroups();
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);

  const groups = data?.items ?? [];
  const hasActiveFilters =
    statusFilter !== "all"
    || reviewFilter !== "all"
    || Boolean(debouncedDestinationFilter);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedDestinationFilter(destinationFilter.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timeoutId);
  }, [destinationFilter]);

  const toggleGroup = (groupId: string) => {
    setSelectedGroups((current) =>
      current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId],
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Passport Groups"
        description="Open a client group to review the passport submissions uploaded inside it."
      />

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <select
          value={statusFilter}
          onChange={(event) => {
            setStatusFilter(
              event.target.value as "all" | PassportGroupSummaryStatus,
            );
            setPage(1);
          }}
          className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="all">All statuses</option>
          <option value="active">Active</option>
          <option value="closed">Closed</option>
          <option value="archived">Archived</option>
        </select>
        <select
          value={reviewFilter}
          onChange={(event) => {
            setReviewFilter(
              event.target.value as PassportGroupSummaryReviewFilter,
            );
            setPage(1);
          }}
          className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="all">All groups</option>
          <option value="needs_review">Needs review</option>
          <option value="has_passports">Has passports</option>
          <option value="confirmed_only">Fully confirmed</option>
        </select>
        <Input
          value={destinationFilter}
          onChange={(event) => setDestinationFilter(event.target.value)}
          placeholder="Filter destination"
          className="h-9 w-64"
        />
        <Button
          type="button"
          variant="secondary"
          disabled={selectedGroups.length === 0}
          isLoading={exportSelected.isPending}
          onClick={() => {
            exportSelected.reset();
            setIsExportDialogOpen(true);
          }}
        >
          <Download className="h-4 w-4" />
          Export Selected ({selectedGroups.length})
        </Button>
        {selectedGroups.length > 0 && (
          <Button type="button" variant="ghost" onClick={() => setSelectedGroups([])}>
            Clear selection
          </Button>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Failed to load passport submissions. Check that the backend is running and reachable.
        </div>
      )}

      {isLoading ? (
        <div className="grid gap-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : data && data.total === 0 && !hasActiveFilters ? (
        <EmptyState
          icon={<Link2 className="h-5 w-5" />}
          title="Create an upload link"
          description="Start by creating a group link. Client passport submissions will appear here after they submit verified details."
          action={{ label: "Create Upload Link", onClick: () => { window.location.href = ROUTES.dashboard.uploadLinks; } }}
        />
      ) : groups.length === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No groups match these filters"
          description="Adjust the status, review, or destination filters to see more passport groups."
          action={{
            label: "Reset Filters",
            onClick: () => {
              setStatusFilter("all");
              setReviewFilter("all");
              setDestinationFilter("");
              setDebouncedDestinationFilter("");
              setPage(1);
            },
          }}
        />
      ) : (
        <>
          <div className="grid gap-4 lg:hidden">
            {groups.map((group) => (
              <PassportGroupMobileCard
                key={group.group_id}
                group={group}
                selected={selectedGroups.includes(group.group_id)}
                onToggle={() => toggleGroup(group.group_id)}
              />
            ))}
          </div>

          <Card className="hidden lg:block">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                      <th className="px-6 py-4">Group</th>
                      <th className="px-6 py-4">Trip</th>
                      <th className="px-6 py-4">Status</th>
                      <th className="px-6 py-4">Passports</th>
                      <th className="px-6 py-4">Needs Review</th>
                      <th className="px-6 py-4">Latest Upload</th>
                      <th className="px-6 py-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {groups.map((group) => (
                      <tr
                        key={group.group_id}
                        className="cursor-pointer hover:bg-slate-50/60"
                        onClick={() => toggleGroup(group.group_id)}
                      >
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={selectedGroups.includes(group.group_id)}
                              onChange={() => toggleGroup(group.group_id)}
                              onClick={(event) => event.stopPropagation()}
                              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            />
                            <div>
                              <div className="font-semibold text-slate-900">{group.group_name}</div>
                              <div className="mt-1 text-xs text-slate-500">{group.confirmed_count} confirmed, {group.failed_count} failed</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="font-medium text-slate-800">{group.destination || "Not set"}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            {group.travel_date || "No Travel/Departure date"}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <GroupStatusBadge status={group.group_status} />
                        </td>
                        <td className="px-6 py-4 text-slate-700">{group.total_passports}</td>
                        <td className="px-6 py-4">
                          <span className="font-medium text-slate-800">{group.pending_review_count}</span>
                        </td>
                        <td className="px-6 py-4 text-slate-500">
                          {group.total_passports > 0 ? formatDateTime(group.latest_submission_at) : "No uploads yet"}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <Link href={passportGroupHref(group) as never} onClick={(event) => event.stopPropagation()}>
                            <Button variant="outline" size="sm" className="gap-2">
                              <Eye className="h-4 w-4" />
                              Open Group
                            </Button>
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
          {data && data.total > 0 && (
            <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm sm:flex-row sm:items-center sm:justify-between">
              <span>
                Showing {(data.page - 1) * data.page_size + 1}
                {"–"}
                {Math.min(data.page * data.page_size, data.total)} of {data.total} groups
              </span>
              <div className="flex items-center gap-2">
                {isFetching && !isLoading && (
                  <span className="mr-2 text-xs text-slate-400">Refreshing…</span>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={data.page <= 1 || isFetching}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                >
                  Previous
                </Button>
                <span className="min-w-24 text-center">
                  Page {data.page} of {Math.max(data.total_pages, 1)}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={data.page >= data.total_pages || isFetching}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

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
    <Card className={selected ? "rounded-2xl border-blue-300 bg-blue-50/40" : "rounded-2xl"} onClick={onToggle}>
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex gap-3">
            <input
              type="checkbox"
              checked={selected}
              onChange={onToggle}
              onClick={(event) => event.stopPropagation()}
              className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            />
            <div>
              <h3 className="text-base font-semibold text-slate-900">{group.group_name}</h3>
              <p className="mt-1 text-xs text-slate-500">
                {group.total_passports > 0 ? formatDateTime(group.latest_submission_at) : "No uploads yet"}
              </p>
            </div>
          </div>
          <GroupStatusBadge status={group.group_status} />
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoPair label="Passports" value={String(group.total_passports)} />
          <InfoPair label="Destination" value={group.destination || "Not set"} />
          <InfoPair label="Needs Review" value={String(group.pending_review_count)} />
          <InfoPair label="Confirmed" value={String(group.confirmed_count)} />
          <InfoPair label="Failed" value={String(group.failed_count)} />
        </div>

        <Link href={passportGroupHref(group) as never} className="block" onClick={(event) => event.stopPropagation()}>
          <Button variant="outline" className="w-full gap-2">
            <FolderOpen className="h-4 w-4" />
            Open Group
          </Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function InfoPair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 font-medium text-slate-800">{value}</div>
    </div>
  );
}

function passportGroupHref(group: PassportGroupSummary) {
  const pathname = ROUTES.dashboard.passportGroup(group.group_id);
  return group.group_status === "archived"
    ? `${pathname}?include_archived=1`
    : pathname;
}

function GroupStatusBadge({ status }: { status: string }) {
  const variant = status === "active" ? "secondary" : status === "closed" ? "outline" : "default";
  return (
    <Badge variant={variant} dot>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  );
}
