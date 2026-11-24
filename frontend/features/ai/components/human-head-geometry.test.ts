import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { decodeHumanHead, HEAD_MORPHS, loadHumanHead } from "./human-head-geometry";

const source = () => Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;

afterEach(() => vi.unstubAllGlobals());

describe("the shipped human head geometry", () => {
  it("has complete 3D volume, valid WebGL1 topology and distinct appearances", () => {
    const female = decodeHumanHead(source(), "female");
    const male = decodeHumanHead(source(), "male");
    const count = female.positions.length / 3;
    expect(count).toBeGreaterThan(10_000);
    expect(count).toBeLessThan(65_536);
    expect(male.triangles).toEqual(female.triangles);
    expect(male.positions).not.toEqual(female.positions);
    for (const head of [female, male]) {
      for (const indices of [head.triangles, head.edges]) {
        expect(indices.every((index) => index < count)).toBe(true);
      }
      const depth = head.positions.filter((_, i) => i % 3 === 2);
      expect(Math.min(...depth)).toBeLessThan(-.65);
      expect(Math.max(...depth)).toBeGreaterThan(.65);
      for (let i = 0; i < head.normals.length; i += 3) {
        expect(Math.hypot(...head.normals.subarray(i, i + 3))).toBeCloseTo(1, 3);
      }
    }
  });

  it("carries six nonempty authored morphs aligned to the same vertex order", () => {
    const head = decodeHumanHead(source(), "female");
    for (const name of HEAD_MORPHS) {
      const shape = head.morphs[name];
      expect(shape.length).toBe(head.positions.length);
      expect(shape.every(Number.isFinite)).toBe(true);
      expect(shape.some((value) => Math.abs(value) > .01)).toBe(true);
    }
    // Speech opening moves the lower face, while the cranium stays fixed.
    let lowerMovement = 0;
    for (let i = 0; i < head.positions.length; i += 3) {
      if (head.positions[i + 1] > .7) expect(head.morphs.jaw.slice(i, i + 3)).toEqual(new Float32Array(3));
      if (head.positions[i + 1] < 0) lowerMovement = Math.max(lowerMovement, -head.morphs.jaw[i + 1]);
    }
    expect(lowerMovement).toBeGreaterThan(.1);
  });

  it.each(["female", "male"])("ships a transparent, bounded %s fallback from the mesh", (appearance) => {
    const image = readFileSync(resolve(`public/ai/human-head/${appearance}-still.png`));
    expect(image.subarray(1, 4).toString()).toBe("PNG");
    expect(image.readUInt32BE(16)).toBe(720);
    expect(image.readUInt32BE(20)).toBe(900);
    expect(image[25]).toBe(6); // PNG RGBA, preserving the page background.
    expect(image.byteLength).toBeLessThan(300_000);
  });

  it.each(["truncated", "signature", "capacity", "scale", "index"])("rejects a corrupt %s before GPU upload", (kind) => {
    const buffer = source();
    const data = new DataView(buffer);
    if (kind === "truncated") return expect(() => decodeHumanHead(buffer.slice(0, -2), "male")).toThrow();
    if (kind === "signature") data.setUint8(0, 0);
    if (kind === "capacity") data.setUint32(8, 65_536, true);
    if (kind === "scale") data.setFloat32(24, Number.NaN, true);
    if (kind === "index") data.setUint16(64 + data.getUint32(8, true) * 3 * 10 * 2, 65_535, true);
    expect(() => decodeHumanHead(buffer, "male")).toThrow();
  });

  it("loads the locally hosted asset and forwards cancellation", async () => {
    const fetcher = vi.fn(async () => ({ ok: true, arrayBuffer: async () => source() }));
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    const head = await loadHumanHead("male", controller.signal);
    expect(head.positions.length).toBeGreaterThan(30_000);
    expect(fetcher).toHaveBeenCalledWith("/ai/human-head/head-v1.bin", { signal: controller.signal, cache: "force-cache" });
  });

  it("reports missing assets without attempting to decode an error page", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
    await expect(loadHumanHead("female")).rejects.toThrow("unavailable");
  });
});
