import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePrivateMutation } from "@/hooks/use-private-mutation";
import { QUERY_KEYS } from "@/constants";
import { operationsApi, type StaffAccount } from "../api/operations.api";
import {
  MANAGED_ACCOUNTS_QUERY_KEY,
  STAFF_ACCOUNTS_QUERY_KEY,
  STAFF_ACCESS_QUERY_KEY,
} from "./operations-query-scope";

export function useStaffAccessAccounts() {
  return useQuery({
    queryKey: STAFF_ACCESS_QUERY_KEY,
    queryFn: operationsApi.staffAccessAccounts,
  });
}

export function useCreateStaff() {
  const queryClient = useQueryClient();

  return usePrivateMutation({
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

  return usePrivateMutation({
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
    resetPassword: usePrivateMutation({
      mutationFn: (accountId: string) =>
        operationsApi.resetManagedAccountPassword(accountId),
      onSuccess: refresh,
    }),
    resetMfa: usePrivateMutation({
      mutationFn: (accountId: string) => operationsApi.resetManagedAccountMfa(accountId),
      onSuccess: refresh,
    }),
    revokeSessions: usePrivateMutation({
      mutationFn: (accountId: string) => operationsApi.revokeManagedAccountSessions(accountId),
      onSuccess: refresh,
    }),
    setStatus: usePrivateMutation({
      mutationFn: ({ accountId, isActive }: { accountId: string; isActive: boolean }) =>
        operationsApi.setManagedAccountStatus(accountId, isActive),
      onSuccess: refresh,
    }),
    deleteAccount: usePrivateMutation({
      mutationFn: (accountId: string) => operationsApi.deleteManagedAccount(accountId),
      onSuccess: refresh,
    }),
  };
}
