import apiClient from "@/lib/api/client";
import type { AnnouncementInput, GcAnnouncement, GcPage, GcPageParams } from "../types";
import type { GcMutationRequestConfig, PageEnvelope, RawAnnouncement } from "./gc-app-wire.types";
import { ROOT, asPage, toOffsetParams, agencyParams } from "./gc-app-transport";
import { normalizeAnnouncement } from "./gc-app-content-mappers";

export const gcAppAnnouncementsApi = {
  listAnnouncements: async (
    agencyId: string | null,
    groupId: string,
    params: GcPageParams,
    signal?: AbortSignal,
  ): Promise<GcPage<GcAnnouncement>> => {
    const { data } = await apiClient.get<PageEnvelope<RawAnnouncement>>(
      `${ROOT}/groups/${groupId}/announcements/page`,
      { params: agencyParams(agencyId, toOffsetParams(params)), signal },
    );
    const page = asPage(data, params);
    return { ...page, items: page.items.map(normalizeAnnouncement) };
  },

  createAnnouncement: async (
    agencyId: string | null,
    groupId: string,
    body: AnnouncementInput,
    expectedAccessRevision: number, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcAnnouncement> => {
    const { data } = await apiClient.post<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements`,
      {
        title: body.title,
        message: body.body,
        priority: body.priority,
        available_from: body.available_from,
        available_until: body.available_until,
        expected_access_revision: expectedAccessRevision,
        publish: body.publish,
      },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeAnnouncement(data);
  },

  updateAnnouncement: async (
    agencyId: string | null,
    groupId: string,
    announcementId: string,
    body: AnnouncementInput,
    expectedAccessRevision: number, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcAnnouncement> => {
    const { data } = await apiClient.put<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements/${announcementId}`,
      {
        title: body.title,
        message: body.body,
        priority: body.priority,
        available_from: body.available_from,
        available_until: body.available_until,
        expected_access_revision: expectedAccessRevision,
        publish: body.publish,
      },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeAnnouncement(data);
  },

  setAnnouncementPublished: async (
    agencyId: string | null,
    groupId: string,
    announcementId: string,
    published: boolean, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcAnnouncement> => {
    const { data } = await apiClient.post<RawAnnouncement>(
      `${ROOT}/groups/${groupId}/announcements/${announcementId}/${published ? "publish" : "unpublish"}`,
      undefined,
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeAnnouncement(data);
  },

  deleteAnnouncement: async (
    agencyId: string | null,
    groupId: string,
    announcementId: string, requestConfig?: GcMutationRequestConfig,
  ): Promise<void> => {
    await apiClient.delete(`${ROOT}/groups/${groupId}/announcements/${announcementId}`, { ...requestConfig,
      params: agencyParams(agencyId),
    });
  },
};
