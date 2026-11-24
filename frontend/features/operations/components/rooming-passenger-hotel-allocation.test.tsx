import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RoomingHotel, RoomingPassenger, RoomingWorkspace } from "../api/operations.api";
import { RoomingPassengerHotelAllocation } from "./rooming-passenger-hotel-allocation";

const roster = vi.hoisted(() => ({
  values: undefined as Record<string, string | null> | undefined,
  isLoading: false,
  error: null as Error | null,
}));
vi.mock("../hooks/use-operations", () => ({
  useRoomingRosterFieldValues: (_groupId: string, key: string | null) => ({
    data: key && roster.values ? { values_by_passenger: roster.values } : undefined,
    isLoading: Boolean(key) && roster.isLoading,
    error: key ? roster.error : null,
  }),
}));

function hotel(id: string, hotel_name: string): RoomingHotel {
  return {
    id, hotel_name, city: null, check_in_date: null, check_out_date: null,
    rooms: [], unallocated_passengers: [], selected_passengers: [], selected_passenger_count: 0,
    allocation_priority_fields: [], allocation_revision: 1, allocation_is_current: false,
    allocated_passenger_count: 0, capacity_total: 0,
  };
}
const active = hotel("active-hotel", "Active hotel"), other = hotel("other-hotel", "Other hotel");

function passenger(id: string, selectedHotelId: string | null = null): RoomingPassenger {
  return {
    passenger_id: id, client_name: `Passenger ${id}`, client_email: null, client_phone: null,
    passport_sex: "M", submission_mode: "single", family_group_id: null, family_group_label: null,
    family_member_index: null, family_relation: null, family_gender: null, family_size: 1,
    family_head_name: null, allocation_tag: "unspecified", special_requests: [], roommate_notes: null,
    selected_hotel_id: selectedHotelId,
    selected_hotel_name: selectedHotelId === active.id ? active.hotel_name : selectedHotelId ? other.hotel_name : null,
    is_vip: false,
  };
}

function setup(passengers: RoomingPassenger[]) {
  const workspace: RoomingWorkspace = {
    group_id: "synthetic-group", group_name: "Synthetic trip", destination: null,
    total_passengers: passengers.length, hotels: [active, other], passengers,
  };
  const props = {
    workspace, activeHotel: active, isAssigning: false, isUpdatingVip: false,
    groupingFields: [{ key: "region", label: "Region", source: "custom", groupable: true }],
    groupingFieldsLoading: false, groupingFieldsError: false,
    onAssign: vi.fn().mockResolvedValue(undefined), onSetVip: vi.fn().mockResolvedValue(undefined),
  };
  const view = render(<RoomingPassengerHotelAllocation {...props} />);
  return { ...view, props };
}

beforeEach(() => { roster.values = undefined; roster.isLoading = false; roster.error = null; });

describe("rooming passenger selection", () => {
  it("retains selections across roster pages and assigns their exact IDs", async () => {
    const passengers = Array.from({ length: 60 }, (_, index) => passenger(String(index + 1).padStart(2, "0")));
    const { props } = setup(passengers);
    await userEvent.click(screen.getByRole("button", { name: "Show passenger list" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Passenger 01" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Passenger 60" }));
    await userEvent.click(screen.getByRole("button", { name: "Assign selected" }));
    await waitFor(() => expect(props.onAssign).toHaveBeenCalledWith(["01", "60"], active.id));
    expect(screen.getByRole("checkbox", { name: "Select Passenger 60" })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByRole("checkbox", { name: "Select Passenger 01" })).toBeChecked();
  });

  it("keeps VIP changes scoped to the active hotel while bulk moves include every selection", async () => {
    const { props } = setup([passenger("A", active.id), passenger("B", other.id), passenger("C")]);
    await userEvent.click(screen.getByRole("button", { name: "Show passenger list" }));
    await userEvent.click(screen.getByRole("button", { name: "Select all group" }));
    await userEvent.click(screen.getByRole("button", { name: "Mark VIP (1)" }));
    await waitFor(() => expect(props.onSetVip).toHaveBeenCalledWith(["A"], true));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Assign selected passengers to" }), other.id);
    await userEvent.click(screen.getByRole("button", { name: "Assign selected" }));
    await waitFor(() => expect(props.onAssign).toHaveBeenCalledWith(["A", "B", "C"], other.id));
  });

  it("discards removed passengers from selected IDs after an authoritative refresh", async () => {
    const a = passenger("A"), b = passenger("B");
    const { props, rerender } = setup([a, b]);
    await userEvent.click(screen.getByRole("button", { name: "Show passenger list" }));
    await userEvent.click(screen.getByRole("button", { name: "Select all group" }));
    rerender(<RoomingPassengerHotelAllocation {...props} workspace={{ ...props.workspace, total_passengers: 1, passengers: [a] }} />);
    await userEvent.click(screen.getByRole("button", { name: "Assign selected" }));
    await waitFor(() => expect(props.onAssign).toHaveBeenCalledWith(["A"], active.id));
  });

  it("supports group selection, expansion and mixed checkboxes without losing selected rows", async () => {
    roster.values = { A: "North", B: "North", C: null };
    setup([passenger("A"), passenger("B"), passenger("C")]);
    await userEvent.click(screen.getByRole("button", { name: "Show passenger list" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group by imported field" }), "region");
    const group = screen.getByRole("checkbox", { name: "Select North" });
    await userEvent.click(group);
    await userEvent.click(screen.getByRole("button", { name: /North.*2 passengers/ }));
    expect(screen.getByRole("checkbox", { name: "Select Passenger A" })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Passenger B" }));
    expect(group).toHaveAttribute("aria-checked", "mixed");
    expect(group).toBePartiallyChecked();
  });

  it("waits for authorized grouping values instead of exposing an ungrouped fallback", async () => {
    roster.isLoading = true;
    setup([passenger("A")]);
    await userEvent.click(screen.getByRole("button", { name: "Show passenger list" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Group by imported field" }), "region");
    expect(screen.getByRole("status")).toHaveTextContent("Loading authorized values");
    expect(screen.queryByRole("checkbox", { name: "Select Passenger A" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select visible" })).toBeDisabled();
  });

  it("preserves selected passengers for a safe retry after assignment rejection", async () => {
    const { props } = setup([passenger("A")]);
    props.onAssign.mockRejectedValueOnce(new Error("Rooming changed. Refresh and retry."));
    await userEvent.click(screen.getByRole("button", { name: "Show passenger list" }));
    await userEvent.click(screen.getByRole("button", { name: "Select visible" }));
    await userEvent.click(screen.getByRole("button", { name: "Assign selected" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Rooming changed. Refresh and retry."));
    expect(screen.getByRole("checkbox", { name: "Select Passenger A" })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Assign selected" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 passenger assigned to Active hotel."));
    expect(props.onAssign).toHaveBeenCalledTimes(2);
  });
});
