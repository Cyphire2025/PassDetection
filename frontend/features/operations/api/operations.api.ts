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
  role: "agency_staff";
  agency_id: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  created_groups: ManagerGroupAccess[];
  assigned_groups: ManagerGroupAccess[];
}

export interface ManagerGroupAccess {
  id: string;
  name: string;
  status: string;
  created_by_user_id: string | null;
}

export interface ManagedAccount {
  id: string;
  full_name: string;
  email: string;
  role: "agency_staff" | "agency_coordinator";
  agency_id: string | null;
  agency_name: string | null;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface DeleteManagedAccountResponse {
  account_id: string;
  result: "deleted" | "access_removed" | string;
  preserved_history: boolean;
}

export interface CreateManagerRequest {
  full_name: string;
  email: string;
  password: string;
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
  coordinator_id: string;
  coordinator_name: string;
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
}

export interface GroupAttendanceOverview {
  group_id: string;
  group_name: string;
  sessions: AttendanceSessionSummary[];
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

  managedAccounts: async (): Promise<ManagedAccount[]> => {
    const { data } = await apiClient.get<ManagedAccount[]>(API_ENDPOINTS.admin.accounts);
    return data;
  },

  resetManagedAccountPassword: async (accountId: string, password: string): Promise<ManagedAccount> => {
    const { data } = await apiClient.post<ManagedAccount>(API_ENDPOINTS.admin.accountPassword(accountId), { password });
    return data;
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
    room_count?: number;
  }): Promise<RoomingHotel> => {
    const { data } = await apiClient.patch<RoomingHotel>(API_ENDPOINTS.rooming.hotel(hotelId), body);
    return data;
  },

  generateRoomingRooms: async (hotelId: string, body: {
    room_type: RoomType;
    count: number;
    starting_number?: number;
    allocation_tag: Exclude<RoomingTag, "unspecified">;
  }): Promise<RoomingRoom[]> => {
    const { data } = await apiClient.post<RoomingRoom[]>(API_ENDPOINTS.rooming.generateRooms(hotelId), body);
    return data;
  },

  updateRoomingAllocation: async (hotelId: string, passengerId: string, body: {
    room_id: string | null;
    allocation_tag: Exclude<RoomingTag, "mixed" | "vip">;
    special_requests: RoomingSpecialRequest[];
    roommate_notes?: string | null;
  }): Promise<RoomingWorkspace> => {
    const { data } = await apiClient.put<RoomingWorkspace>(API_ENDPOINTS.rooming.allocation(hotelId, passengerId), body);
    return data;
  },

  deleteRoomingRoom: async (roomId: string): Promise<void> => {
    await apiClient.delete(API_ENDPOINTS.rooming.room(roomId));
  },

  updateRoomingRoom: async (roomId: string, body: {
    room_number: string;
    room_type: RoomType;
    allocation_tag: Exclude<RoomingTag, "unspecified">;
    roommate_notes?: string | null;
    is_saved: boolean;
  }): Promise<RoomingRoom> => {
    const { data } = await apiClient.patch<RoomingRoom>(API_ENDPOINTS.rooming.room(roomId), body);
    return data;
  },

  updateRoomingRoomOrder: async (hotelId: string, roomIds: string[]): Promise<RoomingRoom[]> => {
    const { data } = await apiClient.put<RoomingRoom[]>(API_ENDPOINTS.rooming.roomOrder(hotelId), { room_ids: roomIds });
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

  createMyAttendanceSession: async (groupId: string, name: string): Promise<AttendanceSession> => {
    const { data } = await apiClient.post<AttendanceSession>(API_ENDPOINTS.tourOperations.myGroupSessions(groupId), {
      name,
    });
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
    syncSource,
  }: {
    sessionId: string;
    qrPayload: string;
    clientEventId: string;
    scannedAt?: string;
    deviceId?: string;
    syncSource?: "online" | "offline";
  }): Promise<AttendanceScanResponse> => {
    const { data } = await apiClient.post<AttendanceScanResponse>(API_ENDPOINTS.tourOperations.mySessionScan(sessionId), {
      qr_payload: qrPayload,
      client_event_id: clientEventId,
      scanned_at: scannedAt,
      device_id: deviceId,
      sync_source: syncSource ?? "online",
    });
    return data;
  },

  completeMyAttendanceSession: async (sessionId: string): Promise<AttendanceSession> => {
    const { data } = await apiClient.put<AttendanceSession>(API_ENDPOINTS.tourOperations.mySessionComplete(sessionId));
    return data;
  },

  groupAttendanceOverview: async (groupId: string): Promise<GroupAttendanceOverview> => {
    const { data } = await apiClient.get<GroupAttendanceOverview>(API_ENDPOINTS.tourOperations.groupAttendance(groupId));
    return data;
  },

  groupQrCodes: async (groupId: string): Promise<GroupPassengerQrCodes> => {
    const { data } = await apiClient.get<GroupPassengerQrCodes>(API_ENDPOINTS.tourOperations.groupQrCodes(groupId));
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
