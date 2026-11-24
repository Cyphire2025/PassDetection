export interface TourOperationsPhase {
  phase: number;
  name: string;
  status: "planned" | "in_progress" | "completed";
  scope: string[];
}

export interface TourOperationsArchitecture {
  module: string;
  current_phase: number;
  principles: string[];
  permissions: Record<string, string[]>;
  data_entities: string[];
  offline_strategy: string[];
  navigation: string[];
  phases: TourOperationsPhase[];
}

export interface TourCoordinator {
  id: string;
  full_name: string;
  email: string;
  agency_id: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  assigned_groups_count: number;
  assigned_passengers_count: number;
}

export interface CreateCoordinatorRequest {
  full_name: string;
  email: string;
  password: string;
}

export interface TourGroupCoordinator {
  coordinator_id: string;
  full_name: string;
  email: string;
  assigned_passengers_count: number;
}

export interface TourGroup {
  id: string;
  name: string;
  status: string;
  destination: string | null;
  travel_date: string | null;
  return_date?: string | null;
  timezone?: string;
  departure_cities: string[];
  base_city_enabled: boolean;
  nearest_international_airport_enabled: boolean;
  staff_code_enabled: boolean;
  agent_employee_code_enabled: boolean;
  meal_preference_enabled: boolean;
  passenger_count: number;
  assigned_passengers_count: number;
  unassigned_passengers_count: number;
  coordinators: TourGroupCoordinator[];
}

export interface TourPassenger {
  id: string;
  client_name: string;
  client_email: string | null;
  client_phone: string | null;
  departure_city: string | null;
  submission_mode?: string;
  family_group_id?: string | null;
  family_group_label?: string | null;
  family_member_index?: number | null;
  family_relation?: string | null;
  family_gender?: string | null;
  family_size?: number;
  family_head_name?: string | null;
  status: string;
  coordinator_id: string | null;
  coordinator_name: string | null;
  qr_payload?: string | null;
}

export interface TourPassengerDetail extends TourPassenger {
  created_at: string;
  updated_at: string;
  client_reviewed_at: string | null;
  confirmed_at: string | null;
  passport_fields: Record<string, unknown>;
  overall_confidence: number | null;
}
