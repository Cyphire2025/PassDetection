import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { notificationsApi } from "./notifications.api";
import { agencyId, draft, preview, batch } from "./notification-test-fixtures";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
const root = "/api/v1/gc-app/admin/notifications";

describe("Authored notification API boundaries", () => {
  it("deletes only the selected saved revision within the agency", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue({ status: 204 });
    await notificationsApi.deleteDraft(agencyId, draft);
    expect(apiClient.delete).toHaveBeenCalledExactlyOnceWith(`${root}/${draft.id}`, { params: { agency_id: agencyId, expected_revision: draft.revision } });
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("saves draft text with explicit agency scope and no send request", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: draft });
    const input = { title: draft.title, body: draft.body, audience: draft.audience, group_ids: draft.group_ids };
    await notificationsApi.createDraft(agencyId, input);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(root, input, { params: { agency_id: agencyId } });
  });

  it("includes the current draft revision when editing or reviewing", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ data: draft });
    vi.mocked(apiClient.post).mockResolvedValue({ data: preview() });
    const input = { title: draft.title, body: "Edited text", audience: draft.audience, group_ids: draft.group_ids };
    await notificationsApi.updateDraft(agencyId, draft, input);
    await notificationsApi.preview(agencyId, draft);
    expect(apiClient.patch).toHaveBeenCalledWith(`${root}/${draft.id}`, { ...input, expected_revision: 1 }, { params: { agency_id: agencyId } });
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(`${root}/${draft.id}/preview`, { expected_revision: 1 }, { params: { agency_id: agencyId } });
  });

  it("preserves the exact request UUID and review payload across explicit retries", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce({ message: "response lost" }).mockResolvedValueOnce({ data: batch });
    const body = { request_id: batch.request_id, expected_revision: 1, preview_token: "review-token" };
    await expect(notificationsApi.send(agencyId, draft.id, body)).rejects.toMatchObject({ message: "response lost" });
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    await notificationsApi.send(agencyId, draft.id, body);
    expect(vi.mocked(apiClient.post).mock.calls[0]).toEqual(vi.mocked(apiClient.post).mock.calls[1]);
  });

  it("recovers prior acceptance with GET only, scoped to the agency", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: batch });
    expect(await notificationsApi.byRequest(agencyId, batch.request_id)).toEqual(batch);
    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith(`${root}/batches/by-request/${batch.request_id}`, { params: { agency_id: agencyId } });
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("bounds draft and batch history requests with cursor pagination", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { items: [], next_cursor: null } });
    const signal = new AbortController().signal;
    await notificationsApi.listDrafts(agencyId, "draft-cursor", signal);
    await notificationsApi.listBatches(agencyId, "batch-cursor", signal);
    expect(apiClient.get).toHaveBeenCalledWith(root, { params: { agency_id: agencyId, cursor: "draft-cursor", limit: 20 }, signal });
    expect(apiClient.get).toHaveBeenCalledWith(`${root}/batches`, { params: { agency_id: agencyId, cursor: "batch-cursor", limit: 20 }, signal });
  });

  it("asks the server to prove the original saved draft outcome during recovery", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: batch });
    await notificationsApi.byRequest(agencyId, batch.request_id, draft.id);
    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith(`${root}/batches/by-request/${batch.request_id}`, { params: { agency_id: agencyId, draft_id: draft.id } });
  });
});
