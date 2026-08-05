"use client";

import { useDeferredValue, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  FileStack,
  FolderKanban,
  FolderOpen,
  Search,
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
import { Skeleton } from "@/components/ui/skeleton";
import { ROUTES } from "@/constants/routes";
import { useDocumentGroups } from "../hooks/use-document-distribution";

export function DocumentGroupList() {
  const { data: groups = [], isLoading, error } = useDocumentGroups();
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);

  const summary = useMemo(
    () => groups.reduce(
      (totals, group) => ({
        passengers: totals.passengers + group.total_passengers,
        active: totals.active + (group.group_status === "active" ? 1 : 0),
        dated: totals.dated + (group.travel_date ? 1 : 0),
      }),
      { passengers: 0, active: 0, dated: 0 },
    ),
    [groups],
  );

  const filteredGroups = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    if (!normalized) return groups;
    return groups.filter((group) =>
      `${group.group_name} ${group.destination ?? ""}`
        .toLocaleLowerCase()
        .includes(normalized),
    );
  }, [deferredQuery, groups]);

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        eyebrow="Passenger document delivery"
        title="Document Distribution"
        description="Choose a group, upload reviewed visas or tickets, verify every passenger match, and keep delivery readiness visible before anything is sent."
        icon={FileStack}
        accent="cyan"
        context={(
          <>
            <WorkspaceHeaderContext icon={FolderKanban}>
              {groups.length.toLocaleString()} groups
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={UsersRound}>
              {summary.passengers.toLocaleString()} passengers
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <IntentPrefetchLink
            href={ROUTES.dashboard.documents}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/15"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Document Hub
          </IntentPrefetchLink>
        )}
      />

      {error && (
        <WorkspaceErrorNotice>
          Distribution groups could not be refreshed. Return to the Document Hub or try this view again.
        </WorkspaceErrorNotice>
      )}

      <WorkspaceSummaryStrip label="Document distribution portfolio">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Groups"
              value={groups.length.toLocaleString()}
              helper="in scope"
              icon={FolderKanban}
            />
            <WorkspaceSummaryItem
              label="Active"
              value={summary.active.toLocaleString()}
              helper="available now"
              icon={CheckCircle2}
              tone="success"
            />
            <WorkspaceSummaryItem
              label="Passengers"
              value={summary.passengers.toLocaleString()}
              helper="delivery roster"
              icon={UsersRound}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Travel date set"
              value={summary.dated.toLocaleString()}
              helper="groups"
              icon={CalendarDays}
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="distribution-groups-heading"
      >
        <div className="border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Group selection
          </p>
          <h2 id="distribution-groups-heading" className="mt-0.5 font-semibold text-slate-950">
            Open a document workspace
          </h2>
        </div>

        <WorkspaceToolbar
          query={query}
          onQueryChange={setQuery}
          searchLabel="Search document distribution groups"
          placeholder="Search by group or destination"
          resultLabel={`${filteredGroups.length.toLocaleString()} groups`}
        />

        {isLoading ? (
          <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-44 rounded-xl" />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <WorkspaceEmptyState
            title="No groups are ready for distribution"
            description="Create an active group and add passengers first. Its document workspace will then appear here."
          />
        ) : filteredGroups.length === 0 ? (
          <WorkspaceEmptyState
            filtered
            title="No distribution groups match this search"
            description="Search by the group name or destination, or clear the search to return to every available workspace."
          />
        ) : (
          <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
            {filteredGroups.map((group) => (
              <article
                key={group.group_id}
                className="flex min-w-0 flex-col rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-300 hover:shadow-sm"
                style={{ contentVisibility: "auto", containIntrinsicSize: "0 190px" }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate font-semibold text-slate-950">{group.group_name}</h3>
                    <p className="mt-1 flex items-center gap-1.5 truncate text-sm text-slate-500">
                      <Search className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      {group.destination || "Destination not set"}
                    </p>
                  </div>
                  <Badge variant={group.group_status === "active" ? "secondary" : "outline"} dot>
                    {group.group_status}
                  </Badge>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-3 border-y border-slate-100 py-3">
                  <div>
                    <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Passengers</dt>
                    <dd className="mt-1 font-semibold tabular-nums text-slate-900">
                      {group.total_passengers.toLocaleString()}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Travel/Departure</dt>
                    <dd className="mt-1 truncate font-medium text-slate-800">
                      {group.travel_date || "Not set"}
                    </dd>
                  </div>
                </dl>

                <IntentPrefetchLink
                  href={ROUTES.dashboard.documentGroup(group.group_id)}
                  className="mt-4 inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 transition hover:border-blue-300 hover:bg-blue-50 hover:text-blue-800"
                >
                  <FolderOpen className="h-4 w-4" aria-hidden="true" />
                  Open Documents
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </IntentPrefetchLink>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
