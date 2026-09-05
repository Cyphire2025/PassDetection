"use client";

import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  ClipboardCheck,
  MapPin,
  QrCode,
  ShieldCheck,
  UserCog,
  UserRoundCheck,
  UsersRound,
} from "lucide-react";
import { Badge, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { cn } from "@/lib/utils/cn";
import { useAssignTourGroupCoordinators, useTourCoordinators, useTourGroups } from "../hooks/use-operations";
import { CoordinatorMultiSelect, getTourGroupTotals } from "./tour-operations-ui";
import type { TourGroup } from "../api/operations.api";
import { PASSENGER_ASSIGNMENT_COMPATIBILITY_UI_ENABLED } from "../config/tour-operations-flags";
import {
  OperationsEmptyState,
  OperationsErrorNotice,
  OperationsPageHeader,
  OperationsSummaryItem,
  OperationsSummaryStrip,
  OperationsToolbar,
} from "./operations-workspace-ui";

type AssignmentFilter = "all" | "unassigned" | "assigned";

export function TourGroupAssignmentsPage() {
  const { data: coordinators = [], isLoading: coordinatorsLoading, error: coordinatorsError } = useTourCoordinators();
  const { data: groups = [], isLoading: groupsLoading, error: groupsError } = useTourGroups();
  const assignGroup = useAssignTourGroupCoordinators();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<AssignmentFilter>("all");
  const deferredQuery = useDeferredValue(query);
  const loading = coordinatorsLoading || groupsLoading;
  const totals = getTourGroupTotals(groups);
  const visibleGroups = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    return groups.filter((group) => {
      if (filter === "unassigned" && group.coordinators.length > 0) return false;
      if (filter === "assigned" && group.coordinators.length === 0) return false;
      if (!normalized) return true;
      return [
        group.name,
        group.destination,
        group.travel_date,
        ...group.coordinators.flatMap((coordinator) => [coordinator.full_name, coordinator.email]),
      ].some((value) => value?.toLocaleLowerCase().includes(normalized));
    });
  }, [deferredQuery, filter, groups]);
  const coveredGroups = totals.groups - totals.unassignedGroups;

  return (
    <div className="flex flex-col gap-5">
      <OperationsPageHeader
        title="Tour Ops"
        description="Set group coverage, then move directly into attendance monitoring or passenger QR distribution. Every assigned coordinator can scan the full submitted roster."
        icon={ClipboardCheck}
        context={(
          <>
            <HeaderContext icon={ShieldCheck}>{coveredGroups} groups covered</HeaderContext>
            {totals.unassignedGroups > 0 ? (
              <HeaderContext icon={AlertTriangle} attention>{totals.unassignedGroups} need assignment</HeaderContext>
            ) : (
              <HeaderContext icon={CheckCircle2}>All active groups covered</HeaderContext>
            )}
          </>
        )}
        actions={(
          <Link
            href={ROUTES.dashboard.tourOperationsCoordinators as never}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3.5 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <UserCog className="h-4 w-4 text-sky-200" aria-hidden="true" />
            Manage coordinators
          </Link>
        )}
      />

      {(coordinatorsError || groupsError) && (
        <OperationsErrorNotice>
          Assignment data could not be refreshed. Previously loaded coverage remains visible where available.
        </OperationsErrorNotice>
      )}
      {assignGroup.error && (
        <OperationsErrorNotice>
          Coordinator coverage could not be saved. The previous group assignment remains unchanged.
        </OperationsErrorNotice>
      )}

      <OperationsSummaryStrip label="Tour operations summary">
        {loading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />)
        ) : (
          <>
            <OperationsSummaryItem label="Active groups" value={totals.groups} helper="tour workspaces" icon={ClipboardCheck} />
            <OperationsSummaryItem label="Passengers" value={totals.passengers.toLocaleString()} helper="submitted roster" icon={UsersRound} />
            <OperationsSummaryItem label="Coordinators" value={coordinators.length} helper="field accounts" icon={UserRoundCheck} />
            <OperationsSummaryItem
              label="Needs coverage"
              value={totals.unassignedGroups}
              helper={totals.unassignedGroups === 0 ? "all covered" : "assign before travel"}
              icon={totals.unassignedGroups === 0 ? CheckCircle2 : AlertTriangle}
              tone={totals.unassignedGroups === 0 ? "success" : "attention"}
            />
          </>
        )}
      </OperationsSummaryStrip>

      <section className="overflow-visible rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="tour-coverage-heading">
        <div className="flex flex-col gap-1 border-b border-slate-200 px-4 py-4 sm:px-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 id="tour-coverage-heading" className="font-semibold text-slate-950">Group coverage</h2>
              <p className="mt-0.5 text-sm text-slate-500">Assign coverage and launch the group&apos;s live operational tools.</p>
            </div>
            <Badge variant="outline">{groups.length} groups</Badge>
          </div>
        </div>

        <OperationsToolbar
          query={query}
          onQueryChange={setQuery}
          searchLabel="Search Tour Ops groups"
          placeholder="Search group, destination, date, or coordinator"
          resultLabel={loading ? "Loading coverage" : `${visibleGroups.length} of ${groups.length} groups`}
        >
          <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1" aria-label="Filter group coverage">
            {([
              ["all", "All"],
              ["unassigned", `Needs coverage (${totals.unassignedGroups})`],
              ["assigned", `Covered (${coveredGroups})`],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                aria-pressed={filter === value}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors",
                  filter === value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </OperationsToolbar>

        {loading ? (
          <div className="space-y-px bg-slate-100">
            {Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-28 rounded-none bg-white" />)}
          </div>
        ) : groups.length === 0 ? (
          <OperationsEmptyState
            title="No groups are available for Tour Ops"
            description="Active groups with submitted passenger rosters will appear here for coordinator coverage."
          />
        ) : visibleGroups.length === 0 ? (
          <OperationsEmptyState
            filtered
            title="No groups match this view"
            description="Clear the search or switch coverage filters to see the full operational list."
            action={(
              <button type="button" onClick={() => { setQuery(""); setFilter("all"); }} className="text-sm font-semibold text-blue-700 hover:text-blue-900">
                Reset view
              </button>
            )}
          />
        ) : (
          <div className="divide-y divide-slate-100 overflow-visible">
            {visibleGroups.map((group) => (
              <GroupAssignmentRow
                key={group.id}
                group={group}
                coordinatorOptions={coordinators}
                disabled={assignGroup.isPending && assignGroup.variables?.groupId === group.id}
                onChange={(coordinatorIds) => assignGroup.mutate({ groupId: group.id, coordinatorIds })}
              />
            ))}
          </div>
        )}
      </section>
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
  const hasCoverage = selectedCoordinatorIds.length > 0;
  return (
    <article className={cn("relative grid gap-4 px-4 py-4 sm:px-5 xl:grid-cols-[minmax(240px,1.2fr)_minmax(240px,0.9fr)_auto] xl:items-center", !hasCoverage && "bg-amber-50/35")}>
      <span className={cn("absolute inset-y-0 left-0 w-1", hasCoverage ? "bg-emerald-500" : "bg-amber-400")} aria-hidden="true" />
      <div className="min-w-0 pl-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-slate-950">{group.name}</h3>
          <Badge variant={group.status === "active" ? "success" : "outline"} dot>{group.status}</Badge>
          {!hasCoverage && <Badge variant="warning">Coverage needed</Badge>}
          {disabled && <Badge variant="secondary">Saving</Badge>}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-500">
          <RowMetadata icon={UsersRound}>{group.passenger_count.toLocaleString()} passengers</RowMetadata>
          <RowMetadata icon={MapPin}>{group.destination || "Destination not set"}</RowMetadata>
          <RowMetadata icon={CalendarDays}>{formatTripDate(group.travel_date)}</RowMetadata>
        </div>
      </div>

      <div className="min-w-0">
        <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          Coordinator coverage
        </label>
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
      </div>

      <div className="flex flex-wrap gap-2 xl:justify-end">
        {PASSENGER_ASSIGNMENT_COMPATIBILITY_UI_ENABLED && (
          <Link
            href={ROUTES.dashboard.tourOperationsGroup(group.id) as never}
            className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            Open group <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        )}
        <Link
          href={ROUTES.dashboard.tourOperationsGroupAttendance(group.id) as never}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 text-sm font-semibold text-blue-800 shadow-sm transition hover:border-blue-300 hover:bg-blue-100"
        >
          <Activity className="h-4 w-4" aria-hidden="true" />
          Attendance
        </Link>
        <Link
          href={ROUTES.dashboard.tourOperationsGroupQrCodes(group.id) as never}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          <QrCode className="h-4 w-4" aria-hidden="true" />
          QR codes
        </Link>
      </div>
    </article>
  );
}

function HeaderContext({ icon: Icon, children, attention = false }: { icon: typeof ShieldCheck; children: React.ReactNode; attention?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium", attention ? "border-amber-400/40 bg-amber-400/10 text-amber-100" : "border-white/15 bg-white/10 text-slate-200")}>
      <Icon className={cn("h-3.5 w-3.5", attention ? "text-amber-300" : "text-sky-300")} aria-hidden="true" />
      {children}
    </span>
  );
}

function RowMetadata({ icon: Icon, children }: { icon: typeof UsersRound; children: React.ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
      <span className="truncate">{children}</span>
    </span>
  );
}

function formatTripDate(value: string | null) {
  if (!value) return "Travel date not set";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}
