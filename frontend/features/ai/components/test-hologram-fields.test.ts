// @vitest-environment node
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gzipSync, gunzipSync } from "node:zlib";
import { Data3DTexture, DataUtils, HalfFloatType, LinearFilter, NoColorSpace } from "three";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HEAD_MORPHS } from "./human-head-geometry";
import { decodeHeadFieldData, HEAD_FIELD_BYTES, HEAD_FIELD_HEADER, HEAD_FIELD_SIDE } from "./test-head-field-format";
import { headFieldUniforms, loadHeadFields } from "./test-hologram-fields";

const root = resolve("public/ai/human-head");
const file = (appearance: string) => readFileSync(resolve(root, `fields-${appearance}-v1.bin.gz`));
const unpack = (appearance: string) => Uint8Array.from(gunzipSync(file(appearance))).buffer;
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("spatial head fields", () => {
  it.each(["female", "male"] as const)("validates the actual %s asset, provenance and finite GPU budget", (appearance) => {
    const manifest = JSON.parse(readFileSync(resolve(root, "fields-v1.json"), "utf8"));
    const decoded = decodeHeadFieldData(unpack(appearance), appearance), record = manifest.assets[appearance];
    expect(createHash("sha256").update(file(appearance)).digest("hex")).toBe(record.sha256);
    expect(record.gpuBytes).toBe(18 * 1024 * 1024); expect(record.gpuBytes).toBeLessThan(20 * 1024 * 1024);
    expect(decoded.arrays).toHaveLength(9); expect(decoded.arrays[0]).toHaveLength(64 ** 3 * 4);
    // Signed occupancy and a genuine directional field, not just rest positions.
    let inside = 0, outside = 0, nonzeroGradients = 0;
    const field = decoded.arrays[0];
    for (let offset = 0; offset < field.length; offset += 4) {
      const distance = DataUtils.fromHalfFloat(field[offset + 3]);
      if (distance < -.04) inside++; if (distance > .04) outside++;
      const normal = [0, 1, 2].map((axis) => DataUtils.fromHalfFloat(field[offset + axis]));
      if (Math.hypot(...normal) > .9) nonzeroGradients++;
    }
    expect(inside).toBeGreaterThan(20_000); expect(outside).toBeGreaterThan(60_000);
    expect(nonzeroGradients).toBeGreaterThan(64 ** 3 * .99);
    for (const [path, hash] of Object.entries(manifest.sourceModules)) {
      const source = readFileSync(resolve(path), "utf8").replace(/\r\n/g, "\n");
      // Verify both checkout forms against the same existing provenance hash.
      for (const newline of ["\n", "\r\n"]) {
        const checkout = source.replace(/\n/g, newline);
        expect(createHash("sha256").update(checkout.replace(/\r\n/g, "\n")).digest("hex")).toBe(hash);
      }
    }
  });

  it("rejects truncation, wrong appearance, invalid bounds and half-float NaNs", () => {
    expect(() => decodeHeadFieldData(new ArrayBuffer(128), "female")).toThrow("size");
    const buffer = unpack("female"), header = new DataView(buffer);
    expect(() => decodeHeadFieldData(buffer, "male")).toThrow("layout");
    header.setFloat32(44, 0, true);
    expect(() => decodeHeadFieldData(buffer, "female")).toThrow("bounds");
    header.setFloat32(44, 2, true); header.setUint16(HEAD_FIELD_HEADER, 0x7e00, true);
    expect(() => decodeHeadFieldData(buffer, "female")).toThrow("Non-finite");
  });

  it("decodes gzip once, binds the selected appearance and disposes all nine owned textures once", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(file("female")));
    vi.stubGlobal("fetch", fetcher);
    const fields = await loadHeadFields("female"), bindings = headFieldUniforms(fields);
    expect(fetcher).toHaveBeenCalledTimes(1); expect(String(fetcher.mock.calls[0][0])).toContain("fields-female-v1.bin.gz");
    const textures = [fields.field, ...HEAD_MORPHS.map((name) => fields.morphs[name]), fields.eyes, fields.detail];
    const releases = textures.map((texture) => vi.spyOn(texture, "dispose"));
    for (const texture of textures) {
      expect(texture).toBeInstanceOf(Data3DTexture); expect(texture.image.depth).toBe(HEAD_FIELD_SIDE);
      expect(texture.type).toBe(HalfFloatType); expect(texture.minFilter).toBe(LinearFilter);
      expect(texture.colorSpace).toBe(NoColorSpace); expect(texture.generateMipmaps).toBe(false);
    }
    expect(bindings.sdfVolume.value).toBe(fields.field); expect(bindings.sdfMin.value).toBe(fields.bounds.min);
    expect(bindings.sdfBlink.value).toBe(fields.morphs.blink);
    fields.dispose(); fields.dispose(); releases.forEach((release) => expect(release).toHaveBeenCalledTimes(1));
  });

  it("cancels a retired pending download without allocating GPU textures", async () => {
    const cancelled = vi.fn(), controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new ReadableStream({ cancel: cancelled }))));
    const loaded = loadHeadFields("female", controller.signal), failure = expect(loaded).rejects.toMatchObject({ name: "AbortError" });
    await Promise.resolve(); await Promise.resolve(); controller.abort(); await failure;
    expect(cancelled).toHaveBeenCalledTimes(1);
  });

  it("bounds decompression output and times out a stalled response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(gzipSync(new Uint8Array(HEAD_FIELD_BYTES + 1)))));
    await expect(loadHeadFields("female")).rejects.toThrow("budget");
    vi.useFakeTimers();
    const cancelled = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new ReadableStream({ cancel: cancelled }))));
    const loaded = loadHeadFields("male"), failure = expect(loaded).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(25_000); await failure;
    expect(cancelled).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });
});
