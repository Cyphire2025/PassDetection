"use client";

import { useState } from "react";
import { ArrowLeft, ArrowRight, CalendarDays, CheckCircle2, MapPin, Plane, UsersRound } from "lucide-react";
import { IntentPrefetchLink } from "@/components/shared/intent-prefetch-link";
import { WorkspaceEmptyState, WorkspaceErrorNotice, WorkspacePageHeader, WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { useTrackerGroups } from "../hooks";
import { formatTravelDate, trackerError } from "../model";
import type { TrackerGroup } from "../types";
import { TrackerPagination } from "./tracker-pagination";

export function TrackerGroupList() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const query = useDebounce(search.trim(), 250);
  const groups = useTrackerGroups(query, page);
  const lastPage = Math.max(1, Math.ceil((groups.data?.total ?? 0) / 24));
  if (groups.data && page > lastPage) setPage(lastPage);
  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="Visa / Flight Tracker"
        description="Choose a travel group to track visa applications and flight bookings for every passenger, including link submissions and imported records."
        icon={Plane}
        actions={<IntentPrefetchLink href={ROUTES.dashboard.documents} className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-700"><ArrowLeft className="h-4 w-4" />Documents</IntentPrefetchLink>}
      />
      <div className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-900">
        <CheckCircle2 className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>Tap a passenger to mark them, update an entire filtered list, or upload Excel to match a batch. Visa and flight progress are tracked separately.</p>
      </div>
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-label="Travel groups">
        <WorkspaceToolbar query={search} onQueryChange={(value) => { setSearch(value); setPage(1); }} searchLabel="Search travel groups" placeholder="Search group or destination" resultLabel={groups.isFetching ? "Refreshing groups…" : `${(groups.data?.total ?? 0).toLocaleString()} groups`} />
        {groups.error ? (
          <div className="space-y-3 p-4"><WorkspaceErrorNotice>{trackerError(groups.error)}</WorkspaceErrorNotice><Button variant="secondary" onClick={() => void groups.refetch()}>Retry loading groups</Button></div>
        ) : groups.isLoading ? (
          <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-64 rounded-xl" />)}</div>
        ) : !groups.data?.groups.length ? (
          <WorkspaceEmptyState filtered={Boolean(query)} title={query ? "No groups match your search" : "No travel groups yet"} description={query ? "Try another group name or destination." : "Create a group and add passengers using its upload link or import. Every passenger in the group will appear here."} />
        ) : (
          <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">{groups.data.groups.map((group) => <TrackerGroupCard key={group.id} group={group} />)}</div>
        )}
        {groups.data && <TrackerPagination page={page} pageSize={groups.data.page_size} total={groups.data.total} busy={groups.isFetching} onChange={setPage} />}
      </section>
    </div>
  );
}

function TrackerGroupCard({ group }: { group: TrackerGroup }) {
  return (
    <article className="flex min-w-0 flex-col rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-300 hover:shadow-sm" style={{ contentVisibility: "auto", containIntrinsicSize: "0 270px" }}>
      <div className="flex items-start justify-between gap-3"><h2 className="min-w-0 break-words text-base font-semibold text-slate-950">{group.name}</h2><span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] capitalize text-slate-500">{group.status}</span></div>
      <p className="mt-2 flex items-center gap-2 text-sm text-slate-500"><MapPin className="h-3.5 w-3.5 shrink-0" />{group.destination || "Destination not set"}</p>
      <p className="mt-1 flex items-center gap-2 text-xs text-slate-500"><CalendarDays className="h-3.5 w-3.5 shrink-0" />{formatTravelDate(group.travel_date)}</p>
      <p className="mt-4 flex items-center gap-2 text-sm font-medium text-slate-700"><UsersRound className="h-4 w-4 text-slate-400" />{group.total.toLocaleString()} passengers</p>
      <div className="mt-3 space-y-3"><GroupProgress label="Visa applied" value={group.visa_marked} total={group.total} /><GroupProgress label="Flight booked" value={group.flight_marked} total={group.total} /></div>
      <IntentPrefetchLink href={ROUTES.dashboard.travelTrackerGroup(group.id)} className="mt-5 inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-semibold text-white transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2">Open tracker<ArrowRight className="h-4 w-4" /></IntentPrefetchLink>
    </article>
  );
}

function GroupProgress({ label, value, total }: { label: string; value: number; total: number }) {
  return <div><div className="mb-1 flex items-center justify-between text-xs"><span className="font-medium text-slate-600">{label}</span><span className="tabular-nums text-slate-500">{value} / {total}</span></div><div role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={total || 1} className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${total ? (value / total) * 100 : 0}%` }} /></div></div>;
}
