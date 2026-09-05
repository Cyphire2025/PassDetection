"use client";

import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import {
  ChevronDown,
  ChevronUp,
  Crown,
  Hotel,
  Search,
  UserCheck,
  UsersRound,
} from "lucide-react";
import {
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  RoomingHotel,
  RoomingPassenger,
  RoomingPriorityField,
  RoomingWorkspace,
} from "../api/operations.api";
import { useRoomingRosterFieldValues } from "../hooks/use-operations";
import { roomingErrorMessage } from "./rooming-error-message";
import {
  groupRoomingRosterPassengers,
  ROOMING_NOT_PROVIDED_KEY,
  roomingRosterValueKey,
  roomingRosterValueOptions,
  sortRoomingRosterPassengers,
} from "./rooming-roster-grouping";

type RosterFilter = "all" | "this-hotel" | "unassigned" | "other-hotel";

interface RoomingPassengerHotelAllocationProps {
  workspace: RoomingWorkspace;
  activeHotel: RoomingHotel;
  isAssigning: boolean;
  isUpdatingVip: boolean;
  groupingFields: RoomingPriorityField[];
  groupingFieldsLoading: boolean;
  groupingFieldsError: boolean;
  onAssign: (passengerIds: string[], hotelId: string) => Promise<void>;
  onSetVip: (passengerIds: string[], isVip: boolean) => Promise<void>;
}

const FILTER_OPTIONS: Array<{ value: RosterFilter; label: string }> = [
  { value: "all", label: "All group passengers" },
  { value: "this-hotel", label: "Staying at this hotel" },
  { value: "unassigned", label: "Not assigned to a hotel" },
  { value: "other-hotel", label: "Staying at another hotel" },
];

