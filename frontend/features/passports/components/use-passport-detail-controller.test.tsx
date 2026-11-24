import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePassportDetailController } from "./use-passport-detail-controller";

const mocks = vi.hoisted(() => ({
  metadata: vi.fn(), upload: vi.fn(), refetch: vi.fn(), reextract: vi.fn(),
  query: { data: { id: "synthetic-passport", group_id: "synthetic-group" }, isLoading: false, error: null },
}));

vi.mock("../hooks/use-passports", () => ({
  usePassportSubmission: () => ({ ...mocks.query, refetch: mocks.refetch }),
  useConfirmPassportSubmission: () => ({ isPending: false }),
  useStaffApprovePassportSubmission: () => ({ isPending: false }),
  useRetryPassportAiVerification: () => ({ isPending: false }),
  useReextractPassportSubmission: () => ({ isPending: false, mutateAsync: mocks.reextract }),
}));
vi.mock("@/stores/auth.store", () => ({ selectUser: vi.fn(), useAuthStore: () => ({ id: "staff", role: "agency_admin" }) }));
vi.mock("./use-passport-detail-navigation", () => ({ usePassportDetailNavigation: () => ({}) }));
vi.mock("../api/passports.api", () => ({ passportsApi: { getImageCrop: mocks.metadata, uploadImageLibraryImage: mocks.upload } }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.metadata.mockResolvedValue({ revision: 7 });
  mocks.upload.mockResolvedValue({});
  mocks.refetch.mockResolvedValue({});
});

describe("passport detail image replacement", () => {
  it("suppresses same-turn duplicate uploads and preserves the server revision", async () => {
    let resolveMetadata: ((value: { revision: number }) => void) | undefined;
    mocks.metadata.mockImplementationOnce(() => new Promise((resolve) => { resolveMetadata = resolve; }));
    const { result } = renderHook(() => usePassportDetailController("synthetic-passport", ""));
    const file = new File(["synthetic"], "front.png", { type: "image/png" });
    let pending: Promise<void>[] = [];
    act(() => {
      pending = [result.current.handleManualImageChange("passport_front", file), result.current.handleManualImageChange("passport_front", file)];
    });
    expect(mocks.metadata).toHaveBeenCalledTimes(1);
    await act(async () => { resolveMetadata?.({ revision: 7 }); await Promise.all(pending); });
    expect(mocks.upload).toHaveBeenCalledTimes(1);
    expect(mocks.upload).toHaveBeenCalledWith("synthetic-passport", "passport_front", file, 7);
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
    expect(result.current.changingImageType).toBeNull();
  });

  it("releases the in-flight guard after a failure so the explicit retry can succeed", async () => {
    mocks.upload.mockRejectedValueOnce(new Error("Synthetic upload failure"));
    const { result } = renderHook(() => usePassportDetailController("synthetic-passport", ""));
    const file = new File(["synthetic"], "front.png", { type: "image/png" });
    await act(async () => result.current.handleManualImageChange("passport_front", file));
    expect(result.current.imageChangeErrors.passport_front).toBe("Synthetic upload failure");
    await act(async () => result.current.handleManualImageChange("passport_front", file));
    expect(mocks.upload).toHaveBeenCalledTimes(2);
    expect(result.current.imageChangeErrors.passport_front).toBeUndefined();
    expect(result.current.imageRevision).toBe(1);
  });
});
