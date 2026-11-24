"use client";

import { ChevronDown, ChevronUp, UsersRound } from "lucide-react";
import { Button, Card, CardContent } from "@/components/ui";
import type { RoomingPassengerHotelAllocationProps } from "../types/rooming-passenger-selection";
import { useRoomingPassengerSelection } from "../hooks/use-rooming-passenger-selection";
import { ROOMING_NOT_PROVIDED_KEY } from "./rooming-roster-grouping";
import { RosterGroupSection } from "./rooming-roster-group";
import { PassengerTable } from "./rooming-roster-table";
import { RoomingRosterFilters } from "./rooming-roster-filters";
import { RoomingSelectionActions } from "./rooming-selection-actions";

export { normalizeRoomingGender } from "./rooming-roster-table";

export function RoomingPassengerHotelAllocation(props: RoomingPassengerHotelAllocationProps) {
  const { workspace, activeHotel } = props;
  const selection = useRoomingPassengerSelection(props);
  const { isExpanded, setIsExpanded, visiblePassengers, validSelectedPassengerIds,
    groupByFieldKey, fieldValuesByPassenger, passengerGroups, selected,
    expandedGroupKeys, pending, toggleGroupExpanded, setGroupSelected,
    togglePassenger, groupingValuesReady } = selection;

  return (
    <Card>
      <CardContent className="p-0">
        <div
          className={`px-4 py-5 sm:px-6 ${
            isExpanded ? "border-b border-slate-200" : ""
          }`}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                  <UsersRound className="h-4 w-4" aria-hidden="true" />
                </span>
                <div>
                  <h2 className="font-semibold text-slate-950">
                    1. Choose who stays at each hotel
                  </h2>
                  <p className="mt-0.5 text-sm text-slate-600">
                    Every group passenger is shown. Assigning someone here
                    automatically moves them out of their previous hotel.
                  </p>
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
                <span className="rounded-full bg-slate-100 px-3 py-1.5 text-slate-700">
                  {visiblePassengers.length} visible
                </span>
                <span className="rounded-full bg-blue-100 px-3 py-1.5 text-blue-800">
                  {validSelectedPassengerIds.length} selected
                </span>
                <span className="rounded-full bg-emerald-100 px-3 py-1.5 text-emerald-800">
                  {activeHotel.selected_passenger_count} at this hotel
                </span>
              </div>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={() => setIsExpanded((current) => !current)}
                aria-expanded={isExpanded}
                aria-controls="rooming-passenger-list"
              >
                {isExpanded ? (
                  <ChevronUp className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <ChevronDown className="h-4 w-4" aria-hidden="true" />
                )}
                {isExpanded ? "Hide passenger list" : "Show passenger list"}
              </Button>
            </div>
          </div>
        </div>

        {isExpanded && (
          <div id="rooming-passenger-list">
            <div className="space-y-4 border-b border-slate-200 bg-slate-50/70 p-4 sm:p-5">
              <RoomingRosterFilters selection={selection} groupingFields={props.groupingFields} groupingFieldsLoading={props.groupingFieldsLoading} groupingFieldsError={props.groupingFieldsError} />
              <RoomingSelectionActions selection={selection} workspace={workspace} activeHotel={activeHotel} isAssigning={props.isAssigning} isUpdatingVip={props.isUpdatingVip} />
            </div>

            <div className="p-4 sm:p-5">
              {groupByFieldKey && fieldValuesByPassenger ? (
                <div className="space-y-3">
                  {passengerGroups.map((group, groupIndex) => {
                    const groupPassengerIds = group.passengers.map(
                      (passenger) => passenger.passenger_id,
                    );
                    const selectedCount = groupPassengerIds.filter(
                      (passengerId) => selected.has(passengerId),
                    ).length;
                    const isGroupExpanded = expandedGroupKeys.has(group.key);
                    return (
                      <RosterGroupSection
                        key={group.key}
                        contentId={`rooming-roster-group-${groupIndex}`}
                        label={group.label}
                        passengerCount={group.passengers.length}
                        selectedCount={selectedCount}
                        isMissing={group.key === ROOMING_NOT_PROVIDED_KEY}
                        expanded={isGroupExpanded}
                        passengers={group.passengers}
                        activeHotelId={activeHotel.id}
                        selected={selected}
                        disabled={pending}
                        onToggleExpanded={() => toggleGroupExpanded(group.key)}
                        onToggleGroup={(shouldSelect) =>
                          setGroupSelected(groupPassengerIds, shouldSelect)
                        }
                        onTogglePassenger={togglePassenger}
                      />
                    );
                  })}
                </div>
              ) : !groupByFieldKey ? (
                <PassengerTable
                  caption="Rooming passenger roster"
                  passengers={visiblePassengers}
                  activeHotelId={activeHotel.id}
                  selected={selected}
                  disabled={pending}
                  onTogglePassenger={togglePassenger}
                />
              ) : null}
              {groupingValuesReady && visiblePassengers.length === 0 && (
                <div className="px-5 py-12 text-center text-sm text-slate-500">
                  No passengers match the current search and filter.
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
