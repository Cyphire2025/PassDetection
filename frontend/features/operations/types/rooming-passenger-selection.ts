import type { RoomingHotel, RoomingPriorityField, RoomingWorkspace } from "../api/operations.api";

export type RosterFilter = "all" | "this-hotel" | "unassigned" | "other-hotel";

export interface RoomingPassengerHotelAllocationProps {
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
