import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { QUERY_KEYS } from "@/constants";
import { operationsApi, type StaffAccount } from "../api/operations.api";

export function useAdminOverview() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.adminOverview,
    queryFn: operationsApi.adminOverview,
  });
}

export function useManagers() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.managers,
    queryFn: operationsApi.managers,
  });
}

export function useAdminGroups() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.adminGroups,
    queryFn: operationsApi.adminGroups,
  });
}

export function useCreateManager() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.createManager,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
    },
  });
}

export function useDeleteManager() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ managerId, deleteOwnedData }: { managerId: string; deleteOwnedData: boolean }) =>
      operationsApi.deleteManager(managerId, deleteOwnedData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.adminGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function useAssignManagerGroups() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ managerId, groupIds }: { managerId: string; groupIds: string[] }) =>
      operationsApi.assignManagerGroups(managerId, groupIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.adminGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

const MANAGED_ACCOUNTS_QUERY_KEY = ["operations", "managed-accounts"] as const;
const STAFF_ACCOUNTS_QUERY_KEY = ["operations", "staff-accounts"] as const;
const STAFF_ACCESS_QUERY_KEY = ["operations", "staff-access"] as const;

export function useManagedAccounts() {
  return useQuery({
    queryKey: MANAGED_ACCOUNTS_QUERY_KEY,
    queryFn: operationsApi.managedAccounts,
    retry: false,
  });
}

export function useStaffAccounts() {
  return useQuery({
    queryKey: STAFF_ACCOUNTS_QUERY_KEY,
    queryFn: operationsApi.staffAccounts,
    retry: false,
  });
}

export function useStaffAccessAccounts() {
  return useQuery({
    queryKey: STAFF_ACCESS_QUERY_KEY,
    queryFn: operationsApi.staffAccessAccounts,
  });
}

export function useCreateStaff() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.createStaff,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MANAGED_ACCOUNTS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: STAFF_ACCOUNTS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: STAFF_ACCESS_QUERY_KEY });
    },
  });
}

export function useAssignStaffGroups() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ staffId, groupIds }: { staffId: string; groupIds: string[] }) =>
      operationsApi.assignStaffGroups(staffId, groupIds),
    onSuccess: (updatedStaff) => {
      queryClient.setQueryData<StaffAccount[]>(STAFF_ACCESS_QUERY_KEY, (accounts) =>
        accounts?.map((account) => account.id === updatedStaff.id ? updatedStaff : account),
      );
      queryClient.invalidateQueries({ queryKey: STAFF_ACCESS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.adminGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.stats });
    },
  });
}

export function useManagedAccountActions() {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: MANAGED_ACCOUNTS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: STAFF_ACCOUNTS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: STAFF_ACCESS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.managers });
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroups });
  };

  return {
    resetPassword: useMutation({
      mutationFn: ({ accountId, password }: { accountId: string; password: string }) =>
        operationsApi.resetManagedAccountPassword(accountId, password),
      onSuccess: refresh,
    }),
    revokeSessions: useMutation({
      mutationFn: (accountId: string) => operationsApi.revokeManagedAccountSessions(accountId),
      onSuccess: refresh,
    }),
    setStatus: useMutation({
      mutationFn: ({ accountId, isActive }: { accountId: string; isActive: boolean }) =>
        operationsApi.setManagedAccountStatus(accountId, isActive),
      onSuccess: refresh,
    }),
    deleteAccount: useMutation({
      mutationFn: (accountId: string) => operationsApi.deleteManagedAccount(accountId),
      onSuccess: refresh,
    }),
  };
}

export function useAnalyticsSummary(days = 30) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.analytics({ days }),
    queryFn: () => operationsApi.analyticsSummary(days),
  });
}

export function useAuditLogs() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.auditLogs(),
    queryFn: operationsApi.auditLogs,
    refetchInterval: 30_000,
  });
}

export function useTourOperationsArchitecture() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourOperationsArchitecture,
    queryFn: operationsApi.tourOperationsArchitecture,
  });
}

export function useTourCoordinators() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourCoordinators,
    queryFn: operationsApi.tourCoordinators,
    retry: false,
  });
}

export function useCreateTourCoordinator() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.createTourCoordinator,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    },
  });
}

