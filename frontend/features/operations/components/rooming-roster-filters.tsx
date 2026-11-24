"use client";

import { Search } from "lucide-react";
import { Input } from "@/components/ui";
import type { RoomingPassengerSelection } from "../hooks/use-rooming-passenger-selection";
import type { RoomingPassengerHotelAllocationProps, RosterFilter } from "../types/rooming-passenger-selection";

const FILTER_OPTIONS: Array<{ value: RosterFilter; label: string }> = [
  { value: "all", label: "All group passengers" },
  { value: "this-hotel", label: "Staying at this hotel" },
  { value: "unassigned", label: "Not assigned to a hotel" },
  { value: "other-hotel", label: "Staying at another hotel" },
];

export function RoomingRosterFilters({ selection, groupingFields, groupingFieldsLoading, groupingFieldsError }: {
  selection: RoomingPassengerSelection;
} & Pick<RoomingPassengerHotelAllocationProps, "groupingFields" | "groupingFieldsLoading" | "groupingFieldsError">) {
  const { search, setSearch, filter, setFilter, pending, groupByFieldKey, setGroupByFieldKey,
    groupValueFilter, setGroupValueFilter, setExpandedGroupKeys, groupValueOptions,
    sortDirection, setSortDirection, rosterFieldValues } = selection;
  return (
    <>
      <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_220px]">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
          placeholder="Search passenger, phone, email, family, or hotel"
          aria-label="Search rooming passengers"
          disabled={pending}
        />
        <label className="sr-only" htmlFor="rooming-roster-filter">
          Filter rooming passengers
        </label>
        <select
          id="rooming-roster-filter"
          value={filter}
          onChange={(event) =>
            setFilter(event.target.value as RosterFilter)
          }
          disabled={pending}
          className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
        >
          {FILTER_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <label className="block text-sm font-medium text-slate-700">
          Group by imported field
          <select
            value={groupByFieldKey ?? ""}
            onChange={(event) => {
              setGroupByFieldKey(event.target.value || null);
              setGroupValueFilter("all");
              setExpandedGroupKeys(new Set());
            }}
            disabled={
              pending || groupingFieldsLoading || groupingFieldsError
            }
            className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
          >
            <option value="">No grouping</option>
            {groupingFields
              .filter((field) => field.groupable)
              .map((field) => (
                <option key={field.key} value={field.key}>
                  {field.label}
                </option>
              ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Filter grouped value
          <select
            value={groupValueFilter}
            onChange={(event) =>
              setGroupValueFilter(event.target.value)
            }
            disabled={
              pending ||
              !groupByFieldKey ||
              rosterFieldValues.isLoading ||
              Boolean(rosterFieldValues.error)
            }
            className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
          >
            <option value="all">All values</option>
            {groupValueOptions.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label} ({option.count})
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Passenger sort
          <select
            value={sortDirection}
            onChange={(event) =>
              setSortDirection(event.target.value as "asc" | "desc")
            }
            disabled={pending}
            className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
          >
            <option value="asc">A to Z</option>
            <option value="desc">Z to A</option>
          </select>
        </label>
      </div>

      {groupingFieldsError && (
        <div
          role="alert"
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
        >
          Imported grouping fields could not be loaded. Passenger
          assignment remains available without grouping.
        </div>
      )}
      {groupByFieldKey && rosterFieldValues.isLoading && (
        <div role="status" className="text-sm text-slate-500">
          Loading authorized values for the selected field...
        </div>
      )}
      {groupByFieldKey && rosterFieldValues.error && (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Values for this grouping field could not be loaded. Choose a
          different field or try again.
        </div>
      )}
    </>
  );
}
