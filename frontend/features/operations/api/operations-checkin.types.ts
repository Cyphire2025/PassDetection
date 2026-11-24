import type {
  RoomType,
} from "./operations-rooming.types";

export interface HotelCheckinPassenger {
  checkin_id: string;
  passenger_id: string;
  passenger_name: string;
  submission_mode: string;
  family_group_id: string | null;
  family_group_label: string | null;
  family_relation: string | null;
  family_size: number;
  family_head_name: string | null;
  room_id: string;
  room_number: string;
  room_type: RoomType;
  roommates: string[];
  checked_in: boolean;
  key_issued: boolean;
  welcome_letter_issued: boolean;
  remarks: string | null;
  is_vip: boolean;
  has_special_request: boolean;
  room_has_missing_occupants: boolean;
}

export interface HotelCheckinDashboard {
  hotel_id: string;
  hotel_name: string;
  group_id: string;
  group_name: string;
  total_allocated_passengers: number;
  checked_in_count: number;
  keys_issued_count: number;
  welcome_letters_issued_count: number;
  rooms_complete: number;
  rooms_with_missing_occupants: number;
  passengers: HotelCheckinPassenger[];
}

export interface HotelCheckinScanResponse {
  status: string;
  message: string;
  checkin: HotelCheckinPassenger | null;
}
