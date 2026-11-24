import { CircleHelp, Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui";
import { MATCH_FILTERS } from "./group-whatsapp-tracking-model";
import type { GroupWhatsAppTrackingModel } from "./use-group-whatsapp-tracking";

type Props = Pick<
  GroupWhatsAppTrackingModel,
  | "groupId"
  | "matchFilter"
  | "setMatchFilter"
  | "broadcastFilter"
  | "setBroadcastFilter"
  | "setMatchPage"
  | "links"
  | "exportTracking"
  | "matchesQuery"
>;

export function GroupWhatsAppTrackingFilters({
  groupId,
  matchFilter,
  setMatchFilter,
  broadcastFilter,
  setBroadcastFilter,
  setMatchPage,
  links,
  exportTracking,
  matchesQuery,
}: Props) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div
        className="flex flex-wrap gap-2"
        aria-label="Filter broadcast recipients by submission status"
      >
        {MATCH_FILTERS.map((filter) => (
          <div
            key={filter.value}
            className="group/filter relative"
          >
            <button
              type="button"
              aria-pressed={matchFilter === filter.value}
              aria-describedby={
                filter.description
                  ? `match-filter-help-${filter.value}`
                  : undefined
              }
              onClick={() => {
                setMatchFilter(filter.value);
                setMatchPage(1);
              }}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                matchFilter === filter.value
                  ? "border-blue-600 bg-blue-600 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
              }`}
            >
              {filter.label}
              {filter.description && (
                <CircleHelp
                  className="h-3.5 w-3.5"
                  aria-hidden="true"
                />
              )}
            </button>
            {filter.description && (
              <span
                id={`match-filter-help-${filter.value}`}
                role="tooltip"
                className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-64 -translate-x-1/2 rounded-lg bg-slate-900 px-3 py-2 text-left text-xs font-medium leading-5 text-white shadow-lg group-hover/filter:block group-focus-within/filter:block"
              >
                {filter.description}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {(links?.broadcasts.length ?? 0) > 1 && (
          <>
            <label
              htmlFor="whatsapp-broadcast-filter"
              className="text-xs font-semibold text-slate-600"
            >
              Broadcast
            </label>
            <select
              id="whatsapp-broadcast-filter"
              value={broadcastFilter}
              onChange={(event) => {
                setBroadcastFilter(event.target.value);
                setMatchPage(1);
              }}
              className="h-9 max-w-72 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            >
              <option value="all">All linked broadcasts</option>
              {links?.broadcasts.map((broadcast) => (
                <option key={broadcast.id} value={broadcast.id}>
                  {broadcast.name}
                </option>
              ))}
            </select>
          </>
        )}
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={
            exportTracking.isPending
            || matchesQuery.isLoading
            || !matchesQuery.data?.total
          }
          aria-label={`Export ${
            MATCH_FILTERS.find(
              (filter) => filter.value === matchFilter,
            )?.label ?? "current tracking view"
          } to Excel`}
          onClick={() => {
            exportTracking.reset();
            exportTracking.mutate({
              groupId,
              status: matchFilter,
              broadcastId: broadcastFilter === "all"
                ? undefined
                : broadcastFilter,
            });
          }}
        >
          {exportTracking.isPending ? (
            <Loader2
              className="h-4 w-4 animate-spin"
              aria-hidden="true"
            />
          ) : (
            <Download className="h-4 w-4" aria-hidden="true" />
          )}
          {exportTracking.isPending ? "Exporting" : "Export Excel"}
        </Button>
      </div>
    </div>
  );
}
