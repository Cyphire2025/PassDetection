export interface AttendanceSession {
  id: string;
  group_id: string;
  name: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  scanned_count: number;
  assigned_count: number;
}

export interface AttendanceScanResponse {
  session_id: string;
  passenger_id: string | null;
  passenger_name: string | null;
  status: "counted" | "duplicate" | "invalid" | string;
  message: string;
  scanned_count: number;
  assigned_count: number;
}

export interface AttendancePassengerStatus {
  passenger_id: string;
  client_name: string;
  client_email: string | null;
  client_phone: string | null;
  departure_city: string | null;
  scanned: boolean;
  scanned_at: string | null;
}

export interface AttendanceSessionDetails {
  id: string;
  group_id: string;
  name: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  scanned_count: number;
  assigned_count: number;
  missing_passengers: AttendancePassengerStatus[];
  scanned_passengers: AttendancePassengerStatus[];
  passengers: AttendancePassengerStatus[];
}

export interface AttendanceCoordinatorSummary {
  coordinator_id: string;
  coordinator_name: string;
  assigned_count: number;
  scanned_count: number;
}

export interface AttendanceMissingPassenger {
  passenger_id: string;
  client_name: string;
  client_email: string | null;
  client_phone: string | null;
  departure_city: string | null;
  coordinator_id: string | null;
  coordinator_name: string | null;
}

export interface AttendanceScanBatchItemResponse {
  client_event_id: string;
  outcome: "counted" | "duplicate" | "rejected";
  retryable: boolean;
  scan: AttendanceScanResponse | null;
  error_code: string | null;
}

export interface AttendanceScanBatchResponse {
  batch_id: string;
  items: AttendanceScanBatchItemResponse[];
}

export interface AttendanceCloseoutCheckpoint {
  pending_count: number;
  sending_count: number;
  retryable_count: number;
  needs_review_count: number;
  unreviewed_rejected_count: number;
  oldest_pending_age_seconds: number | null;
}

export interface AttendanceCloseoutCoordinatorStatus extends AttendanceCloseoutCheckpoint {
  coordinator_id: string;
  coordinator_name: string;
  state: "ready" | "missing" | "stale" | "blocked";
  reported_at: string | null;
  report_age_seconds: number | null;
}

export interface AttendanceCloseoutStatus {
  ready: boolean;
  checkpoint_ttl_seconds: number;
  active_assignment_count: number;
  ready_assignment_count: number;
  missing_assignment_count: number;
  stale_assignment_count: number;
  nonzero_assignment_count: number;
  blocked_assignment_count: number;
  unresolved_count: number;
  oldest_pending_age_seconds: number | null;
  coordinators: AttendanceCloseoutCoordinatorStatus[];
}

export interface AttendanceSessionSummary {
  id: string;
  name: string;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  assigned_count: number;
  scanned_count: number;
  coordinators: AttendanceCoordinatorSummary[];
  missing_passengers: AttendanceMissingPassenger[];
  closeout: AttendanceCloseoutStatus;
}

export interface GroupAttendanceOverview {
  group_id: string;
  group_name: string;
  sessions: AttendanceSessionSummary[];
}

export interface AttendanceSummaryCloseout {
  ready: boolean;
  active_participant_count: number;
  ready_participant_count: number;
  blocked_participant_count: number;
  missing_participant_count: number;
  stale_participant_count: number;
  unresolved_count: number;
}

export interface AttendanceCoordinatorActivitySummary {
  coordinator_id: string;
  coordinator_name: string;
  assigned_count: number;
  scanned_count: number;
  checkpoint_state: "ready" | "missing" | "stale" | "blocked";
  checkpoint_reported_at: string | null;
  pending_count: number;
  sending_count: number;
  retryable_count: number;
  needs_review_count: number;
  unreviewed_rejected_count: number;
  oldest_pending_age_seconds: number | null;
  runtime_count: number;
  active_runtime_count: number;
}

export interface AttendanceActivitySummary {
  id: string;
  name: string;
  status: string;
  revision: string;
  present_count: number;
  missing_count: number;
  exception_count: number;
  closeout: AttendanceSummaryCloseout;
  coordinator_count: number;
  coordinators_truncated: boolean;
  coordinators: AttendanceCoordinatorActivitySummary[];
  last_canonical_update_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface GroupAttendanceSummary {
  group_id: string;
  group_name: string;
  revision: string;
  sessions: AttendanceActivitySummary[];
}

export interface AttendanceMissingPassengerItem {
  passenger_id: string;
  display_name: string;
}

export interface AttendanceMissingPassengersPage {
  session_id: string;
  revision: string;
  items: AttendanceMissingPassengerItem[];
  has_more: boolean;
  next_cursor: string | null;
  page_size: number;
}
