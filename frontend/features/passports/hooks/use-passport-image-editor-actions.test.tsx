import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { passportsApi } from "../api/passports.api";
import { usePassportImageEditorActions } from "./use-passport-image-editor-actions";
import { cropMetadata, deferred } from "./passport-image-editor.test-fixtures";

vi.mock("../api/passports.api", () => ({ passportsApi: {
  saveImageCrop: vi.fn(), resetImageCrop: vi.fn(),
  useImageLibraryImage: vi.fn(), uploadImageLibraryImage: vi.fn(),
} }));

function options() {
  return { submissionId: "passport-1", imageType: "passport_front" as const,
    metadata: cropMetadata, cropRect: cropMetadata.crop!, sharpness: 1.75,
    isGenerating: false, busyRef: { current: false }, setError: vi.fn(),
    onSaved: vi.fn(), onClose: vi.fn() };
}

describe("passport image save actions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("admits one same-turn mutation and preserves the exact crop revision", async () => {
    const request = deferred<typeof cropMetadata>();
    vi.mocked(passportsApi.saveImageCrop).mockReturnValue(request.promise);
    const props = options();
    const { result } = renderHook(() => usePassportImageEditorActions(props));
    let saving!: Promise<void>;
    act(() => { saving = result.current.save(); void result.current.save(); void result.current.reset(); });
    expect(passportsApi.saveImageCrop).toHaveBeenCalledExactlyOnceWith("passport-1", "passport_front",
      { ...cropMetadata.crop, sharpness: 1.75, expected_revision: 7 });
    expect(passportsApi.resetImageCrop).not.toHaveBeenCalled();
    expect(result.current.closeBlocked).toBe(true);
    await act(async () => { request.resolve(cropMetadata); await saving; });
    expect(props.onSaved).toHaveBeenCalledOnce();
    expect(props.onClose).toHaveBeenCalledOnce();
    expect(props.busyRef.current).toBe(false);
  });

  it("does not close a replacement editor after an earlier editor unmounts", async () => {
    const request = deferred<typeof cropMetadata>();
    vi.mocked(passportsApi.resetImageCrop).mockReturnValue(request.promise);
    const props = options();
    const { result, unmount } = renderHook(() => usePassportImageEditorActions(props));
    let resetting!: Promise<void>;
    act(() => { resetting = result.current.reset(); });
    unmount();
    await act(async () => { request.resolve(cropMetadata); await resetting; });
    expect(props.onSaved).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("retains server conflict errors and allows another explicit attempt", async () => {
    vi.mocked(passportsApi.useImageLibraryImage).mockRejectedValue(new Error("Image revision changed"));
    const props = options();
    const { result } = renderHook(() => usePassportImageEditorActions(props));
    await act(async () => { await result.current.activateLibraryImage("saved-2"); });
    expect(props.setError).toHaveBeenLastCalledWith("Image revision changed");
    expect(props.onClose).not.toHaveBeenCalled();
    expect(props.busyRef.current).toBe(false);
    expect(result.current.usingImageId).toBeNull();
  });
});
