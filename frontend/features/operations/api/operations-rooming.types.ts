export type RoomType = "single" | "twin" | "triple";

export type RoomingTag = "unspecified" | "mixed" | "male" | "female" | "family" | "couple" | "vip";

export type RoomingSpecialRequest = "smoking" | "wheelchair" | "vip" | "late_arrival";

export interface RoomingPriorityField {
  key: string;
  label: string;
  source: string;
  groupable: boolean;
}

export interface RoomingPriorityFieldOptions {
  group_id: string;
  fields: RoomingPriorityField[];
  max_priority_fields: number;
  gender_rule: string;
}

export interface RoomingRosterFieldValues {
  group_id: string;
  field: RoomingPriorityField;
  values_by_passenger: Record<string, string | null>;
}

export interface RoomingPassenger {
  passenger_id: string;
  client_name: string;
  client_email: string | null;
  client_phone: string | null;
  passport_sex: string | null;
  submission_mode: string;
  family_group_id: string | null;
  family_group_label: string | null;
  family_member_index: number | null;
  family_relation: string | null;
  family_gender: string | null;
  family_size: number;
  family_head_name: string | null;
  allocation_tag: RoomingTag;
  special_requests: RoomingSpecialRequest[];
  roommate_notes: string | null;
  selected_hotel_id: string | null;
  selected_hotel_name: string | null;
  is_vip: boolean;
}

export interface RoomingRoom {
  id: string;
  room_number: string;
  room_type: RoomType;
  capacity: number;
  allocation_tag: Exclude<RoomingTag, "unspecified">;
  roommate_notes: string | null;
  is_saved: boolean;
  sort_order: number;
  occupants: RoomingPassenger[];
}

export interface RoomingHotel {
  id: string;
  hotel_name: string;
  city: string | null;
  check_in_date: string | null;
  check_out_date: string | null;
  rooms: RoomingRoom[];
  unallocated_passengers: RoomingPassenger[];
  selected_passengers: RoomingPassenger[];
  selected_passenger_count: number;
  allocation_priority_fields: RoomingPriorityField[];
  allocation_revision: number;
  allocation_is_current: boolean;
  allocated_passenger_count: number;
  capacity_total: number;
}

export interface RoomingWorkspace {
  group_id: string;
  group_name: string;
  destination: string | null;
  total_passengers: number;
  hotels: RoomingHotel[];
  passengers: RoomingPassenger[];
}

export interface RoomingRoomAllocationDelta {
  id: string;
  room_number: string;
  room_type: RoomType;
  capacity: number;
  allocation_tag: Exclude<RoomingTag, "unspecified">;
  roommate_notes: string | null;
  is_saved: boolean;
  sort_order: number;
  occupant_ids: string[];
}

export interface RoomingHotelAllocationDelta {
  hotel_id: string;
  rooms: RoomingRoomAllocationDelta[];
  allocation_priority_fields: RoomingPriorityField[];
  allocation_revision: number;
  allocation_is_current: boolean;
  allocated_passenger_count: number;
  capacity_total: number;
}

export interface RoomingPassengerAllocationDelta {
  passenger_id: string;
  selected_hotel_id: string | null;
  is_vip: boolean;
}

export interface RoomingAllocationMutationResponse {
  group_id: string;
  changed: boolean;
  current_revisions: Record<string, number>;
  hotels: RoomingHotelAllocationDelta[];
  passengers: RoomingPassengerAllocationDelta[];
}
