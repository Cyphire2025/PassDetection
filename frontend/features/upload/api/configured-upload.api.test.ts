import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { uploadApi } from "./upload.api";

vi.mock("@/lib/api/client", () => ({ default: { post: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.post).mockResolvedValue({ data: { id: "durable-submission" } });
});

describe("configured document upload transport", () => {
  it("sends all requested passport pages with their distinct document fields and the selected Visa Photo source", async () => {
    const front = new File(["front"], "front.jpg", { type: "image/jpeg" });
    const back = new File(["back"], "back.jpg", { type: "image/jpeg" });
    const cover = new File(["cover"], "cover.jpg", { type: "image/jpeg" });
    const backCover = new File(["back cover"], "back-cover.jpg", { type: "image/jpeg" });
    const photo = new File(["photo"], "photo.jpg", { type: "image/jpeg" });
    await uploadApi.uploadPassport("group-token", "Example Traveller", front, back, "file", "private-key", photo, null, undefined, { passportCoverFile: cover, passportBackCoverFile: backCover, visaPhotoSource: "file" });
    const form = vi.mocked(apiClient.post).mock.calls[0][1] as FormData;
    expect(form.get("file")).toBe(front);
    expect(form.get("passport_back_file")).toBe(back);
    expect(form.get("passport_cover_file")).toBe(cover);
    expect(form.get("passport_back_cover_file")).toBe(backCover);
    expect(form.get("passport_photo_file")).toBe(photo);
    expect(form.get("visa_photo_source")).toBe("file");
    expect(form.get("upload_idempotency_key")).toBe("private-key");
    expect(vi.mocked(apiClient.post).mock.calls[0][2]?.headers).toMatchObject({ "X-Upload-Session-ID": "private-key" });
  });

  it("creates a real request without fabricated document fields for a document-free traveller", async () => {
    const result = await uploadApi.uploadPassport("group-token", "Example Traveller", null, null, "file", "private-key");
    const form = vi.mocked(apiClient.post).mock.calls[0][1] as FormData;
    expect(form.get("client_name")).toBe("Example Traveller");
    for (const key of ["file", "passport_back_file", "passport_cover_file", "passport_back_cover_file", "passport_photo_file", "visa_photo_source"]) expect(form.has(key)).toBe(false);
    expect(result).toEqual({ id: "durable-submission" });
  });
});
