import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { capturePrivateOperationOwner } from "@/lib/api/request-owner";
import { downloadStreamedResponse } from "@/lib/api/streamed-download";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { passportsApi } from "./passports.api";

vi.mock("@/lib/api/client", () => ({ default: { post: vi.fn(), get: vi.fn() } }));
vi.mock("@/lib/api/streamed-download", () => ({ downloadStreamedResponse: vi.fn() }));
const setActor = (role = "agency_admin") => useAuthStore.setState({ user: { id: "actor", role, agency_id: "agency" } as User });
beforeEach(() => { vi.resetAllMocks(); setActor(); });

describe("initiating passport request configuration", () => {
  it.each([
    ["re-extraction", (config: ReturnType<typeof capturePrivateOperationOwner>["requestConfig"]) => passportsApi.reextract("record", {}, config)],
    ["chunked save", (config: ReturnType<typeof capturePrivateOperationOwner>["requestConfig"]) => passportsApi.savePassportDocumentsInChunks("group", { files: [new File(["synthetic"], "passport.jpg")] }, config)],
    ["Excel export", (config: ReturnType<typeof capturePrivateOperationOwner>["requestConfig"]) => passportsApi.exportGroup({ groupId: "group", mode: "all" }, config)],
    ["image export", (config: ReturnType<typeof capturePrivateOperationOwner>["requestConfig"]) => passportsApi.exportGroupImages({ groupId: "group", mode: "all" }, config)],
    ["selected export", (config: ReturnType<typeof capturePrivateOperationOwner>["requestConfig"]) => passportsApi.exportSelectedPassports(["record"], config)],
    ["tracking export", (config: ReturnType<typeof capturePrivateOperationOwner>["requestConfig"]) => passportsApi.exportWhatsAppTracking({ groupId: "group", status: "all" }, config)],
  ] as const)("rejects stale initiating authority before starting %s", async (_name, run) => {
    const initial = capturePrivateOperationOwner();
    setActor("agency_staff");
    await expect(run(initial.requestConfig)).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(downloadStreamedResponse).not.toHaveBeenCalled();
  });

  it("forwards owner metadata outside the unchanged confirmation body", async () => {
    const { requestConfig } = capturePrivateOperationOwner();
    vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "record" } });
    await passportsApi.confirm("record", { surname: "SYNTHETIC" }, requestConfig);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
      "/api/v1/passports/record/confirm", { confirmed_fields: { surname: "SYNTHETIC" } }, requestConfig,
    );
  });

  it("ignores late preview progress after authority changes without throwing in the transport callback", async () => {
    const { requestConfig } = capturePrivateOperationOwner(), progress = vi.fn();
    vi.mocked(apiClient.post).mockImplementation(async (_url, _body, config) => {
      setActor("agency_staff");
      expect(() => config?.onUploadProgress?.({ loaded: 1, total: 2 } as never)).not.toThrow();
      return { data: {} };
    });
    await passportsApi.previewPassportDocuments("group", { files: [new File(["synthetic"], "passport.jpg")], onProgress: progress }, requestConfig);
    expect(progress).not.toHaveBeenCalled();
  });
});
