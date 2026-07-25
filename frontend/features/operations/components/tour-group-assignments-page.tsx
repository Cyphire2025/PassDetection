"use client";

import Link from "next/link";
import { Activity, ArrowRight, ListChecks, QrCode } from "lucide-react";
import { Badge, Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useAssignTourGroupCoordinators, useTourCoordinators, useTourGroups } from "../hooks/use-operations";
import { CoordinatorMultiSelect, getTourGroupTotals, TourEmptyState, TourMetric } from "./tour-operations-ui";
import type { TourGroup } from "../api/operations.api";
import { PASSENGER_ASSIGNMENT_COMPATIBILITY_UI_ENABLED } from "../config/tour-operations-flags";

export function TourGroupAssignmentsPage() {
  const { data: coordinators = [], isLoading: coordinatorsLoading, error: coordinatorsError } = useTourCoordinators();
  const { data: groups = [], isLoading: groupsLoading, error: groupsError } = useTourGroups();
  const assignGroup = useAssignTourGroupCoordinators();
  const loading = coordinatorsLoading || groupsLoading;
  const totals = getTourGroupTotals(groups);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tour Ops"
        description="Assign coordinators to groups. Every assigned coordinator can scan the full submitted roster."
      />

      {(coordinatorsError || groupsError) && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Group assignment data could not be loaded.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {loading ? (
          Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-[90px] rounded-xl" />)
        ) : (
          <>
            <TourMetric label="Groups" value={totals.groups} />
            <TourMetric label="Coordinators" value={coordinators.length} />
            <TourMetric
              label="Unassigned"
              value={totals.unassignedGroups}
              tone={totals.unassignedGroups > 0 ? "warning" : "default"}
            />
          </>
        )}
      </div>

      <Card className="overflow-visible">
        <CardContent className="overflow-visible p-0">
          <div className="flex items-center justify-between border-b border-slate-200 p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                <ListChecks className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">Groups</h2>
                <p className="text-sm text-slate-500">Choose every coordinator who should scan this group.</p>
              </div>
            </div>
            <Badge variant="secondary">{groups.length}</Badge>
          </div>

          {loading ? (
            <div className="space-y-3 p-5">
              {Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-20 rounded-lg" />)}
            </div>
          ) : groups.length === 0 ? (
            <div className="p-5">
              <TourEmptyState>No groups available for tour operations.</TourEmptyState>
            </div>
          ) : (
            <div className="divide-y divide-slate-100 overflow-visible">
              {groups.map((group) => (
                <GroupAssignmentRow
                  key={group.id}
                  group={group}
                  coordinatorOptions={coordinators}
                  disabled={assignGroup.isPending}
                  onChange={(coordinatorIds) => assignGroup.mutate({ groupId: group.id, coordinatorIds })}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function GroupAssignmentRow({
  group,
  coordinatorOptions,
  disabled,
  onChange,
}: {
  group: TourGroup;
  coordinatorOptions: Parameters<typeof CoordinatorMultiSelect>[0]["coordinators"];
  disabled: boolean;
  onChange: (coordinatorIds: string[]) => void;
}) {
  const selectedCoordinatorIds = group.coordinators.map((coordinator) => coordinator.coordinator_id);
  return (
    <div className="grid gap-4 p-5 xl:grid-cols-[minmax(220px,1.2fr)_minmax(180px,0.8fr)_minmax(280px,1fr)_auto] xl:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-slate-900">{group.name}</h3>
          <Badge variant={group.status === "active" ? "success" : "outline"}>{group.status}</Badge>
          {group.coordinators.length === 0 && <Badge variant="warning">No coordinator</Badge>}
        </div>
        <p className="mt-1 truncate text-sm text-slate-500">
          {[group.destination, group.travel_date].filter(Boolean).join(" | ") || "No trip details"}
        </p>
      </div>

      <div className="text-sm">
        <div>
          <p className="text-xs font-medium uppercase text-slate-400">People</p>
          <p className="mt-1 font-semibold text-slate-900">{group.passenger_count}</p>
        </div>
      </div>

      <CoordinatorMultiSelect
        coordinators={coordinatorOptions}
        selectedIds={selectedCoordinatorIds}
        disabled={disabled}
        onToggle={(coordinatorId, checked) => {
          const next = checked
            ? Array.from(new Set([...selectedCoordinatorIds, coordinatorId]))
            : selectedCoordinatorIds.filter((id) => id !== coordinatorId);
          onChange(next);
        }}
      />

      <div className="flex flex-wrap gap-2 xl:justify-end">
        {/* Compatibility-only entry point retained for rollback. */}
        {PASSENGER_ASSIGNMENT_COMPATIBILITY_UI_ENABLED && (
          <Link
            href={ROUTES.dashboard.tourOperationsGroup(group.id) as never}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            Open Group
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        )}
        <Link
          href={ROUTES.dashboard.tourOperationsGroupAttendance(group.id) as never}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 text-sm font-medium text-blue-700 shadow-sm transition hover:bg-blue-100"
        >
          Attendance
          <Activity className="h-4 w-4" aria-hidden="true" />
        </Link>
        <Link
          href={ROUTES.dashboard.tourOperationsGroupQrCodes(group.id) as never}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          QR Codes
          <QrCode className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}