export function RoomingPassengerHotelAllocation({
  workspace,
  activeHotel,
  isAssigning,
  isUpdatingVip,
  groupingFields,
  groupingFieldsLoading,
  groupingFieldsError,
  onAssign,
  onSetVip,
}: RoomingPassengerHotelAllocationProps) {
  const [selectedPassengerIds, setSelectedPassengerIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [targetHotelId, setTargetHotelId] = useState(activeHotel.id);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<RosterFilter>("all");
  const [firstCount, setFirstCount] = useState("50");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [groupByFieldKey, setGroupByFieldKey] = useState<string | null>(null);
  const [groupValueFilter, setGroupValueFilter] = useState("all");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const deferredSearch = useDeferredValue(search);
  const rosterFieldValues = useRoomingRosterFieldValues(
    workspace.group_id,
    groupByFieldKey,
  );

  const passengersById = useMemo(
    () =>
      new Map(
        workspace.passengers.map((passenger) => [
          passenger.passenger_id,
          passenger,
        ]),
      ),
    [workspace.passengers],
  );
  const validSelectedPassengerIds = useMemo(
    () =>
      Array.from(selectedPassengerIds).filter((passengerId) =>
        passengersById.has(passengerId),
      ),
    [passengersById, selectedPassengerIds],
  );

  const selected = useMemo(
    () => new Set(validSelectedPassengerIds),
    [validSelectedPassengerIds],
  );
  const selectedPassengers = useMemo(
    () =>
      validSelectedPassengerIds
        .map((passengerId) => passengersById.get(passengerId))
        .filter((passenger): passenger is RoomingPassenger =>
          Boolean(passenger),
        ),
    [passengersById, validSelectedPassengerIds],
  );
  const selectedAtActiveHotel = useMemo(
    () =>
      selectedPassengers.filter(
        (passenger) => passenger.selected_hotel_id === activeHotel.id,
      ),
    [activeHotel.id, selectedPassengers],
  );
  const statusFilteredPassengers = useMemo(() => {
    const query = deferredSearch.trim().toLocaleLowerCase();
    return workspace.passengers.filter((passenger) => {
      if (
        filter === "this-hotel" &&
        passenger.selected_hotel_id !== activeHotel.id
      ) {
        return false;
      }
      if (filter === "unassigned" && passenger.selected_hotel_id !== null) {
        return false;
      }
      if (
        filter === "other-hotel" &&
        (passenger.selected_hotel_id === null ||
          passenger.selected_hotel_id === activeHotel.id)
      ) {
        return false;
      }
      if (!query) return true;
      return [
        passenger.client_name,
        passenger.client_email,
        passenger.client_phone,
        passenger.selected_hotel_name,
        passenger.family_group_label,
      ].some((value) => value?.toLocaleLowerCase().includes(query));
    });
  }, [activeHotel.id, deferredSearch, filter, workspace.passengers]);
  const fieldValuesByPassenger = rosterFieldValues.data?.values_by_passenger;
  const groupingValuesReady =
    !groupByFieldKey || Boolean(fieldValuesByPassenger);
  const groupValueOptions = useMemo(
    () =>
      groupByFieldKey && fieldValuesByPassenger
        ? roomingRosterValueOptions(
            statusFilteredPassengers,
            fieldValuesByPassenger,
          )
        : [],
    [fieldValuesByPassenger, groupByFieldKey, statusFilteredPassengers],
  );
  const visiblePassengers = useMemo(() => {
    if (groupByFieldKey && !fieldValuesByPassenger) return [];
    const filtered =
      groupByFieldKey && fieldValuesByPassenger && groupValueFilter !== "all"
        ? statusFilteredPassengers.filter(
            (passenger) =>
              roomingRosterValueKey(
                fieldValuesByPassenger[passenger.passenger_id],
              ) === groupValueFilter,
          )
        : statusFilteredPassengers;
    return sortRoomingRosterPassengers(filtered, sortDirection);
  }, [
    fieldValuesByPassenger,
    groupByFieldKey,
    groupValueFilter,
    sortDirection,
    statusFilteredPassengers,
  ]);
  const passengerGroups = useMemo(
    () =>
      groupByFieldKey && fieldValuesByPassenger
        ? groupRoomingRosterPassengers(
            visiblePassengers,
            fieldValuesByPassenger,
            sortDirection,
          )
        : [
            {
              key: "all",
              label: "All passengers",
              passengers: visiblePassengers,
            },
          ],
    [fieldValuesByPassenger, groupByFieldKey, sortDirection, visiblePassengers],
  );

  const parsedFirstCount = Number.parseInt(firstCount, 10);
  const validFirstCount =
    Number.isFinite(parsedFirstCount) && parsedFirstCount > 0;
  const pending = isAssigning || isUpdatingVip;

  const selectVisible = () => {
    setSelectedPassengerIds(
      (current) =>
        new Set([
          ...current,
          ...visiblePassengers.map((passenger) => passenger.passenger_id),
        ]),
    );
  };
  const selectFirst = () => {
    if (!validFirstCount) return;
    setSelectedPassengerIds(
      (current) =>
        new Set([
          ...current,
          ...visiblePassengers
            .slice(0, Math.min(parsedFirstCount, visiblePassengers.length))
            .map((passenger) => passenger.passenger_id),
        ]),
    );
  };
  const togglePassenger = useCallback((passengerId: string) => {
    setSelectedPassengerIds((current) => {
      const next = new Set(current);
      if (next.has(passengerId)) next.delete(passengerId);
      else next.add(passengerId);
      return next;
    });
  }, []);
  const setGroupSelected = (
    groupPassengerIds: string[],
    shouldSelect: boolean,
  ) => {
    setSelectedPassengerIds((current) => {
      const next = new Set(current);
      for (const passengerId of groupPassengerIds) {
        if (shouldSelect) next.add(passengerId);
        else next.delete(passengerId);
      }
      return next;
    });
  };
  const toggleGroupExpanded = (groupKey: string) => {
    setExpandedGroupKeys((current) => {
      const next = new Set(current);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  };

  const effectiveTargetHotelId = workspace.hotels.some(
    (hotel) => hotel.id === targetHotelId,
  )
    ? targetHotelId
    : activeHotel.id;

  const assignSelected = async () => {
    if (validSelectedPassengerIds.length === 0 || !effectiveTargetHotelId)
      return;
    setActionError(null);
    setActionStatus(null);
    try {
      await onAssign(validSelectedPassengerIds, effectiveTargetHotelId);
      const targetHotel = workspace.hotels.find(
        (hotel) => hotel.id === effectiveTargetHotelId,
      );
      setActionStatus(
        `${validSelectedPassengerIds.length} passenger${
          validSelectedPassengerIds.length === 1 ? "" : "s"
        } assigned to ${targetHotel?.hotel_name ?? "the selected hotel"}.`,
      );
    } catch (error) {
      setActionError(
        roomingErrorMessage(
          error,
          "The selected passengers could not be assigned. Please try again.",
        ),
      );
    }
  };

  const setVip = async (isVip: boolean) => {
    if (selectedAtActiveHotel.length === 0) return;
    setActionError(null);
    setActionStatus(null);
    try {
      const ids = selectedAtActiveHotel.map(
        (passenger) => passenger.passenger_id,
      );
      await onSetVip(ids, isVip);
      setActionStatus(
        `${ids.length} passenger${ids.length === 1 ? "" : "s"} ${
          isVip ? "marked as VIP" : "removed from VIP"
        } for ${activeHotel.hotel_name}.`,
      );
    } catch (error) {
      setActionError(
        roomingErrorMessage(
          error,
          "VIP status could not be updated. Please try again.",
        ),
      );
    }
  };

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

              <div className="flex flex-wrap items-end gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={selectVisible}
                  disabled={pending || visiblePassengers.length === 0}
                >
                  Select visible
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    setSelectedPassengerIds(
                      new Set(
                        workspace.passengers.map(
                          (passenger) => passenger.passenger_id,
                        ),
                      ),
                    )
                  }
                  disabled={pending || workspace.passengers.length === 0}
                >
                  Select all group
                </Button>
                <div className="flex items-end gap-2">
                  <Input
                    id="rooming-select-first-count"
                    label="First passengers"
                    type="number"
                    min="1"
                    max={Math.max(1, visiblePassengers.length)}
                    inputMode="numeric"
                    value={firstCount}
                    onChange={(event) => setFirstCount(event.target.value)}
                    className="w-24"
                    disabled={pending}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={selectFirst}
                    disabled={
                      pending ||
                      !validFirstCount ||
                      visiblePassengers.length === 0
                    }
                  >
                    Select first
                  </Button>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setSelectedPassengerIds(new Set())}
                  disabled={pending || validSelectedPassengerIds.length === 0}
                >
                  Clear selection
                </Button>
              </div>

              <div className="grid gap-3 rounded-xl border border-slate-200 bg-white p-3 xl:grid-cols-[minmax(220px,1fr)_auto_auto] xl:items-end">
                <label className="block text-sm font-medium text-slate-700">
                  Assign selected passengers to
                  <select
                    value={effectiveTargetHotelId}
                    onChange={(event) => setTargetHotelId(event.target.value)}
                    disabled={pending}
                    className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
                  >
                    {workspace.hotels.map((hotel) => (
                      <option key={hotel.id} value={hotel.id}>
                        {hotel.hotel_name}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  type="button"
                  onClick={() => void assignSelected()}
                  isLoading={isAssigning}
                  disabled={
                    validSelectedPassengerIds.length === 0 || isUpdatingVip
                  }
                >
                  <Hotel className="h-4 w-4" aria-hidden="true" />
                  Assign selected
                </Button>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void setVip(true)}
                    isLoading={isUpdatingVip}
                    disabled={isAssigning || selectedAtActiveHotel.length === 0}
                    title={`Applies to selected passengers staying at ${activeHotel.hotel_name}`}
                  >
                    <Crown
                      className="h-4 w-4 text-amber-600"
                      aria-hidden="true"
                    />
                    Mark VIP ({selectedAtActiveHotel.length})
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void setVip(false)}
                    isLoading={isUpdatingVip}
                    disabled={isAssigning || selectedAtActiveHotel.length === 0}
                    title={`Applies to selected passengers staying at ${activeHotel.hotel_name}`}
                  >
                    Remove VIP
                  </Button>
                </div>
              </div>

              <p className="text-xs leading-5 text-slate-500">
                VIP actions apply only to selected passengers already staying at{" "}
                <strong className="font-semibold text-slate-700">
                  {activeHotel.hotel_name}
                </strong>
                . VIP passengers always receive a single room during auto
                allocation.
              </p>

              {actionError && (
                <div
                  role="alert"
                  className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
                >
                  {actionError}
                </div>
              )}
              {actionStatus && (
                <div
                  role="status"
                  className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
                >
                  {actionStatus}
                </div>
              )}
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

function RosterGroupSection({
  contentId,
  label,
  passengerCount,
  selectedCount,
  isMissing,
  expanded,
  passengers,
  activeHotelId,
  selected,
  disabled,
  onToggleExpanded,
  onToggleGroup,
  onTogglePassenger,
}: {
  contentId: string;
  label: string;
  passengerCount: number;
  selectedCount: number;
  isMissing: boolean;
  expanded: boolean;
  passengers: RoomingPassenger[];
  activeHotelId: string;
  selected: Set<string>;
  disabled: boolean;
  onToggleExpanded: () => void;
  onToggleGroup: (shouldSelect: boolean) => void;
  onTogglePassenger: (passengerId: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center gap-3 bg-slate-50 px-4 py-3">
        <GroupSelectionCheckbox
          label={`Select ${label}`}
          selectedCount={selectedCount}
          passengerCount={passengerCount}
          disabled={disabled}
          onChange={onToggleGroup}
        />
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-expanded={expanded}
          aria-controls={contentId}
          className="flex min-w-0 flex-1 items-center justify-between gap-3 text-left"
        >
          <span className="min-w-0">
            <span
              className={
                isMissing
                  ? "font-semibold text-amber-800"
                  : "font-semibold text-slate-900"
              }
            >
              {label}
            </span>
            <span className="ml-2 text-xs text-slate-500">
              {passengerCount} passenger{passengerCount === 1 ? "" : "s"}
              {selectedCount > 0 ? ` | ${selectedCount} selected` : ""}
            </span>
          </span>
          {expanded ? (
            <ChevronUp
              className="h-4 w-4 shrink-0 text-slate-500"
              aria-hidden="true"
            />
          ) : (
            <ChevronDown
              className="h-4 w-4 shrink-0 text-slate-500"
              aria-hidden="true"
            />
          )}
        </button>
        <button
          type="button"
          onClick={() => onToggleGroup(selectedCount !== passengerCount)}
          disabled={disabled || passengerCount === 0}
          className="shrink-0 rounded-md px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50"
        >
          {selectedCount === passengerCount ? "Clear group" : "Select group"}
        </button>
      </div>
      {expanded && (
        <div
          id={contentId}
          className="overflow-x-auto border-t border-slate-200"
        >
          <PassengerTable
            caption={`${label} passenger roster`}
            passengers={passengers}
            activeHotelId={activeHotelId}
            selected={selected}
            disabled={disabled}
            onTogglePassenger={onTogglePassenger}
          />
        </div>
      )}
    </section>
  );
}

function GroupSelectionCheckbox({
  label,
  selectedCount,
  passengerCount,
  disabled,
  onChange,
}: {
  label: string;
  selectedCount: number;
  passengerCount: number;
  disabled: boolean;
  onChange: (shouldSelect: boolean) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const checked = passengerCount > 0 && selectedCount === passengerCount;
  const indeterminate = selectedCount > 0 && selectedCount < passengerCount;
  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={inputRef}
      type="checkbox"
      checked={checked}
      onChange={() => onChange(!checked)}
      disabled={disabled || passengerCount === 0}
      aria-label={label}
      aria-checked={indeterminate ? "mixed" : checked}
      className="h-4 w-4 shrink-0 rounded border-slate-300 accent-blue-600"
    />
  );
}

function PassengerTable({
  caption,
  passengers,
  activeHotelId,
  selected,
  disabled,
  onTogglePassenger,
}: {
  caption: string;
  passengers: RoomingPassenger[];
  activeHotelId: string;
  selected: Set<string>;
  disabled: boolean;
  onTogglePassenger: (passengerId: string) => void;
}) {
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const pageCount = Math.max(1, Math.ceil(passengers.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pagePassengers = passengers.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="w-12 px-4 py-3">
              <span className="sr-only">Select passenger</span>
            </th>
            <th scope="col" className="px-3 py-3">
              Passenger
            </th>
            <th scope="col" className="px-3 py-3">
              Gender
            </th>
            <th scope="col" className="px-3 py-3">
              Current hotel
            </th>
            <th scope="col" className="px-4 py-3">
              Room rule
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {pagePassengers.map((passenger) => (
            <PassengerRow
              key={passenger.passenger_id}
              passenger={passenger}
              activeHotelId={activeHotelId}
              checked={selected.has(passenger.passenger_id)}
              disabled={disabled}
              onTogglePassenger={onTogglePassenger}
            />
          ))}
        </tbody>
      </table>
      {pageCount > 1 && (
        <div className="flex items-center justify-between gap-3 border-t border-slate-200 px-4 py-3">
          <p className="text-xs text-slate-500">
            Page {currentPage} of {pageCount} | {passengers.length} passengers |
            selections stay selected across pages
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={currentPage <= 1}
              onClick={() => setPage(currentPage - 1)}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={currentPage >= pageCount}
              onClick={() => setPage(currentPage + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

const PassengerRow = memo(function PassengerRow({
  passenger,
  activeHotelId,
  checked,
  disabled,
  onTogglePassenger,
}: {
  passenger: RoomingPassenger;
  activeHotelId: string;
  checked: boolean;
  disabled: boolean;
  onTogglePassenger: (passengerId: string) => void;
}) {
  const gender = normalizeRoomingGender(passenger.passport_sex);
  const isAtActiveHotel = passenger.selected_hotel_id === activeHotelId;

  return (
    <tr
      className={
        passenger.is_vip
          ? "bg-amber-50/70 hover:bg-amber-50"
          : checked
            ? "bg-blue-50/60 hover:bg-blue-50"
            : "hover:bg-slate-50/80"
      }
    >
      <td className="px-4 py-3 align-top">
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onTogglePassenger(passenger.passenger_id)}
          disabled={disabled}
          aria-label={`Select ${passenger.client_name}`}
          className="mt-1 h-4 w-4 rounded border-slate-300 accent-blue-600"
        />
      </td>
      <td className="px-3 py-3 align-top">
        <div className="font-semibold text-slate-900">
          {passenger.client_name}
        </div>
        <div className="mt-1 flex flex-wrap gap-1.5 text-xs text-slate-500">
          {passenger.family_group_label && (
            <span>{passenger.family_group_label}</span>
          )}
          {passenger.client_phone && <span>{passenger.client_phone}</span>}
        </div>
      </td>
      <td className="px-3 py-3 align-top">
        {gender ? (
          <Badge variant={gender === "Male" ? "secondary" : "success"}>
            {gender}
          </Badge>
        ) : (
          <Badge variant="destructive">Needs correction</Badge>
        )}
      </td>
      <td className="px-3 py-3 align-top">
        {passenger.selected_hotel_name ? (
          <Badge variant={isAtActiveHotel ? "success" : "outline"}>
            {passenger.selected_hotel_name}
          </Badge>
        ) : (
          <span className="text-slate-400">Not assigned</span>
        )}
      </td>
      <td className="px-4 py-3 align-top">
        {passenger.is_vip ? (
          <span className="inline-flex items-center gap-1.5 font-semibold text-amber-800">
            <Crown className="h-4 w-4" aria-hidden="true" />
            VIP - single room
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-slate-600">
            <UserCheck className="h-4 w-4" aria-hidden="true" />
            Same-gender twin
          </span>
        )}
      </td>
    </tr>
  );
});

export function normalizeRoomingGender(
  value: string | null | undefined,
): "Male" | "Female" | null {
  const normalized = value?.trim().toLocaleLowerCase();
  if (normalized === "m" || normalized === "male") return "Male";
  if (normalized === "f" || normalized === "female") return "Female";
  return null;
}