export function useTourGroups() {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourGroups,
    queryFn: operationsApi.tourGroups,
    retry: false,
  });
}

const roomingWorkspaceKey = (groupId: string) => ["operations", "rooming", groupId] as const;

export function useRoomingWorkspace(groupId: string) {
  return useQuery({
    queryKey: roomingWorkspaceKey(groupId),
    queryFn: () => operationsApi.roomingWorkspace(groupId),
    retry: false,
  });
}

export function useRoomingPriorityFields(groupId: string) {
  return useQuery({
    queryKey: [...roomingWorkspaceKey(groupId), "priority-fields"],
    queryFn: () => operationsApi.roomingPriorityFields(groupId),
    enabled: Boolean(groupId),
    staleTime: 30_000,
    retry: false,
  });
}

export function useRoomingActions(groupId: string) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: roomingWorkspaceKey(groupId) });
  const applyWorkspace = (workspace: Awaited<ReturnType<typeof operationsApi.roomingWorkspace>>) => {
    queryClient.setQueryData(roomingWorkspaceKey(groupId), workspace);
  };
  const applyWorkspaceAndRefreshCheckins = (
    workspace: Awaited<ReturnType<typeof operationsApi.roomingWorkspace>>,
  ) => {
    applyWorkspace(workspace);
    queryClient.invalidateQueries({ queryKey: ["rooming", "checkins"] });
  };

  return {
    createHotel: useMutation({
      mutationFn: (body: { hotel_name: string; city?: string; check_in_date?: string; check_out_date?: string }) =>
        operationsApi.createRoomingHotel(groupId, body),
      onSuccess: refresh,
    }),
    updateHotel: useMutation({
      mutationFn: ({ hotelId, ...body }: {
        hotelId: string;
        hotel_name: string;
        city?: string;
        check_in_date?: string;
        check_out_date?: string;
      }) => operationsApi.updateRoomingHotel(hotelId, body),
      onSuccess: refresh,
    }),
    selectHotelPassengers: useMutation({
      mutationFn: ({ hotelId, passengerIds, mode = "add" }: {
        hotelId: string;
        passengerIds: string[];
        mode?: "replace" | "add" | "remove";
      }) => operationsApi.updateRoomingPassengerSelection(hotelId, {
        passenger_ids: passengerIds,
        mode,
      }),
      onSuccess: applyWorkspaceAndRefreshCheckins,
    }),
    setPassengerVip: useMutation({
      mutationFn: ({ hotelId, passengerIds, isVip }: {
        hotelId: string;
        passengerIds: string[];
        isVip: boolean;
      }) => operationsApi.updateRoomingVip(hotelId, {
        passenger_ids: passengerIds,
        is_vip: isVip,
      }),
      onSuccess: applyWorkspaceAndRefreshCheckins,
    }),
    autoAllocate: useMutation({
      mutationFn: ({ hotelId, priorityFields }: {
        hotelId: string;
        priorityFields: string[];
      }) => operationsApi.autoAllocateRoomingHotel(hotelId, {
        priority_fields: priorityFields,
      }),
      onSuccess: applyWorkspaceAndRefreshCheckins,
    }),
  };
}

export function useAssignTourGroupCoordinators() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, coordinatorIds }: { groupId: string; coordinatorIds: string[] }) =>
      operationsApi.assignTourGroupCoordinators(groupId, coordinatorIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    },
  });
}

export function useTourGroupPassengers(groupId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"),
    queryFn: () => operationsApi.tourGroupPassengers(groupId as string),
    enabled: Boolean(groupId),
    retry: false,
  });
}

export function useAssignTourGroupPassengers() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      groupId,
      passengerIds,
      coordinatorId,
    }: {
      groupId: string;
      passengerIds: string[];
      coordinatorId: string | null;
    }) => operationsApi.assignTourGroupPassengers(groupId, passengerIds, coordinatorId),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroupPassengers(variables.groupId) });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroups });
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourCoordinators });
    },
  });
}

export function useMyTourGroups(enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroups, "mine"],
    queryFn: operationsApi.myTourGroups,
    enabled,
    retry: false,
  });
}

