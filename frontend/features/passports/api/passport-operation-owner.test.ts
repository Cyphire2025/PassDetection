import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { passportsApi } from "./passports.api";

vi.mock("@/lib/api/client", () => ({ default: { post: vi.fn(), get: vi.fn() } }));
vi.mock("@/lib/api/streamed-download", () => ({ downloadStreamedResponse: vi.fn() }));

const actor = (id: string) => useAuthStore.setState({ user: { id, role: "agency_admin", agency_id: "agency" } as User });
const saved = () => ({ data: { group_id: "group", total_count: 1, accepted_count: 1, rejected_count: 0, saved_count: 1, accepted_documents: [], rejected_documents: [] } });
beforeEach(() => { vi.resetAllMocks(); actor("initial-actor"); });
afterEach(() => vi.useRealTimers());

describe("passport private operation actor continuity", () => {
  it("stops a multipart import before another chunk or progress callback can use a replacement actor", async () => {
    const progress = vi.fn();
    vi.mocked(apiClient.post).mockImplementation(async () => { actor("replacement-actor"); return saved(); });
    await expect(passportsApi.savePassportDocumentsInChunks("group", {
      files: [new File(["one"], "one.jpg"), new File(["two"], "two.jpg")], maxChunkFiles: 1, onProgress: progress,
    })).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(apiClient.post).toHaveBeenCalledOnce();
    expect(progress).not.toHaveBeenCalled();
  });

  it("stops re-extraction polling and cache progress after the initial actor changes", async () => {
    vi.useFakeTimers();
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "submission", status: "extracting", extraction_status: "processing" } });
    const progress = vi.fn();
    const pending = passportsApi.reextract("submission", { onProgress: progress });
    const rejection = expect(pending).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    await Promise.resolve();
    actor("replacement-actor");
    await vi.advanceTimersByTimeAsync(750);
    await rejection;
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(progress).toHaveBeenCalledOnce();
  });

  it.each(["exportGroup", "exportGroupImages"] as const)("does not confirm %s history under a replacement actor", async (method) => {
    vi.mocked(downloadStreamedResponse).mockImplementation(async () => {
      actor("replacement-actor");
      return { filename: "synthetic", bytesWritten: 1, delivery: "bounded-memory", headers: { "x-passport-export-history-id": "history" } };
    });
    await expect(passportsApi[method]({ groupId: "group", mode: "all" })).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(downloadStreamedResponse).toHaveBeenCalledWith(expect.objectContaining({ expectedOwnerUserId: "initial-actor" }));
  });

  it("keeps successful chunks ordered and bound to the same initial actor", async () => {
    vi.mocked(apiClient.post).mockImplementation(async () => saved());
    const result = await passportsApi.savePassportDocumentsInChunks("group", {
      files: [new File(["one"], "one.jpg"), new File(["two"], "two.jpg")], maxChunkFiles: 1,
    });
    expect(result.saved_count).toBe(2);
    expect(apiClient.post).toHaveBeenCalledTimes(2);
    for (const call of vi.mocked(apiClient.post).mock.calls) {
      expect(call[2]).toMatchObject({ expectedOwnerUserId: "initial-actor" });
    }
  });

  it("ignores stale upload progress without throwing from a browser transport callback", async () => {
    const progress = vi.fn();
    vi.mocked(apiClient.post).mockImplementation(async (_url, _body, config) => {
      actor("replacement-actor");
      expect(() => config?.onUploadProgress?.({ loaded: 1, total: 2 } as never)).not.toThrow();
      return saved();
    });
    await expect(passportsApi.savePassportDocumentsInChunks("group", {
      files: [new File(["one"], "one.jpg")], onProgress: progress,
    })).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(progress).not.toHaveBeenCalled();
  });
});
