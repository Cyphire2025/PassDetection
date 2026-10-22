import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { Triangle, Vector3 } from "three";
import { decodeHumanHead, HEAD_MORPHS, type HumanHeadGeometry } from "./human-head-geometry";
import { prepareTestHead, refineAdultHead } from "./test-hologram-adult-head";
import { eyeRegions } from "./test-hologram-eyes";

const source = (appearance: "female" | "male") => decodeHumanHead(
  Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer, appearance,
);
const chin = (head: HumanHeadGeometry) => {
  let minimum = Infinity;
  for (let i = 0; i < head.positions.length; i += 3) if (Math.abs(head.positions[i]) < .15 && head.positions[i + 2] > .25
    && head.positions[i + 1] < -.4) minimum = Math.min(minimum, head.positions[i + 1]);
  return minimum;
};

describe("adult assistant geometry preparation", () => {
  it.each(["female", "male"] as const)("refines the %s lower face without changing topology, eyes or source arrays", (appearance) => {
    const original = source(appearance), saved = original.positions.slice(), refined = refineAdultHead(original, appearance);
    expect(original.positions).toEqual(saved);
    expect(refined.triangles).toBe(original.triangles); expect(refined.edges).toBe(original.edges);
    const ratio = (.1722 - chin(refined)) / (.1722 - chin(original));
    expect(ratio).toBeGreaterThan(1.035); expect(ratio).toBeLessThan(1.045);
    const originalEyes = eyeRegions(original), refinedEyes = eyeRegions(refined);
    expect(refinedEyes).toEqual(originalEyes);
    let eyes = 0, cheekChanges = 0;
    for (let i = 0; i < original.positions.length; i += 3) {
      if (originalEyes[i + 2] > 0) {
        eyes++;
        expect(refined.positions.subarray(i, i + 3)).toEqual(original.positions.subarray(i, i + 3));
        for (const key of HEAD_MORPHS) expect(refined.morphs[key].subarray(i, i + 3)).toEqual(original.morphs[key].subarray(i, i + 3));
      }
      const [x, y, z] = original.positions.subarray(i, i + 3);
      if (Math.abs(x) > .25 && Math.abs(x) < .4 && y > -.25 && y < -.10 && z > .35) {
        expect(Math.abs(refined.positions[i])).toBeLessThan(Math.abs(x));
        expect(refined.positions[i + 2]).toBeLessThan(z); cheekChanges++;
      }
    }
    expect(eyes).toBe(1830); expect(cheekChanges).toBeGreaterThan(20);
  });

  it.each(["female", "male"] as const)("keeps the %s authored mouth opening, closure and lateral shapes functional", (appearance) => {
    const original = source(appearance), refined = refineAdultHead(original, appearance);
    // Reviewed center upper/lower lip vertices in the shared authored topology.
    const upper = 585 * 3, lower = 618 * 3;
    const gap = (head: HumanHeadGeometry, jaw: number, closure: number) => head.positions[upper + 1] - head.positions[lower + 1]
      + jaw * (head.morphs.jaw[upper + 1] - head.morphs.jaw[lower + 1])
      + closure * (head.morphs.closure[upper + 1] - head.morphs.closure[lower + 1]);
    expect(gap(refined, 0, 0)).toBeCloseTo(gap(original, 0, 0), 7);
    expect(gap(refined, 0, 1)).toBeCloseTo(gap(original, 0, 1), 7);
    expect(gap(refined, 0, 1)).toBeLessThan(gap(refined, 0, 0) * .6);
    const opening = gap(refined, 1, 0) - gap(refined, 0, 0), originalOpening = gap(original, 1, 0) - gap(original, 0, 0);
    expect(opening).toBeGreaterThan(.14); expect(opening / originalOpening).toBeGreaterThan(.95);
    expect(opening / originalOpening).toBeLessThan(1.2);
    for (const key of HEAD_MORPHS) {
      expect(refined.morphs[key].every(Number.isFinite)).toBe(true);
      const energy = (values: Float32Array) => values.reduce((sum, value) => sum + value * value, 0);
      expect(energy(refined.morphs[key]) / energy(original.morphs[key])).toBeGreaterThan(.85);
      expect(energy(refined.morphs[key]) / energy(original.morphs[key])).toBeLessThan(1.3);
    }
  });

  it.each(["female", "male"] as const)("keeps %s face triangles oriented and supplies finite unit normals", (appearance) => {
    const original = source(appearance), refined = refineAdultHead(original, appearance), triangle = new Triangle();
    const before = new Vector3(), after = new Vector3();
    for (let face = 0; face < original.triangles.length; face += 3) {
      const normal = (head: HumanHeadGeometry, out: Vector3) => {
        triangle.a.fromArray(head.positions, head.triangles[face] * 3);
        triangle.b.fromArray(head.positions, head.triangles[face + 1] * 3);
        triangle.c.fromArray(head.positions, head.triangles[face + 2] * 3);
        return triangle.getNormal(out);
      };
      normal(original, before); normal(refined, after);
      if (before.lengthSq() > .5) expect(before.dot(after)).toBeGreaterThan(.95);
    }
    for (let i = 0; i < refined.normals.length; i += 3) expect(Math.hypot(...refined.normals.subarray(i, i + 3))).toBeCloseTo(1, 4);
  });

  it.each(["female", "male"] as const)("prepares the exact deterministic %s mesh shared by the renderer and bake", (appearance) => {
    const original = source(appearance), first = prepareTestHead(original, appearance), repeated = prepareTestHead(original, appearance);
    for (const key of ["positions", "normals", "triangles", "edges", "surfaceDetail"] as const) {
      expect(Buffer.from(first[key].buffer).equals(Buffer.from(repeated[key].buffer))).toBe(true);
    }
    for (const key of HEAD_MORPHS) expect(Buffer.from(first.morphs[key].buffer).equals(Buffer.from(repeated.morphs[key].buffer))).toBe(true);
    expect(first.positions.length / 3).toBeLessThan(65_536);
    expect(first.surfaceDetail).toHaveLength(first.positions.length);
    expect(eyeRegions(first).subarray(0, original.positions.length)).toEqual(eyeRegions(original));
    const crown = (head: HumanHeadGeometry) => head.positions.reduce((value, next, i) => i % 3 === 1 ? Math.max(value, next) : value, -Infinity);
    expect(crown(first) - crown(original)).toBeGreaterThan(.02);
    expect(crown(first) - crown(original)).toBeLessThan(.06);
    for (const values of [first.positions, first.normals, first.surfaceDetail, ...Object.values(first.morphs)]) expect(values.every(Number.isFinite)).toBe(true);
  });
});
