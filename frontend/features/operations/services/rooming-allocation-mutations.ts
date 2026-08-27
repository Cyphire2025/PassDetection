import type {
  RoomingAllocationMutationResponse,
  RoomingHotel,
  RoomingPassenger,
  RoomingWorkspace,
} from "../api/operations.api";

export const ROOMING_REVISION_CONFLICT_CODE =
  "ROOMING_ALLOCATION_REVISION_CONFLICT";

export type RoomingMutationMergeStatus =
  | "applied"
  | "stale"
  | "incompatible";

export interface RoomingMutationMergeResult {
  status: RoomingMutationMergeStatus;
  workspace: RoomingWorkspace;
}

export function expectedRoomingRevisionsForHotel(
  workspace: RoomingWorkspace,
  hotelId: string,
): Record<string, number> {
  const hotel = workspace.hotels.find((candidate) => candidate.id === hotelId);
  if (!hotel) {
    throw new Error("The selected hotel is no longer available. Refresh Rooming and try again.");
  }
  return { [hotel.id]: hotel.allocation_revision };
}

export function expectedRoomingRevisionsForSelection(
  workspace: RoomingWorkspace,
  {
    hotelId,
    passengerIds,
    mode,
  }: {
    hotelId: string;
    passengerIds: string[];
    mode: "replace" | "add" | "remove";
  },
): Record<string, number> {
  const hotelById = new Map(
    workspace.hotels.map((hotel) => [hotel.id, hotel] as const),
  );
  if (!hotelById.has(hotelId)) {
    throw new Error("The selected hotel is no longer available. Refresh Rooming and try again.");
  }

  const revisionHotelIds = new Set([hotelId]);
  if (mode !== "remove") {
    const requestedIds = new Set(passengerIds);
    for (const passenger of workspace.passengers) {
      if (
        requestedIds.has(passenger.passenger_id)
        && passenger.selected_hotel_id
        && passenger.selected_hotel_id !== hotelId
      ) {
        revisionHotelIds.add(passenger.selected_hotel_id);
      }
    }
  }

  return Object.fromEntries(
    [...revisionHotelIds]
      .sort()
      .map((revisionHotelId) => {
        const hotel = hotelById.get(revisionHotelId);
        if (!hotel) {
          throw new Error(
            "A passenger's current hotel is no longer available. Refresh Rooming and try again.",
          );
        }
        return [revisionHotelId, hotel.allocation_revision];
      }),
  );
}

