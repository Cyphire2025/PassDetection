export interface CompanyReference {
  id: string;
  name: string;
  status: "active" | "inactive";
}

export interface Company extends CompanyReference {
  external_reference: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface CompanySearch {
  search?: string;
  status?: "active" | "inactive" | "all";
  cursor?: string;
  page_size?: number;
}

export interface CompanyInput {
  name: string;
  external_reference?: string | null;
}

export interface CompanyUpdate extends Partial<CompanyInput> {
  expected_revision: number;
  status?: CompanyReference["status"];
}

export interface CompanySummary {
  completed_groups: number;
  current_groups: number;
  passenger_trips_completed: number;
  collected_records: number;
  active_groups: number;
  closed_groups: number;
  archived_groups: number;
  total_groups: number;
  unique_travellers: number | null;
  trip_participations: number | null;
  unresolved_historical_records: number;
  unprocessed_records?: number;
  identity_totals_partial: boolean;
}

export interface CompanyGroup {
  id: string;
  name: string;
  destination: string | null;
  travel_date: string | null;
  return_date: string | null;
  status: "active" | "closed" | "archived";
  phase?: "active" | "completed";
  import_only: boolean;
  submission_count: number;
  returning_travellers?: number;
  trip_participations?: number;
  reuse_completed?: number;
}

export interface CompanyGroupSearch extends Omit<CompanySearch, "status"> {
  phase?: "all" | "active" | "completed";
  status?: CompanyGroup["status"] | "all";
  import_only?: boolean;
}

export interface TravellerHistory {
  id: string;
  group_id: string;
  group_name: string;
  travel_date: string | null;
  lifecycle: string;
  participation_status: string;
  document_revision: number | null;
}

export interface HistoryPage<T> {
  items: T[];
  next_cursor: string | null;
}
