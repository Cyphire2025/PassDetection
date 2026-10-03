export type TrackerKind = "visa" | "flight";
export type TrackerStatus = "all" | "marked" | "pending";

export interface TrackerGroup {
  id: string;
  name: string;
  destination: string | null;
  travel_date: string | null;
  return_date: string | null;
  status: string;
  total: number;
  visa_marked: number;
  flight_marked: number;
}

export interface TrackerGroups {
  groups: TrackerGroup[];
  total: number;
  page: number;
  page_size: number;
}

export interface TrackerPassenger {
  id: string;
  full_name: string;
  given_name: string | null;
  surname: string | null;
  passport_number: string | null;
  nationality: string | null;
  gender: string | null;
  date_of_birth: string | null;
  date_of_expiry: string | null;
  email: string | null;
  phone: string | null;
  departure_city: string | null;
  submission_status: string;
  visa_applied: boolean;
  flight_booked: boolean;
  visa_updated_at: string | null;
  flight_updated_at: string | null;
}

export interface TrackerCounts { total: number; marked: number; pending: number }
export interface TrackerRoster {
  group: TrackerGroup;
  counts: TrackerCounts;
  passengers: TrackerPassenger[];
  total: number;
  page: number;
  page_size: number;
}
export interface TrackerFilters {
  track: TrackerKind;
  status: TrackerStatus;
  search: string;
  page: number;
  page_size: number;
}
export type TrackerMarkRequest = { track: TrackerKind; marked: boolean } & (
  | { passenger_ids: string[] }
  | { selection: { status: TrackerStatus; search: string }; expected_count: number }
);
export interface TrackerMarkResult {
  updated_count: number;
  unchanged_count: number;
  passenger_ids: string[];
  counts: TrackerCounts;
}
export interface TrackerImportRow {
  row_number: number;
  name: string | null;
  passport_number: string | null;
  passenger_id: string | null;
  passenger_name: string | null;
  status: "matched" | "ambiguous" | "unmatched" | "duplicate";
  reason: string;
}
export interface TrackerImportPreview {
  track: TrackerKind;
  marked: boolean;
  total_rows: number;
  matched_count: number;
  ambiguous_count: number;
  unmatched_count: number;
  duplicate_count: number;
  passenger_ids: string[];
  rows: TrackerImportRow[];
}
