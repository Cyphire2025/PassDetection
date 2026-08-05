"use client";

import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BedDouble,
  Building2,
  CalendarDays,
  Compass,
  Hotel,
  MapPin,
  UsersRound,
} from "lucide-react";
import { Badge, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { useTourGroups } from "../hooks/use-operations";
import {
  OperationsEmptyState,
  OperationsErrorNotice,
  OperationsPageHeader,
  OperationsSummaryItem,
  OperationsSummaryStrip,
  OperationsToolbar,
} from "./operations-workspace-ui";

export function RoomingGroupsPage() {
  const { data: groups = [], isLoading, error } = useTourGroups();
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const normalizedQuery = deferredQuery.trim().toLocaleLowerCase();
  const visibleGroups = useMemo(
    () => groups.filter((group) => (
      !normalizedQuery
      || [group.name, group.destination, group.travel_date]
        .some((value) => value?.toLocaleLowerCase().includes(normalizedQuery))
    )),
    [groups, normalizedQuery],
  );
  const passengerTotal = useMemo(
    () => groups.reduce((total, group) => total + group.passenger_count, 0),
    [groups],
  );
  const destinationCount = useMemo(
    () => new Set(groups.map((group) => group.destination?.trim()).filter(Boolean)).size,
    [groups],
  );
  const datedGroups = useMemo(
    () => groups.filter((group) => Boolean(group.travel_date)).length,
    [groups],
  );

  return (
    <div className="flex flex-col gap-5">
      <OperationsPageHeader
        eyebrow="Hotel planning workspace"
        title="Rooming Lists"
        description="Build hotel stays, place every passenger, apply rooming priorities, and hand the final plan to the hotel desk."
        icon={BedDouble}
        context={(
          <>
            <HeaderContext icon={Building2}>{groups.length} active groups</HeaderContext>
            <HeaderContext icon={UsersRound}>{passengerTotal.toLocaleString()} passengers in scope</HeaderContext>
          </>
        )}
      />

      {error && (
        <OperationsErrorNotice>
          Rooming groups could not be refreshed. Previously loaded groups remain available where possible.
        </OperationsErrorNotice>
      )}

      <OperationsSummaryStrip label="Rooming portfolio summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />)
        ) : (
          <>
            <OperationsSummaryItem label="Active groups" value={groups.length} helper="ready to plan" icon={BedDouble} />
            <OperationsSummaryItem label="Passengers" value={passengerTotal.toLocaleString()} helper="confirmed roster" icon={UsersRound} />
            <OperationsSummaryItem label="Destinations" value={destinationCount} helper="travel locations" icon={Compass} />
            <OperationsSummaryItem label="Travel dates" value={datedGroups} helper="scheduled groups" icon={CalendarDays} />
          </>
        )}
      </OperationsSummaryStrip>

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-labelledby="rooming-portfolio-heading">
        <div className="flex flex-col gap-1 border-b border-slate-200 px-4 py-4 sm:px-5">
          <h2 id="rooming-portfolio-heading" className="font-semibold text-slate-950">Group rooming portfolio</h2>
          <p className="text-sm text-slate-500">Open a group to manage its hotels, passenger allocation, room plan, and check-in desk.</p>
        </div>
        <OperationsToolbar
          query={query}
          onQueryChange={setQuery}
          searchLabel="Search rooming groups"
          placeholder="Search group, destination, or travel date"
          resultLabel={isLoading ? "Loading groups" : `${visibleGroups.length} of ${groups.length} groups`}
        />

        {isLoading ? (
          <div className="grid gap-px bg-slate-100 md:grid-cols-2">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-36 rounded-none bg-white" />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <OperationsEmptyState
            title="No active groups are ready for rooming"
            description="Rooming workspaces appear here when an active group has been created and its roster is available."
          />
        ) : visibleGroups.length === 0 ? (
          <OperationsEmptyState
            filtered
            title="No rooming groups match this search"
            description="Try a group name, destination, or travel date, or clear the search to restore the full portfolio."
            action={(
              <button type="button" onClick={() => setQuery("")} className="text-sm font-semibold text-blue-700 hover:text-blue-900">
                Clear search
              </button>
            )}
          />
        ) : (
          <div className="grid gap-px bg-slate-100 md:grid-cols-2">
            {visibleGroups.map((group) => (
              <Link
                key={group.id}
                href={ROUTES.dashboard.roomingGroup(group.id) as never}
                className="group relative min-w-0 bg-white px-5 py-5 transition-colors hover:bg-blue-50/45 focus-visible:z-10"
              >
                <span className="absolute inset-y-0 left-0 w-1 bg-transparent transition-colors group-hover:bg-blue-600" aria-hidden="true" />
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate font-semibold text-slate-950">{group.name}</h3>
                      <Badge variant={group.status === "active" ? "success" : "outline"} dot>
                        {group.status}
                      </Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-600">
                      <GroupMetadata icon={UsersRound}>{group.passenger_count.toLocaleString()} passengers</GroupMetadata>
                      <GroupMetadata icon={MapPin}>{group.destination || "Destination not set"}</GroupMetadata>
                      <GroupMetadata icon={CalendarDays}>{formatTravelDate(group.travel_date)}</GroupMetadata>
                    </div>
                  </div>
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500 transition group-hover:border-blue-200 group-hover:bg-white group-hover:text-blue-700">
                    <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                  </span>
                </div>
                <div className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3 text-xs font-semibold text-blue-700">
                  <Hotel className="h-3.5 w-3.5" aria-hidden="true" />
                  Open hotel planning workspace
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function HeaderContext({ icon: Icon, children }: { icon: typeof Building2; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200">
      <Icon className="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />
      {children}
    </span>
  );
}

function GroupMetadata({ icon: Icon, children }: { icon: typeof UsersRound; children: React.ReactNode }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
      <span className="truncate">{children}</span>
    </span>
  );
}

function formatTravelDate(value: string | null) {
  if (!value) return "Travel date not set";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}
