import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import manifest from "../../../public/ai/human-head/particles-v1.json";
import { decodeParticleHead, PARTICLE_ATTRIBUTES } from "./test-hologram-packed";

describe("prepared particle assets", () => {
  it.each(["female", "male"] as const)("loads bounded, finite %s anatomy and all speaking shapes within a one MB transfer", (appearance) => {
    const record = manifest.assets[appearance], packed = readFileSync(resolve("public/ai/human-head", record.file));
    expect(packed.byteLength).toBeLessThan(1_000_000);
    expect(createHash("sha256").update(packed).digest("hex")).toBe(record.sha256);
    const data = decodeParticleHead(Uint8Array.from(gunzipSync(packed)).buffer);
    expect(data).toHaveLength(PARTICLE_ATTRIBUTES.length);
    for (const values of data) { expect(values.length).toBe(43264 * 3); expect(values.every(Number.isFinite)).toBe(true); }
    for (let i = 2; i < 8; i++) expect(data[i].some((value) => Math.abs(value) > .001)).toBe(true);
    // Adaptive prefixes still contain both interior material and a broad face silhouette.
    const visible = data[0].slice(0, 25600 * 3);
    expect(Math.min(...visible)).toBeLessThan(-.7); expect(Math.max(...visible)).toBeGreaterThan(.7);
    const corrupt = Uint8Array.from(gunzipSync(packed)).buffer;
    new DataView(corrupt).setUint32(8, 1_000_000, true);
    expect(() => decodeParticleHead(corrupt)).toThrow("layout");
  });
  it("rejects truncated buffers before reading attributes", () => {
    expect(() => decodeParticleHead(new ArrayBuffer(10))).toThrow("size");
  });
});
