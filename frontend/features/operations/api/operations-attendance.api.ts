import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { ownerBoundRequestConfig } from "@/lib/api/request-owner";
import type {
  AttendanceSession,
  AttendanceScanResponse,
  AttendanceSessionDetails,
  AttendanceScanBatchResponse,
  AttendanceCloseoutCheckpoint,
  AttendanceCloseoutStatus,
  GroupAttendanceOverview,
  GroupAttendanceSummary,
  AttendanceMissingPassengersPage,
} from "./operations-attendance.types";

export const attendanceOperationsApi = {
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
    expectedOwnerUserId,
  }: {
    sessionId: string;
    qrPayload: string;
    clientEventId: string;
    scannedAt?: string;
    deviceId?: string;
    runtimeId?: string;
    syncSource?: "online" | "offline";
    expectedOwnerUserId?: string;
  }): Promise<AttendanceScanResponse> => {
    const { data } = await apiClient.post<AttendanceScanResponse>(API_ENDPOINTS.tourOperations.mySessionScan(sessionId), {
      qr_payload: qrPayload,
      client_event_id: clientEventId,
      scanned_at: scannedAt,
      device_id: deviceId,
      runtime_id: runtimeId,
      sync_source: syncSource ?? "online",
    }, ownerBoundRequestConfig(expectedOwnerUserId));
    return data;
  },

  scanMyAttendanceSessionBatch: async ({
    sessionId,
    batchId,
    scans,
    expectedOwnerUserId,
  }: {
    sessionId: string;
    batchId: string;
    expectedOwnerUserId?: string;
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
      ownerBoundRequestConfig(expectedOwnerUserId),
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
    expectedOwnerUserId,
  }: {
    groupId: string;
    sessionId: string;
    checkpoint: AttendanceCloseoutCheckpoint;
    expectedOwnerUserId?: string;
  }): Promise<AttendanceCloseoutCheckpoint & { reported_at: string }> => {
    const { data } = await apiClient.put<AttendanceCloseoutCheckpoint & { reported_at: string }>(
      API_ENDPOINTS.tourOperations.mySessionCloseoutCheckpoint(groupId, sessionId),
      checkpoint,
      ownerBoundRequestConfig(expectedOwnerUserId),
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
};