export function mergeRoomingAllocationMutation(
  workspace: RoomingWorkspace,
  mutation: RoomingAllocationMutationResponse,
): RoomingMutationMergeResult {
  if (workspace.group_id !== mutation.group_id) {
    return { status: "incompatible", workspace };
  }

  const hotelById = new Map(
    workspace.hotels.map((hotel) => [hotel.id, hotel] as const),
  );
  const deltaByHotelId = new Map(
    mutation.hotels.map((hotel) => [hotel.hotel_id, hotel] as const),
  );
  if (deltaByHotelId.size !== mutation.hotels.length) {
    return { status: "incompatible", workspace };
  }

  for (const [hotelId, currentRevision] of Object.entries(
    mutation.current_revisions,
  )) {
    const cachedHotel = hotelById.get(hotelId);
    if (
      !cachedHotel
      || !Number.isSafeInteger(currentRevision)
      || currentRevision < 0
    ) {
      return { status: "incompatible", workspace };
    }
    if (cachedHotel.allocation_revision > currentRevision) {
      return { status: "stale", workspace };
    }
    if (
      cachedHotel.allocation_revision < currentRevision
      && !deltaByHotelId.has(hotelId)
    ) {
      return { status: "incompatible", workspace };
    }
  }

  for (const delta of mutation.hotels) {
    if (
      !hotelById.has(delta.hotel_id)
      || mutation.current_revisions[delta.hotel_id] !== delta.allocation_revision
    ) {
      return { status: "incompatible", workspace };
    }
  }
  if (mutation.changed && mutation.hotels.length === 0) {
    return { status: "incompatible", workspace };
  }
  if (!mutation.changed) {
    return { status: "applied", workspace };
  }

  const passengerDeltaById = new Map(
    mutation.passengers.map((passenger) => [passenger.passenger_id, passenger] as const),
  );
  if (passengerDeltaById.size !== mutation.passengers.length) {
    return { status: "incompatible", workspace };
  }

  const hotelNameById = new Map(
    workspace.hotels.map((hotel) => [hotel.id, hotel.hotel_name] as const),
  );
  const passengers = workspace.passengers.map((passenger) => {
    const delta = passengerDeltaById.get(passenger.passenger_id);
    if (!delta) return passenger;
    if (delta.selected_hotel_id && !hotelNameById.has(delta.selected_hotel_id)) {
      return null;
    }
    return {
      ...passenger,
      selected_hotel_id: delta.selected_hotel_id,
      selected_hotel_name: delta.selected_hotel_id
        ? hotelNameById.get(delta.selected_hotel_id) ?? null
        : null,
      is_vip: delta.is_vip,
    } satisfies RoomingPassenger;
  });
  if (passengers.some((passenger) => passenger === null)) {
    return { status: "incompatible", workspace };
  }
  const resolvedPassengers = passengers as RoomingPassenger[];
  const passengerById = new Map(
    resolvedPassengers.map((passenger) => [passenger.passenger_id, passenger] as const),
  );
  if (
    [...passengerDeltaById.keys()].some(
      (passengerId) => !passengerById.has(passengerId),
    )
  ) {
    return { status: "incompatible", workspace };
  }

  const allocationHotels: RoomingHotel[] = [];
  for (const hotel of workspace.hotels) {
    const delta = deltaByHotelId.get(hotel.id);
    if (!delta) {
      allocationHotels.push(hotel);
      continue;
    }
    const rooms = [];
    for (const room of delta.rooms) {
      const occupants = room.occupant_ids.map((passengerId) =>
        passengerById.get(passengerId),
      );
      if (occupants.some((passenger) => passenger === undefined)) {
        return { status: "incompatible", workspace };
      }
      rooms.push({
        id: room.id,
        room_number: room.room_number,
        room_type: room.room_type,
        capacity: room.capacity,
        allocation_tag: room.allocation_tag,
        roommate_notes: room.roommate_notes,
        is_saved: room.is_saved,
        sort_order: room.sort_order,
        occupants: occupants as RoomingPassenger[],
      });
    }
    allocationHotels.push({
      ...hotel,
      rooms,
      allocation_priority_fields: delta.allocation_priority_fields,
      allocation_revision: delta.allocation_revision,
      allocation_is_current: delta.allocation_is_current,
      allocated_passenger_count: delta.allocated_passenger_count,
      capacity_total: delta.capacity_total,
    });
  }

  const selectedPassengersByHotel = new Map<string, RoomingPassenger[]>();
  for (const passenger of resolvedPassengers) {
    if (!passenger.selected_hotel_id) continue;
    const selected = selectedPassengersByHotel.get(passenger.selected_hotel_id) ?? [];
    selected.push(passenger);
    selectedPassengersByHotel.set(passenger.selected_hotel_id, selected);
  }
  const allocatedPassengerIds = new Set(
    allocationHotels.flatMap((hotel) =>
      hotel.rooms.flatMap((room) =>
        room.occupants.map((occupant) => occupant.passenger_id),
      ),
    ),
  );
  const unallocatedPassengers = resolvedPassengers.filter(
    (passenger) => !allocatedPassengerIds.has(passenger.passenger_id),
  );
  const hotels = allocationHotels.map((hotel) => {
    const selectedPassengers = selectedPassengersByHotel.get(hotel.id) ?? [];
    return {
      ...hotel,
      selected_passengers: selectedPassengers,
      selected_passenger_count: selectedPassengers.length,
      unallocated_passengers: unallocatedPassengers,
    };
  });

  return {
    status: "applied",
    workspace: {
      ...workspace,
      hotels,
      passengers: resolvedPassengers,
    },
  };
}

export function isRoomingRevisionConflict(error: unknown): boolean {
  return Boolean(
    error
    && typeof error === "object"
    && "code" in error
    && error.code === ROOMING_REVISION_CONFLICT_CODE,
  );
}
