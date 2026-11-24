import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useDocumentWorkspaceUpload } from "./use-document-workspace-upload";
import type { useDocumentReview } from "./use-document-distribution";

const mocks = vi.hoisted(() => ({
  review: vi.fn(), verify: vi.fn(), upload: vi.fn(), reset: vi.fn(), resolve: vi.fn(),
  replace: vi.fn(), restore: vi.fn(), forget: vi.fn(), cancel: vi.fn(), candidates: new Map(),
}));
vi.mock("../api/document-distribution.api", () => ({ documentDistributionApi: { getReview: mocks.review } }));
vi.mock("./use-document-distribution", () => ({
  useVerifyDistributionDocuments: () => ({ mutateAsync: mocks.verify, reset: mocks.reset }),
  useUploadDistributionDocuments: () => ({ mutate: mocks.upload }),
}));
vi.mock("./use-document-manual-review", () => ({ useDocumentManualReview: () => ({
  candidates: mocks.candidates, pending: false, pendingUpload: null,
  replaceCandidates: mocks.replace, restoreUpload: mocks.restore, forgetUpload: mocks.forget,
}) }));
vi.mock("./use-document-filename-conflicts", () => ({ useDocumentFilenameConflicts: () => ({ cancel: mocks.cancel, resolve: mocks.resolve }) }));

const review = { data: undefined } as ReturnType<typeof useDocumentReview>;
const resetManualTarget = vi.fn();
beforeEach(() => { vi.clearAllMocks(); window.sessionStorage.clear(); });

describe("document workspace upload ownership", () => {
  it("starts one verification flow when Check is invoked twice before a pending render", async () => {
    let releaseReview: (() => void) | undefined;
    mocks.review.mockImplementation(() => new Promise((resolve) => { releaseReview = () => resolve({}); }));
    mocks.resolve.mockResolvedValue(null);
    const { result } = renderHook(() => useDocumentWorkspaceUpload("group", "visa", review, resetManualTarget));
    await act(async () => undefined);
    act(() => result.current.resetSelection([new File(["%PDF"], "visa.pdf", { type: "application/pdf" })]));
    let pending: Promise<void>[] = [];
    act(() => { pending = [result.current.checkDocuments(), result.current.checkDocuments()]; });
    expect(mocks.review).toHaveBeenCalledTimes(1);
    await act(async () => { releaseReview?.(); await Promise.all(pending); });
    expect(mocks.resolve).toHaveBeenCalledTimes(1);
    expect(mocks.verify).not.toHaveBeenCalled();
    expect(result.current.preparingCheck).toBe(false);
  });

  it("aborts owned work and ignores its late response after the workspace unmounts", async () => {
    let releaseReview: (() => void) | undefined;
    mocks.review.mockImplementation(() => new Promise((resolve) => { releaseReview = () => resolve({}); }));
    const { result, unmount } = renderHook(() => useDocumentWorkspaceUpload("group", "visa", review, resetManualTarget));
    await act(async () => undefined);
    act(() => result.current.resetSelection([new File(["%PDF"], "visa.pdf", { type: "application/pdf" })]));
    let pending: Promise<void> | undefined;
    act(() => { pending = result.current.checkDocuments(); });
    const signal = mocks.review.mock.calls[0][2] as AbortSignal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { releaseReview?.(); await pending; });
    expect(mocks.resolve).not.toHaveBeenCalled();
    expect(mocks.verify).not.toHaveBeenCalled();
  });
});
