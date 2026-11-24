"use client";

import { useCallback, useDeferredValue, useMemo, useState } from "react";
import type { RoomingPassenger } from "../api/operations.api";
import type { RoomingPassengerHotelAllocationProps, RosterFilter } from "../types/rooming-passenger-selection";
import { useRoomingRosterFieldValues } from "./use-operations";
import { roomingErrorMessage } from "../components/rooming-error-message";
import { groupRoomingRosterPassengers, roomingRosterValueKey, roomingRosterValueOptions, sortRoomingRosterPassengers } from "../components/rooming-roster-grouping";

export function useRoomingPassengerSelection({
  workspace,
  activeHotel,
  isAssigning,
  isUpdatingVip,
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

  return {
    selected, validSelectedPassengerIds, selectedAtActiveHotel,
    visiblePassengers, passengerGroups, fieldValuesByPassenger, groupingValuesReady, groupValueOptions,
    search, setSearch, filter, setFilter, firstCount, setFirstCount, validFirstCount,
    groupByFieldKey, setGroupByFieldKey, groupValueFilter, setGroupValueFilter,
    sortDirection, setSortDirection, expandedGroupKeys, setExpandedGroupKeys,
    isExpanded, setIsExpanded, actionError, actionStatus, pending, rosterFieldValues,
    setSelectedPassengerIds, selectVisible, selectFirst, togglePassenger,
    setGroupSelected, toggleGroupExpanded, effectiveTargetHotelId, setTargetHotelId,
    assignSelected, setVip,
  };
}

export type RoomingPassengerSelection = ReturnType<typeof useRoomingPassengerSelection>;
