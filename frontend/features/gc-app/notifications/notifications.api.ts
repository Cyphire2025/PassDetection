import apiClient from "@/lib/api/client";
import type { NotificationBatch, NotificationDraft, NotificationDraftInput, NotificationPage, NotificationPreview, NotificationSendInput } from "./notification-types";

const ROOT = "/api/v1/gc-app/admin/notifications";
const scope = (agencyId: string) => ({ agency_id: agencyId });

export const notificationsApi = {
  listDrafts: async (agencyId: string, cursor: string | null, signal?: AbortSignal): Promise<NotificationPage<NotificationDraft>> => {
    const { data } = await apiClient.get<NotificationPage<NotificationDraft>>(ROOT, { params: { ...scope(agencyId), cursor: cursor ?? undefined, limit: 20 }, signal });
    return data;
  },
  getDraft: async (agencyId: string, id: string): Promise<NotificationDraft> => {
    const { data } = await apiClient.get<NotificationDraft>(`${ROOT}/${encodeURIComponent(id)}`, { params: scope(agencyId) });
    return data;
  },
  createDraft: async (agencyId: string, body: NotificationDraftInput): Promise<NotificationDraft> => {
    const { data } = await apiClient.post<NotificationDraft>(ROOT, body, { params: scope(agencyId) });
    return data;
  },
  updateDraft: async (agencyId: string, draft: NotificationDraft, body: NotificationDraftInput): Promise<NotificationDraft> => {
    const { data } = await apiClient.patch<NotificationDraft>(`${ROOT}/${encodeURIComponent(draft.id)}`, { ...body, expected_revision: draft.revision }, { params: scope(agencyId) });
    return data;
  },
  preview: async (agencyId: string, draft: NotificationDraft): Promise<NotificationPreview> => {
    const { data } = await apiClient.post<NotificationPreview>(`${ROOT}/${encodeURIComponent(draft.id)}/preview`, { expected_revision: draft.revision }, { params: scope(agencyId) });
    return data;
  },
  send: async (agencyId: string, draftId: string, body: NotificationSendInput): Promise<NotificationBatch> => {
    const { data } = await apiClient.post<NotificationBatch>(`${ROOT}/${encodeURIComponent(draftId)}/send`, body, { params: scope(agencyId) });
    return data;
  },
  byRequest: async (agencyId: string, requestId: string): Promise<NotificationBatch> => {
    const { data } = await apiClient.get<NotificationBatch>(`${ROOT}/batches/by-request/${encodeURIComponent(requestId)}`, { params: scope(agencyId) });
    return data;
  },
  getBatch: async (agencyId: string, batchId: string, signal?: AbortSignal): Promise<NotificationBatch> => {
    const { data } = await apiClient.get<NotificationBatch>(`${ROOT}/batches/${encodeURIComponent(batchId)}`, { params: scope(agencyId), signal });
    return data;
  },
  listBatches: async (agencyId: string, cursor: string | null, signal?: AbortSignal): Promise<NotificationPage<NotificationBatch>> => {
    const { data } = await apiClient.get<NotificationPage<NotificationBatch>>(`${ROOT}/batches`, { params: { ...scope(agencyId), cursor: cursor ?? undefined, limit: 20 }, signal });
    return data;
  },
};
