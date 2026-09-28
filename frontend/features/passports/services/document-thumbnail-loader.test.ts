import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const base = "/api/v1/passports/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const thumbnail = `${base}/images/passport_cover/thumbnail?crop_revision=2`;
const imageResponse = (headers: Record<string, string> = {}) => new Response(
  new Blob(["thumbnail"], { type: "image/jpeg" }),
  { headers: { "Content-Type": "image/jpeg", ...headers } },
);

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("document preview scheduling", () => {
  it("recognizes all five images and legacy covers without rewriting external URLs", async () => {
    const { documentThumbnailUrl, isManagedDocumentThumbnail } = await import("./document-thumbnail-scheduler");
    for (const kind of ["visa_photo", "passport_front", "passport_back", "passport_cover", "passport_back_cover"]) {
      expect(documentThumbnailUrl(`${base}/images/${kind}?crop_revision=2`))
        .toBe(`${base}/images/${kind}/thumbnail?crop_revision=2`);
    }
    expect(documentThumbnailUrl(`${base}/covers/back_cover`)).toBe(`${base}/images/passport_back_cover/thumbnail`);
    expect(documentThumbnailUrl(`${base}/covers/cover`)).toBe(`${base}/images/passport_cover/thumbnail`);
    expect(isManagedDocumentThumbnail(thumbnail)).toBe(true);
    const external = `https://example.test${base}/images/passport_cover`;
    expect(documentThumbnailUrl(external)).toBe(external);
    expect(isManagedDocumentThumbnail(external)).toBe(false);
  });

  it("caps concurrent requests and removes cancelled queued work", async () => {
    const { acquireDocumentThumbnailSlot } = await import("./document-thumbnail-scheduler");
    const releases: Array<() => void> = [];
    for (let index = 0; index < 6; index += 1) {
      void acquireDocumentThumbnailSlot().then((release) => releases.push(release));
    }
    await vi.advanceTimersByTimeAsync(300);
    expect(releases).toHaveLength(6);
    const cancelled = new AbortController();
    const rejected = expect(acquireDocumentThumbnailSlot(cancelled.signal)).rejects.toMatchObject({ name: "AbortError" });
    cancelled.abort();
    await rejected;
    let seventhStarted = false;
    void acquireDocumentThumbnailSlot().then((release) => {
      seventhStarted = true;
      release();
    });
    await vi.advanceTimersByTimeAsync(1_000);
    expect(seventhStarted).toBe(false);
    releases.forEach((release) => release());
    await vi.advanceTimersByTimeAsync(1);
    expect(seventhStarted).toBe(true);
  });

  it("pauses all queued previews for Retry-After, then resumes without losing images", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 429, headers: { "Retry-After": "2" } }))
      .mockImplementation(async () => imageResponse());
    vi.stubGlobal("fetch", request);
    const { fetchDocumentThumbnail } = await import("./document-thumbnail-loader");
    const first = fetchDocumentThumbnail(thumbnail, new AbortController().signal);
    const second = fetchDocumentThumbnail(thumbnail.replace("passport_cover", "passport_back_cover"), new AbortController().signal);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(request).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    const images = await Promise.all([first, second]);
    expect(images.every((image) => image.type === "image/jpeg")).toBe(true);
    expect(request).toHaveBeenCalledTimes(3);
    expect(request.mock.calls[0][1]).toMatchObject({ credentials: "same-origin", cache: "no-store", redirect: "error" });
  });

  it("adapts pacing to a lower configured server allowance", async () => {
    const request = vi.fn(async () => imageResponse({ "X-RateLimit-Refill-Per-Second": "2" }));
    vi.stubGlobal("fetch", request);
    const { fetchDocumentThumbnail } = await import("./document-thumbnail-loader");
    const results = Array.from({ length: 3 }, () => fetchDocumentThumbnail(thumbnail, new AbortController().signal));
    await vi.advanceTimersByTimeAsync(41);
    expect(request).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(623);
    expect(request).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    await Promise.all(results);
    expect(request).toHaveBeenCalledTimes(3);
  });

  it("waits for a depleted minute budget to reset", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(imageResponse({ "X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "3" }))
      .mockResolvedValueOnce(imageResponse());
    vi.stubGlobal("fetch", request);
    const { fetchDocumentThumbnail } = await import("./document-thumbnail-loader");
    const results = Array.from({ length: 2 }, () => fetchDocumentThumbnail(thumbnail, new AbortController().signal));
    await vi.advanceTimersByTimeAsync(2_999);
    expect(request).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await Promise.all(results);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("cancels during cooldown without starting another request", async () => {
    const request = vi.fn(async () => new Response(null, { status: 503, headers: { "Retry-After": "60" } }));
    vi.stubGlobal("fetch", request);
    const { fetchDocumentThumbnail } = await import("./document-thumbnail-loader");
    const controller = new AbortController();
    const rejected = expect(fetchDocumentThumbnail(thumbnail, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(100);
    controller.abort();
    await rejected;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("bounds retries and rejects non-image or missing responses", async () => {
    const request = vi.fn(async () => new Response(null, { status: 429, headers: { "Retry-After": "1" } }));
    vi.stubGlobal("fetch", request);
    const { fetchDocumentThumbnail } = await import("./document-thumbnail-loader");
    const rejected = expect(fetchDocumentThumbnail(thumbnail, new AbortController().signal)).rejects.toThrow("429");
    await vi.advanceTimersByTimeAsync(5_001);
    await rejected;
    expect(request).toHaveBeenCalledTimes(6);
    await vi.advanceTimersByTimeAsync(1_000);
    request.mockResolvedValueOnce(new Response("login", { headers: { "Content-Type": "text/html" } }));
    await expect(fetchDocumentThumbnail(thumbnail, new AbortController().signal)).rejects.toThrow("not an image");
  });
});
