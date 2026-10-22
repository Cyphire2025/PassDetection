import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { decodeHumanHead, HEAD_MORPHS, type HumanHeadGeometry } from "./human-head-geometry";
import { createShortHairHead } from "./test-hologram-hair";
import { CORNEA_APERTURE } from "./test-hologram-eyes";
import { HEAD_ATTRIBUTES, meshAttributes, sampleHead } from "./test-hologram-particles";
import { fillHeadSurface } from "./test-hologram-surface-sampling";

function random() {
  let seed = 941;
  return () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
}

function plane(): HumanHeadGeometry {
  const positions = new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]);
  return { positions, normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1]),
    triangles: new Uint16Array([0, 1, 2, 0, 2, 3]), edges: new Uint16Array(),
    morphs: Object.fromEntries(HEAD_MORPHS.map((key, i) => [key, Float32Array.from(positions, (v, axis) =>
      v * .01 * (i + 1) + .003 * (axis % 3))])) as HumanHeadGeometry["morphs"] };
}

const percentile = (values: number[], fraction: number) => values.sort((a, b) => a - b)[Math.floor((values.length - 1) * fraction)];

/** Independent probe-grid distances measure uncovered patches, rather than
 * asserting the implementation's cell size or its random-number sequence.
 */
function coverage(points: Float32Array): number {
  const distances: number[] = [];
  for (let y = 0; y < 40; y++) for (let x = 0; x < 40; x++) {
    const px = -1 + (x + .5) / 20, py = -1 + (y + .5) / 20;
    let distance = Infinity;
    for (let i = 0; i < points.length; i += 3) distance = Math.min(distance, (px - points[i]) ** 2 + (py - points[i + 1]) ** 2);
    distances.push(Math.sqrt(distance));
  }
  return percentile(distances, .95);
}

describe("balanced head surface samples", () => {
  it("reduces large uncovered patches without larger grains, and retains deterministic exact morph interpolation", () => {
    const head = plane(), source = meshAttributes(head), count = 1024;
    const sampled = source.map(() => new Float32Array(count * 3)), repeated = source.map(() => new Float32Array(count * 3));
    fillHeadSurface(head, source, sampled, count, random()); fillHeadSurface(head, source, repeated, count, random());
    expect(sampled).toEqual(repeated);
    const baseline = new Float32Array(count * 3), next = random();
    for (let i = 0; i < count; i++) baseline.set([next() * 2 - 1, next() * 2 - 1, 0], i * 3);
    expect(coverage(sampled[0])).toBeLessThan(coverage(baseline) * .85);
    for (let i = 0; i < count * 3; i++) {
      expect(Math.abs(sampled[0][i])).toBeLessThanOrEqual(1);
      for (let morph = 0; morph < HEAD_MORPHS.length; morph++) {
        expect(sampled[morph + 2][i]).toBeCloseTo(sampled[0][i] * .01 * (morph + 1) + .003 * (i % 3), 6);
      }
    }
  });

  it.each(["female", "male"] as const)("keeps the %s feature budget detailed without reducing the true interior quota", (appearance) => {
    const binary = Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;
    const head = createShortHairHead(decodeHumanHead(binary, appearance));
    for (const count of [25_600, 65_536]) {
      const start = performance.now(), sampled = sampleHead(head, count), elapsed = performance.now() - start;
      const surface = Math.ceil(count * .6), eyes = sampled[HEAD_ATTRIBUTES.indexOf("eyeRegion")];
      const detail = sampled[HEAD_ATTRIBUTES.indexOf("surfaceDetail")], p = sampled[0];
      let hair = 0, iris = 0, sclera = 0, centralFace = 0, leftIris = 0, rightIris = 0;
      for (let point = 0; point < count; point++) {
        const offset = point * 3;
        if (point >= surface) { expect(detail[offset + 2]).toBeGreaterThanOrEqual(.049999); continue; }
        expect(detail[offset + 2]).toBe(0);
        if (detail[offset] > .03) hair++;
        if (eyes[offset + 2] > .5 && eyes[offset + 2] < 1.5) {
          iris++; if (p[offset] < 0) leftIris++; else rightIris++;
        }
        if (eyes[offset + 2] > 1.5) {
          sclera++;
          expect(Math.hypot(eyes[offset], eyes[offset + 1])).toBeGreaterThanOrEqual(CORNEA_APERTURE - .000001);
        }
        if (p[offset + 2] > .25 && Math.abs(p[offset]) < .45 && p[offset + 1] > -.65 && p[offset + 1] < .45) centralFace++;
      }
      expect(hair / surface).toBeGreaterThan(.30); expect(hair / surface).toBeLessThan(.43);
      expect(iris / surface).toBeGreaterThan(.024); expect(sclera / surface).toBeGreaterThan(.014);
      expect(Math.min(leftIris, rightIris)).toBeGreaterThan(iris * .40);
      // Original area-random allocation gave the female only 2,731/6,964 central
      // facial samples at these tiers. Both appearances need materially more.
      expect(centralFace / surface).toBeGreaterThan(.25);
      console.info(`${appearance} ${count} grains in ${elapsed.toFixed(1)}ms: surface=${surface}, face=${centralFace}, hair=${hair}, iris=${iris}, sclera=${sclera}`);
    }
  });
});
