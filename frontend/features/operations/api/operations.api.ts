import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";

export interface AdminOverview {
  agencies: number;
  users: number;
  client_groups: number;
  passport_submissions: number;
  pending_review: number;
  client_submitted: number;
  failed: number;
}

export interface ManagerAccount {
  id: string;
  full_name: string;
  email: string;
  role: "agency_manager";
  agency_id: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  created_groups: ManagerGroupAccess[];
  assigned_groups: ManagerGroupAccess[];
  credential_state: "invited" | "active";
  activation_token?: string | null;
}

export interface ManagerGroupAccess {
  id: string;
  agency_id: string;
  name: string;
  status: string;
  created_by_user_id: string | null;
}

export interface ManagedAccount {
  id: string;
  full_name: string;
  email: string;
  role: "agency_manager" | "agency_staff" | "agency_coordinator";
  agency_id: string | null;
  agency_name: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  credential_state: "invited" | "active";
  activation_token?: string | null;
}

export interface StaffAccount {
  id: string;
  full_name: string;
  email: string;
  role: "agency_staff";
  agency_id: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  credential_state?: "invited" | "active";
  created_groups: ManagerGroupAccess[];
  assigned_groups: ManagerGroupAccess[];
}

export interface DeleteManagedAccountResponse {
  account_id: string;
  result: "deleted" | "access_removed" | string;
  preserved_history: boolean;
}

export interface CreateManagerRequest {
  full_name: string;
  email: string;
}

export interface CreateStaffRequest {
  full_name: string;
  email: string;
}

export interface DeleteManagerResponse {
  deleted_manager_id: string;
  deleted_owned_data: boolean;
  deleted_client_groups: number;
  deleted_passport_submissions: number;
  deleted_processing_jobs: number;
  deleted_notifications: number;
  deleted_audit_logs: number;
  deleted_storage_objects: number;
}

export interface AnalyticsSummary {
  status_counts: Record<string, number>;
  confidence_buckets: Record<string, number>;
  submissions_by_day: Record<string, number>;
  average_confidence: number | null;
}

export interface AuditLog {
  id: string;
  agency_id: string | null;
  user_id: string | null;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  ip_address: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogListItem {
  id: string;
  agency_id: string | null;
  user_id: string | null;
  actor_email: string | null;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  result: AuditLogResult | null;
  created_at: string;
}

export type AuditLogResult = "success" | "blocked" | "denied" | "failed";

export interface AuditLogPage {
  items: AuditLogListItem[];
  has_more: boolean;
  next_cursor: string | null;
  incomplete: boolean;
  page_size: number;
}

export interface AuditLogFilters {
  start_at?: string;
  end_at?: string;
  actor?: string;
  event_type?: string;
  entity_type?: string;
  entity_id?: string;
  result?: AuditLogResult;
  agency_id?: string;
}

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
  hotel_id: string; hotel_name: string; group_id: string; group_name: string;
  total_allocated_passengers: number; checked_in_count: number; keys_issued_count: number; welcome_letters_issued_count: number; rooms_complete: number; rooms_with_missing_occupants: number;
  passengers: HotelCheckinPassenger[];
}
export interface HotelCheckinScanResponse { status: string; message: string; checkin: HotelCheckinPassenger | null; }

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

export interface GroupPassengerQrCode {
  passenger_id: string;
  client_name: string;
  client_email: string | null;
  client_phone: string | null;
  departure_city: string | null;
  coordinator_id: string | null;
  coordinator_name: string | null;
  qr_status: "not_generated" | "active" | "inactive" | "expired" | "revoked" | string;
  qr_token_version: number | null;
  qr_created_at: string | null;
  qr_expires_at: string | null;
  qr_revoked_at: string | null;
  qr_payload: string | null;
}

export interface PassengerQrToken {
  passenger_id: string;
  status: GroupPassengerQrCode["qr_status"];
  token_version: number;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  qr_payload: string | null;
}

export interface GroupPassengerQrCodes {
  group_id: string;
  group_name: string;
  generated_at: string;
  passengers: GroupPassengerQrCode[];
}

