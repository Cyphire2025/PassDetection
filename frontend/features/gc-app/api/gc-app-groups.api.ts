import apiClient from "@/lib/api/client";
import type {
  GcAppControlPatch,
  GcAppGroupControl,
  GcAppGroupFilters,
  GcCompanyReference,
  GcGroupReference,
  GcPage,
  GcPageParams,
} from "../types";
import type { GcMutationRequestConfig, PageEnvelope, RawGroup, RawGroupAccess } from "./gc-app-wire.types";
import { capturePrivateOperationOwner } from "@/lib/api/request-owner";
import { ROOT, asPage, toOffsetParams, agencyParams, mapBounded } from "./gc-app-transport";
import { normalizeGroup, normalizeControl, fullControlBody } from "./gc-app-account-mappers";

export const gcAppGroupsApi = {
  searchGroups: async (
    agencyId: string | null,
    params: GcPageParams & { eligible_only?: boolean },
    signal?: AbortSignal,
  ): Promise<GcPage<GcGroupReference>> => {
    const { data } = await apiClient.get<PageEnvelope<RawGroup>>(
      `${ROOT}/groups`,
      {
        params: {
          ...toOffsetParams(params),
          agency_id: agencyId ?? undefined,
          eligible_only: params.eligible_only || undefined,
          unconfigured_only: params.eligible_only || undefined,
        },
        signal,
      },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map(normalizeGroup) };
  },

  listGroups: async (
    agencyId: string | null,
    params: GcAppGroupFilters,
    signal?: AbortSignal,
  ): Promise<GcPage<GcAppGroupControl>> => {
    const owner = capturePrivateOperationOwner();
    const { data } = await apiClient.get<PageEnvelope<RawGroup>>(`${ROOT}/groups`, {
      ...owner.requestConfig,
      params: {
        ...toOffsetParams(params),
        agency_id: agencyId ?? undefined,
        configured_only: true,
        availability: params.availability === "all" ? undefined : params.availability,
        lifecycle_status: params.lifecycle === "all" ? undefined : params.lifecycle,
      },
      signal,
    });
    owner.assertCurrent();
    const page = asPage(data, params);
    const items = await mapBounded(page.items, 4, async (group) => {
      owner.assertCurrent();
      if (group.access) return normalizeControl(group.access, group);
      const response = await apiClient.get<RawGroupAccess>(`${ROOT}/groups/${group.id}`, {
        ...owner.requestConfig,
        params: agencyParams(agencyId),
        signal,
      });
      owner.assertCurrent();
      return normalizeControl(response.data, group);
    });
    owner.assertCurrent();
    return { ...page, items };
  },

  getGroupControl: async (
    agencyId: string | null,
    groupId: string,
    signal?: AbortSignal,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.get<RawGroupAccess>(`${ROOT}/groups/${groupId}`, {
      params: agencyParams(agencyId),
      signal,
    });
    return normalizeControl(data);
  },

  addGroup: async (
    agencyId: string | null,
    group: GcGroupReference,
    company: GcCompanyReference, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.put<RawGroupAccess>(`${ROOT}/groups/${group.id}`, {
      client_organization_id: company.id,
      enabled: true,
      passenger_access_enabled: true,
      client_manager_access_enabled: true,
      coordinator_access_enabled: true,
      access_starts_at: null,
      access_expires_at: null,
      expected_revision: group.gc_revision ?? null,
      ...(group.gc_removed_at ? { restore_removed: true } : {}),
    }, { ...requestConfig, params: agencyParams(agencyId) });
    const normalized = normalizeControl(data, {
      id: group.id,
      name: group.name,
      destination: group.destination,
      travel_date: group.start_date,
      return_date: group.end_date,
      lifecycle_status: group.lifecycle,
      gc_enabled: true,
      client_organization_id: company.id,
      client_organization_name: company.name,
    });
    return { ...normalized, organization_id: company.id, company };
  },

  removeGroup: async (agencyId: string | null, control: GcAppGroupControl, requestConfig?: GcMutationRequestConfig): Promise<void> => {
    await apiClient.delete(
      `${ROOT}/groups/${control.id}/app-setup`,
      { ...requestConfig, params: agencyParams(agencyId, { expected_revision: control.revision }) },
    );
  },

  updateGroupControl: async (
    agencyId: string | null,
    control: GcAppGroupControl,
    patch: GcAppControlPatch, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.put<RawGroupAccess>(
      `${ROOT}/groups/${control.id}`,
      fullControlBody(control, patch),
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeControl(data, {
      id: control.id,
      name: control.name,
      destination: control.destination,
      travel_date: control.start_date,
      return_date: control.end_date,
      lifecycle_status: control.lifecycle,
      gc_enabled: data.enabled,
      client_organization_id: control.organization_id,
      client_organization_name: control.company?.name ?? null,
    });
  },

  setMyPhotosEnabled: async (
    agencyId: string | null,
    control: GcAppGroupControl,
    enabled: boolean, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcAppGroupControl> => {
    const { data } = await apiClient.put<RawGroupAccess>(
      `${ROOT}/groups/${control.id}/features/my-photos`,
      { enabled, expected_revision: control.revision },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeControl(data, {
      id: control.id,
      name: control.name,
      destination: control.destination,
      travel_date: control.start_date,
      return_date: control.end_date,
      lifecycle_status: control.lifecycle,
      gc_enabled: data.enabled,
      client_organization_id: control.organization_id,
      client_organization_name: control.company?.name ?? null,
    });
  },

  revokeGroupAccess: async (agencyId: string | null, groupId: string, requestConfig?: GcMutationRequestConfig): Promise<void> => {
    await apiClient.delete(`${ROOT}/groups/${groupId}`, { ...requestConfig, params: agencyParams(agencyId) });
  },
};