export function useMyTourGroupPassengers(groupId: string | null, enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"), "mine"],
    queryFn: () => operationsApi.myTourGroupPassengers(groupId as string),
    enabled: enabled && Boolean(groupId),
    retry: false,
  });
}

export function useMyTourGroupPassenger(groupId: string | null, passengerId: string | null, enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"), "mine", passengerId ?? "none"],
    queryFn: () => operationsApi.myTourGroupPassenger(groupId as string, passengerId as string),
    enabled: enabled && Boolean(groupId) && Boolean(passengerId),
    retry: false,
  });
}

export function useCreateMyAttendanceSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, name }: { groupId: string; name: string }) =>
      operationsApi.createMyAttendanceSession(groupId, name),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(variables.groupId), "sessions"] });
    },
  });
}

export function useMyAttendanceSessions(groupId: string | null, enabled = true) {
  return useQuery({
    queryKey: [...QUERY_KEYS.operations.tourGroupPassengers(groupId ?? "none"), "sessions"],
    queryFn: () => operationsApi.myAttendanceSessions(groupId as string),
    enabled: enabled && Boolean(groupId),
    retry: false,
    refetchInterval: 1_500,
    refetchIntervalInBackground: false,
    staleTime: 500,
  });
}

export function useMyAttendanceSessionDetails(sessionId: string | null, enabled = true) {
  return useQuery({
    queryKey: ["operations", "tour-operations", "coordinator", "sessions", sessionId ?? "none", "details"],
    queryFn: () => operationsApi.myAttendanceSessionDetails(sessionId as string),
    enabled: enabled && Boolean(sessionId),
    retry: false,
  });
}

export function useScanMyAttendanceSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: operationsApi.scanMyAttendanceSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroups });
    },
  });
}

export function useCompleteMyAttendanceSession() {
  return useMutation({
    mutationFn: operationsApi.completeMyAttendanceSession,
  });
}

export function useGroupAttendanceOverview(groupId: string) {
  return useQuery({
    queryKey: ["operations", "tour-operations", "groups", groupId, "attendance"],
    queryFn: () => operationsApi.groupAttendanceOverview(groupId),
    // This response includes the missing-passenger roster for each activity.
    // Keep its existing low-frequency office refresh; coordinator devices use
    // the lightweight 1.5-second shared-session summary above.
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

export function useGroupQrCodes(groupId: string) {
  return useQuery({
    queryKey: QUERY_KEYS.operations.tourGroupQrCodes(groupId),
    queryFn: () => operationsApi.groupQrCodes(groupId),
    retry: false,
  });
}

export function useQrDeliveryPreview(groupId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["operations", "tour-operations", "groups", groupId, "qr-whatsapp-preview"],
    queryFn: () => operationsApi.qrDeliveryPreview(groupId),
    enabled,
    retry: false,
  });
}

export function useSendQrBroadcast(groupId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { qr_token_ids: string[]; message_content: string }) =>
      operationsApi.sendQrBroadcast(groupId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["operations", "tour-operations", "groups", groupId, "qr-whatsapp-preview"],
      });
    },
  });
}

export function usePassengerQrLifecycle(groupId: string) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: QUERY_KEYS.operations.tourGroupQrCodes(groupId) });
  const refreshPassenger = (passengerId: string) => {
    void refresh();
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.passports.detail(passengerId) });
  };

  return {
    generate: useMutation({
      mutationFn: (passengerId: string) => operationsApi.generatePassengerQr(groupId, passengerId),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
    regenerate: useMutation({
      mutationFn: (passengerId: string) => operationsApi.regeneratePassengerQr(groupId, passengerId),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
    revoke: useMutation({
      mutationFn: (passengerId: string) => operationsApi.revokePassengerQr(groupId, passengerId),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
    setActive: useMutation({
      mutationFn: ({ passengerId, isActive }: { passengerId: string; isActive: boolean }) =>
        operationsApi.setPassengerQrActive(groupId, passengerId, isActive),
      onSuccess: (_data, variables) => refreshPassenger(variables.passengerId),
    }),
    expire: useMutation({
      mutationFn: (passengerId: string) =>
        operationsApi.setPassengerQrExpiration(groupId, passengerId, new Date().toISOString()),
      onSuccess: (_data, passengerId) => refreshPassenger(passengerId),
    }),
  };
}
