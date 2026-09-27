import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { PUBLIC_UPLOAD_ACCEPT, preparePublicUploadFile, publicUploadFileError } from "./public-upload-file";

vi.mock("@/lib/api/client", () => ({ default: { post: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());

function file(name: string, type: string, size = 100) {
  const value = new File(["data"], name, { type });
  Object.defineProperty(value, "size", { value: size });
  return value;
}

describe("public upload sources", () => {
  it.each([
    ["photo.jpg", "image/jpeg"], ["photo.jpeg", "image/jpeg"], ["photo.png", "image/png"],
    ["photo.heic", "image/heic"], ["photo.heif", "image/heif"], ["photo.avif", "image/avif"], ["page.pdf", "application/pdf"],
  ])("allows %s with the same source policy for passport and visa", (name, type) => {
    expect(publicUploadFileError(file(name, type), "passport")).toBeNull();
    expect(publicUploadFileError(file(name, type), "visa")).toBeNull();
  });

  it.each([["a.webp", "image/webp"], ["a.bmp", "image/bmp"], ["a.tiff", "image/tiff"], ["a.gif", "image/gif"], ["a.zip", "application/zip"]])("rejects %s", (name, type) => {
    expect(publicUploadFileError(file(name, type), "passport")).toContain("single-page PDF");
    expect(publicUploadFileError(file(name, type), "visa")).toContain("single-page PDF");
    expect(PUBLIC_UPLOAD_ACCEPT).not.toContain(type);
  });

  it("uses the 2 MB PDF limit for both flows while keeping visa images at 10 MB", () => {
    const max = 2 * 1024 * 1024;
    for (const purpose of ["passport", "visa"] as const) {
      expect(publicUploadFileError(file("page.pdf", "application/pdf", max), purpose)).toBeNull();
      expect(publicUploadFileError(file("page.pdf", "application/pdf", max + 1), purpose)).toContain("2 MB");
      expect(publicUploadFileError(file("page.PDF", "", max + 1), purpose)).toContain("2 MB");
      expect(publicUploadFileError(file("a.png", "image/png", 0), purpose)).toContain("empty");
    }
    expect(publicUploadFileError(file("a.png", "image/png", max + 1), "passport")).toContain("2 MB");
    expect(publicUploadFileError(file("a.png", "image/png", 10 * 1024 * 1024), "visa")).toBeNull();
    expect(publicUploadFileError(file("a.png", "image/png", 10 * 1024 * 1024 + 1), "visa")).toContain("10 MB");
  });

  it("prepares original bytes under the current upload identity and returns a JPEG", async () => {
    const original = file("page.pdf", "application/pdf");
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: new Blob(["jpeg"], { type: "image/jpeg" }) });
    const controller = new AbortController();
    const prepared = await preparePublicUploadFile(original, { token: "test-token", uploadSessionId: "test-session", purpose: "passport", signal: controller.signal });
    expect(prepared.name).toBe("page.jpg");
    expect(prepared.type).toBe("image/jpeg");
    const [url, data, config] = vi.mocked(apiClient.post).mock.calls[0];
    expect(url).toBe("/api/v1/passports/upload/test-token/prepare-file");
    expect((data as FormData).get("file")).toBe(original);
    expect((data as FormData).get("purpose")).toBe("passport");
    expect(config).toMatchObject({ responseType: "blob", headers: { "X-Upload-Session-ID": "test-session" }, signal: controller.signal });
  });

  it("does not send invalid sources or requests without upload identity", async () => {
    await expect(preparePublicUploadFile(file("a.webp", "image/webp"), { token: "token", uploadSessionId: "session", purpose: "visa" })).rejects.toThrow("single-page PDF");
    await expect(preparePublicUploadFile(file("a.png", "image/png"), { purpose: "passport" })).rejects.toThrow("session");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("preserves server PDF errors and rejects an invalid preview response", async () => {
    const options = { token: "token", uploadSessionId: "session", purpose: "passport" } as const;
    const rejected = { code: "HTTP_400", message: "PDF must contain exactly one page." };
    vi.mocked(apiClient.post).mockRejectedValueOnce(rejected);
    await expect(preparePublicUploadFile(file("page.pdf", "application/pdf"), options)).rejects.toBe(rejected);
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: new Blob(["pdf"], { type: "application/pdf" }) });
    await expect(preparePublicUploadFile(file("page.pdf", "application/pdf"), options)).rejects.toThrow("preview could not");
  });
});
