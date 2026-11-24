import apiClient from "@/lib/api/client";
import type {
  ClientManagerAccount,
  ClientManagerFilters,
  ClientManagerInput,
  ClientManagerSession,
  GcAppAccountStatus,
  GcPage,
  GcPageParams,
} from "../types";
import type {
  GcMutationRequestConfig,
  PageEnvelope,
  RawClientManager,
  RawClientManagerSession,
} from "./gc-app-wire.types";
import { assertRequestOwner, capturePrivateOperationOwner } from "@/lib/api/request-owner";
import { ROOT, asPage, toOffsetParams, agencyParams } from "./gc-app-transport";
import { normalizeClientManager } from "./gc-app-account-mappers";

export const gcAppManagersApi = {
  listClientManagers: async (
    agencyId: string | null,
    params: ClientManagerFilters,
    signal?: AbortSignal,
  ): Promise<GcPage<ClientManagerAccount>> => {
    const { data } = await apiClient.get<PageEnvelope<RawClientManager>>(
      `${ROOT}/client-managers`,
      {
        params: {
          ...toOffsetParams(params),
          agency_id: agencyId ?? undefined,
          status: params.status === "all" ? undefined : params.status,
          company_id: params.company_id || undefined,
        },
        signal,
      },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map(normalizeClientManager) };
  },

  createClientManager: async (agencyId: string | null, body: ClientManagerInput, requestConfig?: GcMutationRequestConfig): Promise<ClientManagerAccount> => {
    const { data } = await apiClient.post<RawClientManager>(`${ROOT}/client-managers`, {
      full_name: body.name,
      email: body.email,
      phone_number: body.phone_number,
      organization_id: body.company_id,
      group_ids: body.group_ids,
      return_temporary_password_once: false,
      invitation_flow: true,
      return_activation_token_once: true,
      force_password_change: false,
    }, { ...requestConfig, params: { agency_id: agencyId ?? undefined } });
    return normalizeClientManager(data);
  },

  updateClientManager: async (
    agencyId: string | null,
    managerId: string,
    current: ClientManagerAccount,
    body: ClientManagerInput, requestConfig?: GcMutationRequestConfig,
  ): Promise<ClientManagerAccount> => {
    const owner = requestConfig?.expectedOwnerUserId === undefined
      ? capturePrivateOperationOwner()
      : { requestConfig, assertCurrent: () => assertRequestOwner(requestConfig) };
    owner.assertCurrent();
    const { data: updatedProfile } = await apiClient.patch<RawClientManager>(
      `${ROOT}/client-managers/${managerId}`,
      {
        full_name: body.name,
        email: body.email,
        phone_number: body.phone_number,
        organization_id: body.company_id,
        expected_revision: current.revision,
      },
      { ...requestConfig, ...owner.requestConfig, params: agencyParams(agencyId) },
    );
    owner.assertCurrent();
    const { data: updatedGroups } = await apiClient.put<RawClientManager>(
      `${ROOT}/client-managers/${managerId}/groups`,
      { group_ids: body.group_ids, expected_revision: updatedProfile.revision },
      { ...requestConfig, ...owner.requestConfig, params: agencyParams(agencyId) },
    );
    owner.assertCurrent();
    return normalizeClientManager(updatedGroups);
  },

  setClientManagerStatus: async (
    agencyId: string | null,
    managerId: string,
    status: Exclude<GcAppAccountStatus, "deleted" | "invited">,
    revision: number, requestConfig?: GcMutationRequestConfig,
  ): Promise<ClientManagerAccount> => {
    const { data } = await apiClient.patch<RawClientManager>(
      `${ROOT}/client-managers/${managerId}/status`,
      { status, expected_revision: revision },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeClientManager(data);
  },

  resetClientManagerPassword: async (
    agencyId: string | null,
    managerId: string, requestConfig?: GcMutationRequestConfig,
  ): Promise<ClientManagerAccount> => {
    const { data } = await apiClient.post<RawClientManager>(
      `${ROOT}/client-managers/${managerId}/reset-password`,
      { issue_activation_link: true },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeClientManager(data);
  },

  revokeClientManagerSessions: async (agencyId: string | null, managerId: string, requestConfig?: GcMutationRequestConfig): Promise<void> => {
    await apiClient.post(
      `${ROOT}/client-managers/${managerId}/revoke-sessions`,
      undefined,
      { ...requestConfig, params: agencyParams(agencyId) },
    );
  },

  softDeleteClientManager: async (agencyId: string | null, managerId: string, requestConfig?: GcMutationRequestConfig): Promise<void> => {
    await apiClient.delete(`${ROOT}/client-managers/${managerId}`, { ...requestConfig,
      params: agencyParams(agencyId),
    });
  },

  listClientManagerSessions: async (
    agencyId: string | null,
    managerId: string,
    params: GcPageParams,
    signal?: AbortSignal,
  ): Promise<GcPage<ClientManagerSession>> => {
    const { data } = await apiClient.get<PageEnvelope<RawClientManagerSession>>(
      `${ROOT}/client-managers/${managerId}/sessions`,
      { params: agencyParams(agencyId, toOffsetParams(params)), signal },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map((session) => ({
      id: session.id,
      device_name: null,
      platform: session.platform,
      app_version: session.app_version,
      ip_address: null,
      created_at: session.created_at,
      last_seen_at: session.last_seen_at,
      revoked_at: session.revoked_at,
      // This endpoint describes another person's sessions; active is not our device.
      current: false,
      status: session.status,
      expires_at: session.expires_at,
    })) };
  },
};