export interface QrDeliveryPreviewRecipient {
  passenger_id: string;
  passenger_name: string;
  passport_number: string | null;
  qr_token_id: string | null;
  qr_token_version: number | null;
  qr_status: string;
  recipient_id: string | null;
  broadcast_group_id: string | null;
  broadcast_name: string | null;
  phone_number: string | null;
  delivery_id: string | null;
  delivery_status: string;
  eligible: boolean;
  reason: string;
  error_message: string | null;
  message_preview: string | null;
}

export interface QrDeliveryPreview {
  group_id: string;
  template_name: string | null;
  template_configured: boolean;
  linked_broadcast_count: number;
  can_send: boolean;
  configuration_error: string | null;
  message_content: string;
  summary: {
    total_passengers: number;
    ready: number;
    retryable: number;
    already_sent: number;
    in_progress: number;
    blocked: number;
    ambiguous_recipients?: number;
  };
  recipients: QrDeliveryPreviewRecipient[];
}

export interface SendQrBroadcastResponse {
  send_batch_id: string | null;
  queued_count: number;
  skipped_count: number;
  message: string;
}

export const operationsApi = {
  adminOverview: async (): Promise<AdminOverview> => {
    const { data } = await apiClient.get<AdminOverview>(API_ENDPOINTS.admin.overview);
    return data;
  },

  managers: async (): Promise<ManagerAccount[]> => {
    const { data } = await apiClient.get<ManagerAccount[]>(API_ENDPOINTS.admin.managers);
    return data;
  },

  createManager: async (body: CreateManagerRequest): Promise<ManagerAccount> => {
    const { data } = await apiClient.post<ManagerAccount>(API_ENDPOINTS.admin.managers, body);
    return data;
  },

  createStaff: async (body: CreateStaffRequest): Promise<ManagedAccount> => {
    const { data } = await apiClient.post<ManagedAccount>(API_ENDPOINTS.admin.staff, body);
    return data;
  },

  staffAccessAccounts: async (): Promise<StaffAccount[]> => {
    const { data } = await apiClient.get<StaffAccount[]>(API_ENDPOINTS.admin.staffAccess);
    return data;
  },

  deleteManager: async (managerId: string, deleteOwnedData: boolean): Promise<DeleteManagerResponse> => {
    const { data } = await apiClient.delete<DeleteManagerResponse>(API_ENDPOINTS.admin.manager(managerId), {
      data: { delete_owned_data: deleteOwnedData },
    });
    return data;
  },

  adminGroups: async (): Promise<ManagerGroupAccess[]> => {
    const { data } = await apiClient.get<ManagerGroupAccess[]>(API_ENDPOINTS.admin.groups);
    return data;
  },

  assignManagerGroups: async (managerId: string, groupIds: string[]): Promise<ManagerAccount> => {
    const { data } = await apiClient.put<ManagerAccount>(API_ENDPOINTS.admin.managerGroups(managerId), {
      group_ids: groupIds,
    });
    return data;
  },

  assignStaffGroups: async (staffId: string, groupIds: string[]): Promise<StaffAccount> => {
    const { data } = await apiClient.put<StaffAccount>(API_ENDPOINTS.admin.staffGroups(staffId), {
      group_ids: groupIds,
    });
    return data;
  },

  managedAccounts: async (): Promise<ManagedAccount[]> => {
    const { data } = await apiClient.get<ManagedAccount[]>(API_ENDPOINTS.admin.accounts);
    return data;
  },

  staffAccounts: async (): Promise<ManagedAccount[]> => {
    const { data } = await apiClient.get<ManagedAccount[]>(API_ENDPOINTS.admin.staff);
    return data;
  },

  resetManagedAccountPassword: async (accountId: string): Promise<ManagedAccount> => {
    const { data } = await apiClient.post<ManagedAccount>(API_ENDPOINTS.admin.accountPassword(accountId), { issue_activation_link: true });
    return data;
  },

  resetManagedAccountMfa: async (accountId: string): Promise<void> => {
    await apiClient.post(API_ENDPOINTS.admin.accountMfa(accountId));
  },

  revokeManagedAccountSessions: async (accountId: string): Promise<void> => {
    await apiClient.post(API_ENDPOINTS.admin.accountSessions(accountId));
  },

  setManagedAccountStatus: async (accountId: string, isActive: boolean): Promise<ManagedAccount> => {
    const { data } = await apiClient.patch<ManagedAccount>(API_ENDPOINTS.admin.accountStatus(accountId), {
      is_active: isActive,
    });
    return data;
  },

  deleteManagedAccount: async (accountId: string): Promise<DeleteManagedAccountResponse> => {
    const { data } = await apiClient.delete<DeleteManagedAccountResponse>(API_ENDPOINTS.admin.account(accountId));
    return data;
  },

  analyticsSummary: async (days = 30): Promise<AnalyticsSummary> => {
    const { data } = await apiClient.get<AnalyticsSummary>(API_ENDPOINTS.analytics.summary, {
      params: { days },
    });
    return data;
  },

  auditLogs: async (): Promise<AuditLog[]> => {
    const { data } = await apiClient.get<AuditLog[]>(API_ENDPOINTS.auditLogs.root);
    return data;
  },

  auditLogPage: async ({
    filters,
    cursor,
    pageSize = 50,
    signal,
  }: {
    filters: AuditLogFilters;
    cursor?: string | null;
    pageSize?: number;
    signal?: AbortSignal;
  }): Promise<AuditLogPage> => {
    const { data } = await apiClient.get<AuditLogPage>(API_ENDPOINTS.auditLogs.page, {
      params: {
        ...filters,
        cursor: cursor || undefined,
        page_size: pageSize,
      },
      signal,
    });
    return data;
  },

  exportAuditLogs: async ({
    filters,
    signal,
  }: {
    filters: AuditLogFilters & { start_at: string; end_at: string };
    signal?: AbortSignal;
  }): Promise<{ content: Blob; truncated: boolean }> => {
    const response = await apiClient.get<Blob>(API_ENDPOINTS.auditLogs.export, {
      params: filters,
      responseType: "blob",
      signal,
    });
    return {
      content: response.data,
      truncated: String(response.headers["x-audit-export-truncated"]).toLowerCase() === "true",
    };
  },

  tourOperationsArchitecture: async (): Promise<TourOperationsArchitecture> => {
    const { data } = await apiClient.get<TourOperationsArchitecture>(API_ENDPOINTS.tourOperations.architecture);
    return data;
  },

  tourCoordinators: async (): Promise<TourCoordinator[]> => {
    const { data } = await apiClient.get<TourCoordinator[]>(API_ENDPOINTS.tourOperations.coordinators);
    return data;
  },

  createTourCoordinator: async (body: CreateCoordinatorRequest): Promise<TourCoordinator> => {
    const { data } = await apiClient.post<TourCoordinator>(API_ENDPOINTS.tourOperations.coordinators, body);
    return data;
  },

  tourGroups: async (): Promise<TourGroup[]> => {
    const { data } = await apiClient.get<TourGroup[]>(API_ENDPOINTS.tourOperations.groups);
    return data;
  },

  roomingWorkspace: async (groupId: string): Promise<RoomingWorkspace> => {
    const { data } = await apiClient.get<RoomingWorkspace>(API_ENDPOINTS.rooming.group(groupId));
    return data;
  },

  roomingPriorityFields: async (groupId: string): Promise<RoomingPriorityFieldOptions> => {
    const { data } = await apiClient.get<RoomingPriorityFieldOptions>(
      API_ENDPOINTS.rooming.priorityFields(groupId),
    );
    return data;
  },

  roomingRosterFieldValues: async (
    groupId: string,
    fieldKey: string,
  ): Promise<RoomingRosterFieldValues> => {
    const { data } = await apiClient.get<RoomingRosterFieldValues>(
      API_ENDPOINTS.rooming.rosterFieldValues(groupId),
      { params: { field_key: fieldKey } },
    );
    return data;
  },

  createRoomingHotel: async (groupId: string, body: {
    hotel_name: string;
    city?: string;
    check_in_date?: string;
    check_out_date?: string;
  }): Promise<RoomingHotel> => {
    const { data } = await apiClient.post<RoomingHotel>(API_ENDPOINTS.rooming.hotels(groupId), body);
    return data;
  },

  updateRoomingHotel: async (hotelId: string, body: {
    hotel_name: string;
    city?: string;
    check_in_date?: string;
    check_out_date?: string;
  }): Promise<RoomingHotel> => {
    const { data } = await apiClient.patch<RoomingHotel>(API_ENDPOINTS.rooming.hotel(hotelId), body);
    return data;
  },

  updateRoomingPassengerSelection: async (
    hotelId: string,
    body: {
      passenger_ids: string[];
      mode: "replace" | "add" | "remove";
      expected_allocation_revisions: Record<string, number>;
    },
  ): Promise<RoomingAllocationMutationResponse> => {
    const { data } = await apiClient.put<RoomingAllocationMutationResponse>(
      API_ENDPOINTS.rooming.passengerSelection(hotelId),
      body,
    );
    return data;
  },

  updateRoomingVip: async (
    hotelId: string,
    body: {
      passenger_ids: string[];
      is_vip: boolean;
      expected_allocation_revisions: Record<string, number>;
    },
  ): Promise<RoomingAllocationMutationResponse> => {
    const { data } = await apiClient.put<RoomingAllocationMutationResponse>(
      API_ENDPOINTS.rooming.vip(hotelId),
      body,
    );
    return data;
  },

  autoAllocateRoomingHotel: async (
    hotelId: string,
    body: {
      priority_fields: string[];
      expected_allocation_revisions: Record<string, number>;
    },
  ): Promise<RoomingAllocationMutationResponse> => {
    const { data } = await apiClient.post<RoomingAllocationMutationResponse>(
      API_ENDPOINTS.rooming.autoAllocate(hotelId),
      body,
    );
    return data;
  },

  exportRoomingHotel: async (hotelId: string): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(API_ENDPOINTS.rooming.hotelExport(hotelId), { responseType: "blob" });
    return data;
  },

  hotelCheckins: async (hotelId: string): Promise<HotelCheckinDashboard> => {
    const { data } = await apiClient.get<HotelCheckinDashboard>(API_ENDPOINTS.rooming.checkins(hotelId)); return data;
  },
  scanHotelCheckin: async (hotelId: string, qr_payload: string, client_event_id?: string): Promise<HotelCheckinScanResponse> => {
    const { data } = await apiClient.post<HotelCheckinScanResponse>(API_ENDPOINTS.rooming.checkinScan(hotelId), { qr_payload, client_event_id, device_id: getDeviceId() }); return data;
  },
  updateHotelCheckin: async (checkinId: string, body: { key_issued?: boolean; welcome_letter_issued?: boolean; remarks?: string }): Promise<HotelCheckinPassenger> => {
    const { data } = await apiClient.patch<HotelCheckinPassenger>(API_ENDPOINTS.rooming.checkin(checkinId), body); return data;
  },
  exportHotelCheckins: async (hotelId: string): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(API_ENDPOINTS.rooming.checkinExport(hotelId), { responseType: "blob" }); return data;
  },

  assignTourGroupCoordinators: async (groupId: string, coordinatorIds: string[]): Promise<TourGroup> => {
    const { data } = await apiClient.put<TourGroup>(API_ENDPOINTS.tourOperations.groupCoordinators(groupId), {
      coordinator_ids: coordinatorIds,
    });
    return data;
  },

  tourGroupPassengers: async (groupId: string): Promise<TourPassenger[]> => {
    const { data } = await apiClient.get<TourPassenger[]>(API_ENDPOINTS.tourOperations.groupPassengers(groupId));
    return data;
  },

  assignTourGroupPassengers: async (
    groupId: string,
    passengerIds: string[],
    coordinatorId: string | null,
  ): Promise<TourPassenger[]> => {
    const { data } = await apiClient.put<TourPassenger[]>(API_ENDPOINTS.tourOperations.assignGroupPassengers(groupId), {
      passenger_ids: passengerIds,
      coordinator_id: coordinatorId,
    });
    return data;
  },

  myTourGroups: async (): Promise<TourGroup[]> => {
    const { data } = await apiClient.get<TourGroup[]>(API_ENDPOINTS.tourOperations.myGroups);
    return data;
  },

  myTourGroupPassengers: async (groupId: string): Promise<TourPassenger[]> => {
    const { data } = await apiClient.get<TourPassenger[]>(API_ENDPOINTS.tourOperations.myGroupPassengers(groupId));
    return data;
  },

  myTourGroupPassenger: async (groupId: string, passengerId: string): Promise<TourPassengerDetail> => {
    const { data } = await apiClient.get<TourPassengerDetail>(
      API_ENDPOINTS.tourOperations.myGroupPassenger(groupId, passengerId),
    );
    return data;
  },

  myAttendanceSessions: async (groupId: string): Promise<AttendanceSession[]> => {
    const { data } = await apiClient.get<AttendanceSession[]>(API_ENDPOINTS.tourOperations.myGroupSessions(groupId));
    return data;
  },

  myAttendanceSessionDetails: async (sessionId: string): Promise<AttendanceSessionDetails> => {
    const { data } = await apiClient.get<AttendanceSessionDetails>(API_ENDPOINTS.tourOperations.mySessionDetails(sessionId));
    return data;
  },

  scanMyAttendanceSession: async ({
    sessionId,
    qrPayload,
    clientEventId,
    scannedAt,
    deviceId,
    runtimeId,
    syncSource,
  }: {
    sessionId: string;
    qrPayload: string;
    clientEventId: string;
    scannedAt?: string;
    deviceId?: string;
    runtimeId?: string;
    syncSource?: "online" | "offline";
  }): Promise<AttendanceScanResponse> => {
    const { data } = await apiClient.post<AttendanceScanResponse>(API_ENDPOINTS.tourOperations.mySessionScan(sessionId), {
      qr_payload: qrPayload,
      client_event_id: clientEventId,
      scanned_at: scannedAt,
      device_id: deviceId,
      runtime_id: runtimeId,
      sync_source: syncSource ?? "online",
    });
    return data;
  },

  scanMyAttendanceSessionBatch: async ({
    sessionId,
    batchId,
    scans,
  }: {
    sessionId: string;
    batchId: string;
    scans: Array<Readonly<{
      clientEventId: string;
      qrPayload: string;
      scannedAt: string;
    }>>;
  }): Promise<AttendanceScanBatchResponse> => {
    const { data } = await apiClient.post<AttendanceScanBatchResponse>(
      API_ENDPOINTS.tourOperations.mySessionScanBatch(sessionId),
      {
        batch_id: batchId,
        scans: scans.map((scan) => ({
          client_event_id: scan.clientEventId,
          qr_payload: scan.qrPayload,
          scanned_at: scan.scannedAt,
        })),
      },
    );
    return data;
  },

  completeManagedAttendanceSession: async ({
    groupId,
    sessionId,
    exceptionReason,
  }: {
    groupId: string;
    sessionId: string;
    exceptionReason?: string;
  }): Promise<AttendanceSession> => {
    const { data } = await apiClient.put<AttendanceSession>(
      API_ENDPOINTS.tourOperations.managedSessionComplete(groupId, sessionId),
      exceptionReason ? { exception_reason: exceptionReason } : {},
    );
    return data;
  },

  publishMyAttendanceCloseoutCheckpoint: async ({
    groupId,
    sessionId,
    checkpoint,
  }: {
    groupId: string;
    sessionId: string;
    checkpoint: AttendanceCloseoutCheckpoint;
  }): Promise<AttendanceCloseoutCheckpoint & { reported_at: string }> => {
    const { data } = await apiClient.put<AttendanceCloseoutCheckpoint & { reported_at: string }>(
      API_ENDPOINTS.tourOperations.mySessionCloseoutCheckpoint(groupId, sessionId),
      checkpoint,
    );
    return data;
  },

  managedAttendanceCloseoutStatus: async (
    groupId: string,
    sessionId: string,
  ): Promise<AttendanceCloseoutStatus> => {
    const { data } = await apiClient.get<AttendanceCloseoutStatus>(
      API_ENDPOINTS.tourOperations.managedSessionCloseout(groupId, sessionId),
    );
    return data;
  },

  createManagedAttendanceSession: async ({
    groupId,
    name,
  }: {
    groupId: string;
    name: string;
  }): Promise<AttendanceSession> => {
    const { data } = await apiClient.post<AttendanceSession>(
      API_ENDPOINTS.tourOperations.managedSessions(groupId),
      { name },
    );
    return data;
  },

  groupAttendanceOverview: async (groupId: string): Promise<GroupAttendanceOverview> => {
    const { data } = await apiClient.get<GroupAttendanceOverview>(API_ENDPOINTS.tourOperations.groupAttendance(groupId));
    return data;
  },

  groupAttendanceSummary: async ({
    groupId,
    previous,
    signal,
  }: {
    groupId: string;
    previous?: GroupAttendanceSummary;
    signal?: AbortSignal;
  }): Promise<GroupAttendanceSummary> => {
    const response = await apiClient.get<GroupAttendanceSummary>(
      API_ENDPOINTS.tourOperations.groupAttendanceSummary(groupId),
      {
        headers: previous
          ? { "If-None-Match": `"${previous.revision}"` }
          : undefined,
        signal,
        validateStatus: (status) => status === 200 || status === 304,
      },
    );
    if (response.status === 304) {
      if (!previous) {
        throw new Error("Attendance summary returned no data without a local revision");
      }
      return previous;
    }
    return response.data;
  },

  groupAttendanceMissingPassengers: async ({
    groupId,
    sessionId,
    revision,
    cursor,
    search,
    limit = 50,
    signal,
  }: {
    groupId: string;
    sessionId: string;
    revision: string;
    cursor?: string | null;
    search?: string;
    limit?: number;
    signal?: AbortSignal;
  }): Promise<AttendanceMissingPassengersPage> => {
    const { data } = await apiClient.get<AttendanceMissingPassengersPage>(
      API_ENDPOINTS.tourOperations.groupAttendanceMissing(groupId, sessionId),
      {
        params: {
          revision,
          cursor: cursor || undefined,
          search: search || undefined,
          limit,
        },
        signal,
      },
    );
    return data;
  },

  groupQrCodes: async (groupId: string): Promise<GroupPassengerQrCodes> => {
    const { data } = await apiClient.get<GroupPassengerQrCodes>(API_ENDPOINTS.tourOperations.groupQrCodes(groupId));
    return data;
  },

  qrDeliveryPreview: async (groupId: string): Promise<QrDeliveryPreview> => {
    const { data } = await apiClient.get<QrDeliveryPreview>(
      API_ENDPOINTS.tourOperations.groupQrWhatsAppPreview(groupId),
    );
    return data;
  },

  sendQrBroadcast: async (
    groupId: string,
    body: { qr_token_ids: string[]; message_content: string },
  ): Promise<SendQrBroadcastResponse> => {
    const { data } = await apiClient.post<SendQrBroadcastResponse>(
      API_ENDPOINTS.tourOperations.groupQrWhatsAppSend(groupId),
      body,
    );
    return data;
  },

  generatePassengerQr: async (groupId: string, passengerId: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.post<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQr(groupId, passengerId));
    return data;
  },

  regeneratePassengerQr: async (groupId: string, passengerId: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.post<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrRegenerate(groupId, passengerId));
    return data;
  },

  revokePassengerQr: async (groupId: string, passengerId: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.post<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrRevoke(groupId, passengerId));
    return data;
  },

  setPassengerQrActive: async (groupId: string, passengerId: string, isActive: boolean): Promise<PassengerQrToken> => {
    const { data } = await apiClient.patch<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrActive(groupId, passengerId), {
      is_active: isActive,
    });
    return data;
  },

  setPassengerQrExpiration: async (groupId: string, passengerId: string, expiresAt: string): Promise<PassengerQrToken> => {
    const { data } = await apiClient.patch<PassengerQrToken>(API_ENDPOINTS.tourOperations.passengerQrExpiration(groupId, passengerId), {
      expires_at: expiresAt,
    });
    return data;
  },
};

function getDeviceId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const key = "passdetection-coordinator-device-id";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const next = crypto.randomUUID();
  window.localStorage.setItem(key, next);
  return next;
}
