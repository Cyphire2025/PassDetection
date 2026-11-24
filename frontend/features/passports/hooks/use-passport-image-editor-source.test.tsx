import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { passportsApi } from "../api/passports.api";
import { usePassportImageEditorSource } from "./use-passport-image-editor-source";
import { cropMetadata, deferred } from "./passport-image-editor.test-fixtures";

vi.mock("../api/passports.api", () => ({ passportsApi: {
  getImageCrop: vi.fn(), getEditableImage: vi.fn(), listImageLibrary: vi.fn(),
} }));

describe("private passport image source lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(passportsApi.listImageLibrary).mockResolvedValue([]);
  });

  it("does not fetch a private source after metadata resolves for a closed editor", async () => {
    const metadata = deferred<typeof cropMetadata>();
    vi.mocked(passportsApi.getImageCrop).mockReturnValue(metadata.promise);
    const onError = vi.fn();
    const { unmount } = renderHook(() => usePassportImageEditorSource("passport-1", "passport_front", onError));
    unmount();
    await act(async () => { metadata.resolve(cropMetadata); });
    expect(passportsApi.getEditableImage).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("releases the authorized image blob URL on close", async () => {
    const create = vi.fn(() => "blob:private-source");
    const revoke = vi.fn();
    const createDescriptor = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const revokeDescriptor = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
    try {
      vi.mocked(passportsApi.getImageCrop).mockResolvedValue(cropMetadata);
      vi.mocked(passportsApi.getEditableImage).mockResolvedValue(new Blob(["image"]));
      const onError = vi.fn();
      const { result, unmount } = renderHook(() => usePassportImageEditorSource("passport-1", "passport_front", onError));
      await act(async () => {});
      expect(result.current.sourceObjectUrl).toBe("blob:private-source");
      unmount();
      expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:private-source");
    } finally {
      if (createDescriptor) Object.defineProperty(URL, "createObjectURL", createDescriptor);
      else Reflect.deleteProperty(URL, "createObjectURL");
      if (revokeDescriptor) Object.defineProperty(URL, "revokeObjectURL", revokeDescriptor);
      else Reflect.deleteProperty(URL, "revokeObjectURL");
    }
  });
});
