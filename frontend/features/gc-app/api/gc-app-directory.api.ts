import apiClient from "@/lib/api/client";
import type { GcAgencyReference, GcCompanyReference, GcPage, GcPageParams } from "../types";
import type { GcMutationRequestConfig, PageEnvelope } from "./gc-app-wire.types";
import { capturePrivateOperationOwner } from "@/lib/api/request-owner";
import {
  ROOT,
  AGENCY_DIRECTORY_PAGE_SIZE,
  MAX_AGENCY_DIRECTORY_ITEMS,
  asPage,
  toOffsetParams,
  agencyParams,
  mapBounded,
} from "./gc-app-transport";

export const gcAppDirectoryApi = {
  listAgencies: async (signal?: AbortSignal): Promise<GcAgencyReference[]> => {
    const owner = capturePrivateOperationOwner();
    type AgencyPage = {
      items: GcAgencyReference[];
      total: number;
      offset: number;
      limit: number;
    };
    const { data: first } = await apiClient.get<AgencyPage>(`${ROOT}/agencies`, {
      ...owner.requestConfig,
      params: { offset: 0, limit: AGENCY_DIRECTORY_PAGE_SIZE },
      signal,
    });
    owner.assertCurrent();
    if (first.total > MAX_AGENCY_DIRECTORY_ITEMS) {
      throw new Error(
        "The agency directory is too large to load safely. Use an agency search before continuing.",
      );
    }
    const offsets = Array.from(
      { length: Math.max(0, Math.ceil(first.total / first.limit) - 1) },
      (_value, index) => (index + 1) * first.limit,
    );
    const remaining = await mapBounded(offsets, 4, async (offset) => {
      owner.assertCurrent();
      const { data } = await apiClient.get<AgencyPage>(`${ROOT}/agencies`, {
        ...owner.requestConfig,
        params: { offset, limit: first.limit },
        signal,
      });
      owner.assertCurrent();
      return data.items;
    });
    owner.assertCurrent();
    return [...first.items, ...remaining.flat()]
      .filter((agency) => agency.is_active)
      .slice(0, first.total);
  },

  searchCompanies: async (
    agencyId: string | null,
    params: GcPageParams,
    signal?: AbortSignal,
  ): Promise<GcPage<GcCompanyReference>> => {
    const { data } = await apiClient.get<PageEnvelope<GcCompanyReference>>(
      `${ROOT}/client-organizations/search`,
      {
        params: {
          ...toOffsetParams(params),
          agency_id: agencyId ?? undefined,
        },
        signal,
      },
    );
    return asPage(data, params);
  },

  createClientOrganization: async (
    agencyId: string | null,
    name: string, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcCompanyReference> => {
    const { data } = await apiClient.post<GcCompanyReference>(
      `${ROOT}/client-organizations`,
      { name },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return data;
  },

  removeClientOrganization: async (
    agencyId: string | null,
    organizationId: string, requestConfig?: GcMutationRequestConfig,
  ): Promise<void> => {
    await apiClient.delete(`${ROOT}/client-organizations/${organizationId}`, { ...requestConfig,
      params: agencyParams(agencyId),
    });
  },
};
