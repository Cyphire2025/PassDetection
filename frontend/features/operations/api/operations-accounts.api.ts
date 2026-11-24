import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type {
  AdminOverview,
  ManagerAccount,
  ManagerGroupAccess,
  ManagedAccount,
  StaffAccount,
  DeleteManagedAccountResponse,
  CreateManagerRequest,
  CreateStaffRequest,
  DeleteManagerResponse,
} from "./operations-accounts.types";

export const accountsOperationsApi = {
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
};
