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
  status: string;
  coordinator_id: string | null;
  coordinator_name: string | null;
  qr_payload?: string | null;
}

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
  coordinator_id: string | null;
  coordinator_name: string | null;
  qr_payload: string;
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
};
