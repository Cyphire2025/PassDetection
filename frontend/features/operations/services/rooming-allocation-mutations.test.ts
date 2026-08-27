import { describe, expect, it } from "vitest";
import type {
  RoomingAllocationMutationResponse,
  RoomingHotel,
  RoomingPassenger,
  RoomingWorkspace,
} from "../api/operations.api";
import {
  expectedRoomingRevisionsForHotel,
  expectedRoomingRevisionsForSelection,
  mergeRoomingAllocationMutation,
} from "./rooming-allocation-mutations";

function passenger(
  id: string,
  selectedHotelId: string | null,
): RoomingPassenger {
  return {
    passenger_id: id,
    client_name: id,
    client_email: null,
    client_phone: null,
    passport_sex: "Male",
    submission_mode: "single",
    family_group_id: null,
    family_group_label: null,
    family_member_index: null,
    family_relation: null,
    family_gender: null,
    family_size: 1,
    family_head_name: null,
    allocation_tag: "male",
    special_requests: [],
    roommate_notes: null,
    selected_hotel_id: selectedHotelId,
    selected_hotel_name: selectedHotelId ? `Hotel ${selectedHotelId}` : null,
    is_vip: false,
  };
}

function hotel(
  id: string,
  revision: number,
  selectedPassengers: RoomingPassenger[],
): RoomingHotel {
  return {
    id,
    hotel_name: `Hotel ${id}`,
    city: `City ${id}`,
    check_in_date: null,
    check_out_date: null,
    rooms: [],
    unallocated_passengers: selectedPassengers,
    selected_passengers: selectedPassengers,
    selected_passenger_count: selectedPassengers.length,
    allocation_priority_fields: [],
    allocation_revision: revision,
    allocation_is_current: false,
    allocated_passenger_count: 0,
    capacity_total: 0,
  };
}

function workspace(): RoomingWorkspace {
  const passengerA = passenger("passenger-a", "hotel-a");
  const passengerB = passenger("passenger-b", "hotel-b");
  return {
    group_id: "group-a",
    group_name: "Group A",
    destination: "Delhi",
    total_passengers: 2,
    hotels: [
      hotel("hotel-a", 3, [passengerA]),
      hotel("hotel-b", 5, [passengerB]),
    ],
    passengers: [passengerA, passengerB],
  };
}

describe("rooming allocation revision fences", () => {
  it("includes the target and every known source hotel for passenger moves", () => {
    const current = workspace();

    expect(
      expectedRoomingRevisionsForSelection(current, {
        hotelId: "hotel-b",
        passengerIds: ["passenger-a"],
        mode: "add",
      }),
    ).toEqual({ "hotel-a": 3, "hotel-b": 5 });
    expect(
      expectedRoomingRevisionsForSelection(current, {
        hotelId: "hotel-b",
        passengerIds: ["passenger-a"],
        mode: "remove",
      }),
    ).toEqual({ "hotel-b": 5 });
    expect(expectedRoomingRevisionsForHotel(current, "hotel-a")).toEqual({
      "hotel-a": 3,
    });
  });
});

describe("rooming allocation delta merge", () => {
  it("applies a multi-hotel move without overwriting static hotel data", () => {
    const current = workspace();
    const mutation: RoomingAllocationMutationResponse = {
      group_id: current.group_id,
      changed: true,
      current_revisions: { "hotel-a": 4, "hotel-b": 6 },
      hotels: [
        {
          hotel_id: "hotel-a",
          rooms: [],
          allocation_priority_fields: [],
          allocation_revision: 4,
          allocation_is_current: false,
          allocated_passenger_count: 0,
          capacity_total: 0,
        },
        {
          hotel_id: "hotel-b",
          rooms: [],
          allocation_priority_fields: [],
          allocation_revision: 6,
          allocation_is_current: false,
          allocated_passenger_count: 0,
          capacity_total: 0,
        },
      ],
      passengers: [
        {
          passenger_id: "passenger-a",
          selected_hotel_id: "hotel-b",
          is_vip: false,
        },
      ],
    };

    const result = mergeRoomingAllocationMutation(current, mutation);

    expect(result.status).toBe("applied");
    expect(result.workspace.hotels[0].city).toBe("City hotel-a");
    expect(result.workspace.hotels[0].allocation_revision).toBe(4);
    expect(result.workspace.hotels[0].selected_passengers).toEqual([]);
    expect(result.workspace.hotels[1].allocation_revision).toBe(6);
    expect(
      result.workspace.hotels[1].selected_passengers.map(
        (item) => item.passenger_id,
      ),
    ).toEqual(["passenger-a", "passenger-b"]);
    expect(result.workspace.hotels[1].unallocated_passengers).toHaveLength(2);
  });

  it("hydrates compact room occupant IDs from the authoritative roster", () => {
    const current = workspace();
    const mutation: RoomingAllocationMutationResponse = {
      group_id: current.group_id,
      changed: true,
      current_revisions: { "hotel-a": 4 },
      hotels: [
        {
          hotel_id: "hotel-a",
          rooms: [
            {
              id: "room-a",
              room_number: "1",
              room_type: "single",
              capacity: 1,
              allocation_tag: "male",
              roommate_notes: null,
              is_saved: true,
              sort_order: 0,
              occupant_ids: ["passenger-a"],
            },
          ],
          allocation_priority_fields: [],
          allocation_revision: 4,
          allocation_is_current: true,
          allocated_passenger_count: 1,
          capacity_total: 1,
        },
      ],
      passengers: [],
    };

    const result = mergeRoomingAllocationMutation(current, mutation);

    expect(result.status).toBe("applied");
    expect(result.workspace.hotels[0].rooms[0].occupants[0].passenger_id).toBe(
      "passenger-a",
    );
    expect(result.workspace.hotels[0].unallocated_passengers).toEqual([
      result.workspace.passengers[1],
    ]);
  });

  it("discards an out-of-order response after a newer revision is cached", () => {
    const current = workspace();
    current.hotels[0].allocation_revision = 8;
    const mutation: RoomingAllocationMutationResponse = {
      group_id: current.group_id,
      changed: true,
      current_revisions: { "hotel-a": 7 },
      hotels: [
        {
          hotel_id: "hotel-a",
          rooms: [],
          allocation_priority_fields: [],
          allocation_revision: 7,
          allocation_is_current: false,
          allocated_passenger_count: 0,
          capacity_total: 0,
        },
      ],
      passengers: [],
    };

    const result = mergeRoomingAllocationMutation(current, mutation);

    expect(result.status).toBe("stale");
    expect(result.workspace).toBe(current);
    expect(result.workspace.hotels[0].allocation_revision).toBe(8);
  });
});
