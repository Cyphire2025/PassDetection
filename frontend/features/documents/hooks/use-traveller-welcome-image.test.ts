import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { whatsappApi } from "@/features/whatsapp/api/whatsapp.api";
import { useTravellerWelcomeImage } from "./use-traveller-welcome-image";

vi.mock("@/features/whatsapp/api/whatsapp.api", () => ({ whatsappApi: { uploadWelcomeImage: vi.fn() } }));

describe("traveller welcome image recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:welcome-image") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  });

  it("uploads once to the chosen source and keeps a local preview only for this page", async () => {
    vi.mocked(whatsappApi.uploadWelcomeImage).mockResolvedValue({ media_id: "fresh-media", file_name: "welcome.png", content_type: "image/png" });
    const { result, unmount } = renderHook(() => useTravellerWelcomeImage());
    const file = new File(["image"], "welcome.png", { type: "image/png" });
    await act(() => result.current.upload("source-broadcast", file));
    expect(whatsappApi.uploadWelcomeImage).toHaveBeenCalledExactlyOnceWith("source-broadcast", file);
    expect(result.current.image).toEqual({ sourceId: "source-broadcast", mediaId: "fresh-media", previewUrl: "blob:welcome-image" });
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:welcome-image");
  });

  it("rejects unsupported and oversized images before contacting the server", async () => {
    const { result } = renderHook(() => useTravellerWelcomeImage());
    await act(() => result.current.upload("source", new File(["pdf"], "document.pdf", { type: "application/pdf" })));
    const largeFile = new File(["png"], "large.png", { type: "image/png" });
    Object.defineProperty(largeFile, "size", { value: 6 * 1024 * 1024 });
    await act(() => result.current.upload("source", largeFile));
    expect(whatsappApi.uploadWelcomeImage).not.toHaveBeenCalled();
    expect(result.current.error).toBe("Choose a JPG or PNG image up to 5 MB.");
  });

  it("surfaces upload failures without marking an image ready", async () => {
    vi.mocked(whatsappApi.uploadWelcomeImage).mockRejectedValue(new Error("Image provider unavailable"));
    const { result } = renderHook(() => useTravellerWelcomeImage());
    await act(() => result.current.upload("source", new File(["image"], "welcome.png", { type: "image/png" })));
    expect(result.current.image).toBeNull();
    expect(result.current.uploading).toBe(false);
    expect(result.current.error).toBe("Image provider unavailable");
  });
});
