import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import sharp from "sharp";
import { BufferGeometry, HalfFloatType, SRGBColorSpace, type WebGLRenderer } from "three";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decodeLandscapeGeometry, loadLandscapeAssets } from "./test-landscape-assets";
import compactAssets from "../../../public/ai/test-landscape/compact-v1.json";

const root = resolve("public/ai/test-landscape");
const source = (file: string) => Uint8Array.from(readFileSync(resolve(root, file))).buffer;
const renderer = { capabilities: { getMaxAnisotropy: () => 4 } } as WebGLRenderer;
const flush = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };
const bitmap = (size = 2048) => ({ width: size, height: size, close: vi.fn() }) as unknown as ImageBitmap;
const images: ImageBitmap[] = [], callbacks: Array<(image: ImageBitmap) => void> = [];
let mode = "success";

beforeEach(() => {
  vi.useFakeTimers(); mode = "success"; callbacks.length = 0; images.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, arrayBuffer: async () => url.endsWith(".bin") ? source(url.split("/").at(-1)!) : new ArrayBuffer(8) })));
  vi.stubGlobal("createImageBitmap", vi.fn(async () => {
    if (mode === "hang") return new Promise<ImageBitmap>((done) => { callbacks.push(done); });
    if (mode === "error" && images.length === 1) throw new Error("Image decode failed");
    const image = bitmap(mode === "invalid" ? 1 : images.length === 2 ? 256 : 2048);
    images.push(image); return image;
  }));
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("original landscape assets", () => {
  it("compresses the compact terrain binaries without changing geometry or color data", () => {
    for (const name of ["mountain", "ground", "patch", "grade-rgba16f"] as const) {
      const record = compactAssets[name], packed = readFileSync(resolve(root, record.file));
      expect(createHash("sha256").update(packed).digest("hex")).toBe(record.sha256);
      expect(gunzipSync(packed)).toEqual(readFileSync(resolve(root, `${name}.bin`)));
    }
    expect(Object.values(compactAssets).reduce((sum, record) => sum + record.bytes, 0)).toBeLessThan(550_000);
  });
  it("preserves the decoded source topology and reproducible derived-file hashes", () => {
    const manifest = JSON.parse(readFileSync(resolve(root, "provenance.json"), "utf8"));
    for (const record of manifest.derived) expect(createHash("sha256").update(readFileSync(resolve(root, record.file))).digest("hex")).toBe(record.sha256);
    for (const [file, vertices, indices] of [["mountain.bin", 1703, 8652], ["ground.bin", 2780, 14877], ["patch.bin", 4, 6]] as const) {
      const mesh = decodeLandscapeGeometry(source(file));
      expect(mesh.getAttribute("position").count).toBe(vertices); expect(mesh.index!.count).toBe(indices);
      expect(mesh.getAttribute("uv").count).toBe(vertices); expect(mesh.boundingSphere!.radius).toBeGreaterThan(.5); mesh.dispose();
    }
  });

  it("preserves the exact offline-decoded RGBA pixels in ordinary lossless images", async () => {
    const manifest = JSON.parse(readFileSync(resolve(root, "provenance.json"), "utf8"));
    const textures = manifest.derived.filter((record: { rgba_sha256?: string }) => record.rgba_sha256);
    expect(textures).toHaveLength(3);
    for (const record of textures) {
      const { data, info } = await sharp(resolve(root, record.file)).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
      expect([info.width, info.height, info.channels]).toEqual([record.width, record.height, 4]);
      expect(createHash("sha256").update(data).digest("hex")).toBe(record.rgba_sha256);
      expect(record.bytes).toBeLessThan(record.compared_bytes.png);
    }
  });

  it("rejects malformed geometry before allocating a renderable mesh", () => {
    const invalid = source("mountain.bin"), header = new DataView(invalid);
    header.setUint32(4, 100_000, true);
    expect(() => decodeLandscapeGeometry(invalid)).toThrow("Invalid landscape geometry");
    expect(() => decodeLandscapeGeometry(new ArrayBuffer(3))).toThrow("Truncated");
    const brokenIndex = source("mountain.bin");
    new DataView(brokenIndex).setUint16(brokenIndex.byteLength - 2, 65535, true);
    expect(() => decodeLandscapeGeometry(brokenIndex)).toThrow("Invalid landscape attributes");
  });

  it("loads only ordinary images/binaries and releases native bitmaps with textures once", async () => {
    const loader = loadLandscapeAssets(renderer), loaded = await loader.ready;
    expect(loaded.grade.type).toBe(HalfFloatType); expect(loaded.grade.image.depth).toBe(32);
    expect(createImageBitmap).toHaveBeenCalledTimes(3);
    for (const [, options] of vi.mocked(createImageBitmap).mock.calls) expect(options).toEqual({ imageOrientation: "none", premultiplyAlpha: "none", colorSpaceConversion: "none" });
    const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    expect(urls).toHaveLength(7);
    expect(urls).toContain("/ai/test-landscape/grade-rgba16f.bin");
    expect(urls.every((url) => /^\/ai\/test-landscape\/[\w-]+\.(bin|webp)$/.test(url))).toBe(true);
    for (const map of [loaded.mountainMap, loaded.groundMap, loaded.wind]) {
      expect(map.flipY).toBe(false); expect(map.colorSpace).toBe(SRGBColorSpace); expect(map.anisotropy).toBe(4);
    }
    const releases = Object.values(loaded).map((item) => vi.spyOn(item, "dispose"));
    loader.dispose(); loader.dispose();
    releases.forEach((release) => expect(release).toHaveBeenCalledTimes(1));
    images.forEach((image) => expect(image.close).toHaveBeenCalledTimes(1));
    expect(vi.getTimerCount()).toBe(0);
  });

  it("times out stalled image decoding, aborts fetches and closes late bitmaps", async () => {
    mode = "hang";
    const loader = loadLandscapeAssets(renderer), failure = expect(loader.ready).rejects.toThrow("timed out");
    await flush(); expect(createImageBitmap).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(25_000); await failure;
    const signal = vi.mocked(fetch).mock.calls[0][1]!.signal as AbortSignal;
    expect(signal.aborted).toBe(true);
    const late = callbacks.map((done, i) => { const image = bitmap(i === 2 ? 256 : 2048); done(image); return image; });
    await flush(); late.forEach((image) => expect(image.close).toHaveBeenCalledTimes(1));
    expect(vi.getTimerCount()).toBe(0);
  });

  it("retires pending fetches without decoding their late image responses", async () => {
    const responses: Array<() => void> = [];
    vi.mocked(fetch).mockImplementation((input) => new Promise((done) => {
      responses.push(() => done({ ok: true, arrayBuffer: async () => String(input).endsWith(".bin") ? source(String(input).split("/").at(-1)!) : new ArrayBuffer(8) } as Response));
    }));
    const loader = loadLandscapeAssets(renderer), failure = expect(loader.ready).rejects.toMatchObject({ name: "AbortError" });
    loader.dispose(); await failure;
    responses.forEach((done) => done()); await flush();
    expect(createImageBitmap).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects a reported image error promptly and frees other owned resources", async () => {
    mode = "error";
    const geometryRelease = vi.spyOn(BufferGeometry.prototype, "dispose"), loader = loadLandscapeAssets(renderer);
    await expect(loader.ready).rejects.toThrow("Image decode failed");
    expect(geometryRelease).toHaveBeenCalledTimes(3);
    images.forEach((image) => expect(image.close).toHaveBeenCalledTimes(1));
    expect(vi.getTimerCount()).toBe(0);
  });

  it("closes incorrectly sized decoded images before rejecting preparation", async () => {
    mode = "invalid";
    const loader = loadLandscapeAssets(renderer);
    await expect(loader.ready).rejects.toThrow("Invalid landscape texture");
    images.forEach((image) => expect(image.close).toHaveBeenCalledTimes(1));
    expect(vi.getTimerCount()).toBe(0);
  });
});
