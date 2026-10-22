import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BufferAttribute, BufferGeometry, FrontSide, Mesh, MeshBasicMaterial, Raycaster, Vector3 } from "three";
import { decodeHumanHead, HEAD_MORPHS } from "./human-head-geometry";
import { createShortHairHead } from "./test-hologram-hair";
import { appendSweptLocks } from "./test-hologram-hair-locks";
import { HEAD_ATTRIBUTES, sampleHead } from "./test-hologram-particles";

const source = () => Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;

describe("the restrained 3D scalp groom", () => {
  it.each(["female", "male"] as const)("preserves the %s face and every authored articulation", (appearance) => {
    const original = decodeHumanHead(source(), appearance), hair = createShortHairHead(original);
    expect(hair.positions.subarray(0, original.positions.length)).toEqual(original.positions);
    expect(hair.normals.subarray(0, original.normals.length)).toEqual(original.normals);
    expect(hair.surfaceDetail.length).toBe(hair.positions.length);
    expect(hair.surfaceDetail.subarray(0, original.positions.length).every((value) => value === 0)).toBe(true);
    expect(hair.surfaceDetail.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)).toBe(true);
    expect(hair.positions.length).toBeGreaterThan(original.positions.length);
    expect(hair.positions.length / 3).toBeLessThan(65_536);
    for (const morph of HEAD_MORPHS) {
      expect(hair.morphs[morph].subarray(0, original.positions.length)).toEqual(original.morphs[morph]);
      expect(hair.morphs[morph].length).toBe(hair.positions.length);
      expect(hair.morphs[morph].every(Number.isFinite)).toBe(true);
    }
    const retained = new Set<string>();
    for (let i = 0; i < hair.triangles.length; i += 3) retained.add(Array.from(hair.triangles.subarray(i, i + 3)).join(","));
    let protectedFaces = 0;
    for (let i = 0; i < original.triangles.length; i += 3) {
      const triangle = Array.from(original.triangles.subarray(i, i + 3));
      if (!triangle.every((index) => original.positions[index * 3 + 2] > .25 && original.positions[index * 3 + 1] < .35)) continue;
      expect(retained.has(triangle.join(","))).toBe(true); protectedFaces++;
    }
    expect(protectedFaces).toBeGreaterThan(500);
    for (const indices of [hair.triangles, hair.edges]) expect(indices.every((value) => value < hair.positions.length / 3)).toBe(true);
    for (let i = original.positions.length; i < hair.positions.length; i += 3) {
      expect(hair.positions[i + 1]).toBeGreaterThan(.05);
      expect(hair.positions[i + 1]).toBeLessThan(1.10);
      expect(Math.abs(hair.positions[i])).toBeLessThan(.76);
      expect(Math.hypot(...hair.normals.subarray(i, i + 3))).toBeCloseTo(1, 4);
    }
  });

  it("is deterministic, extends the crown in 3D and samples the groom without increasing particle budgets", () => {
    const head = decodeHumanHead(source(), "female"), first = createShortHairHead(head), second = createShortHairHead(head);
    expect(first.positions).toEqual(second.positions); expect(first.normals).toEqual(second.normals);
    expect(first.triangles).toEqual(second.triangles);
    const crown = (positions: Float32Array) => positions.reduce((maximum, value, index) => index % 3 === 1 ? Math.max(maximum, value) : maximum, -Infinity);
    expect(crown(first.positions) - crown(head.positions)).toBeGreaterThan(.025);
    const sampled = sampleHead(first, 4096);
    expect(sampled).toHaveLength(HEAD_ATTRIBUTES.length);
    for (const values of sampled) { expect(values.length).toBe(4096 * 3); expect(values.every(Number.isFinite)).toBe(true); }
    expect(crown(sampled[0])).toBeGreaterThan(crown(head.positions));
  });

  it("builds closed outward-facing locks with real volume on every side of the scalp", () => {
    const head = decodeHumanHead(source(), "female"), positions: number[] = [], normals: number[] = [], triangles: number[] = [];
    const count = appendSweptLocks(head, positions, normals, triangles), edges = new Map<string, number>();
    let volume = 0;
    for (let i = 0; i < triangles.length; i += 3) {
      const [a, b, c] = triangles.slice(i, i + 3).map((index) => index * 3);
      volume += (positions[a] * (positions[b + 1] * positions[c + 2] - positions[b + 2] * positions[c + 1])
        + positions[a + 1] * (positions[b + 2] * positions[c] - positions[b] * positions[c + 2])
        + positions[a + 2] * (positions[b] * positions[c + 1] - positions[b + 1] * positions[c])) / 6;
      for (let side = 0; side < 3; side++) {
        const from = triangles[i + side], to = triangles[i + (side + 1) % 3];
        const key = `${Math.min(from, to)}:${Math.max(from, to)}`; edges.set(key, (edges.get(key) ?? 0) + 1);
      }
    }
    expect(count).toBeGreaterThan(10_000); expect(count).toBeLessThan(12_000);
    expect([...edges.values()].every((uses) => uses === 2)).toBe(true);
    expect(volume).toBeGreaterThan(.025);
    for (const [axis, sign] of [[0, 1], [0, -1], [2, 1], [2, -1]]) {
      expect(positions.some((value, index) => index % 3 === axis && value * sign > .45)).toBe(true);
    }
  });

  // Hundreds of full-mesh visibility probes also run with CI coverage instrumentation.
  it("shows several staggered front waves instead of hiding every lock behind one ridge", () => {
    const head = createShortHairHead(decodeHumanHead(source(), "female"));
    const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(head.positions, 3));
    geometry.setIndex(new BufferAttribute(head.triangles, 1));
    const material = new MeshBasicMaterial({ side: FrontSide }), mesh = new Mesh(geometry, material);
    mesh.updateMatrixWorld();
    const firstFrontVertex = head.positions.length / 3 - 2000, visibleLocks = new Set<number>();
    for (let x = -.45; x <= .45; x += .05) for (let y = .50; y < 1.1; y += .025) {
      const hit = new Raycaster(new Vector3(x, y, 3), new Vector3(0, 0, -1)).intersectObject(mesh)[0];
      if (hit?.face && hit.face.a >= firstFrontVertex) visibleLocks.add(Math.floor((hit.face.a - firstFrontVertex) / 200));
    }
    geometry.dispose(); material.dispose();
    expect(visibleLocks.size).toBeGreaterThanOrEqual(8);
  }, 30_000);

  it("shades generated hair troughs while preserving exposed crests and every original facial vertex", () => {
    const head = createShortHairHead(decodeHumanHead(source(), "female"));
    const firstLock = head.positions.length / 3 - 11_000;
    let lightCrests = 0, occludedTroughs = 0;
    for (let vertex = firstLock; vertex < head.positions.length / 3; vertex++) {
      const offset = vertex * 3;
      expect(head.surfaceDetail[offset]).toBe(1);
      if (head.surfaceDetail[offset + 1] < .12) lightCrests++;
      if (head.surfaceDetail[offset + 1] > .65) occludedTroughs++;
    }
    expect(lightCrests / 11_000).toBeGreaterThan(.05);
    expect(occludedTroughs / 11_000).toBeGreaterThan(.30);
    const sampled = sampleHead(head, 4096)[HEAD_ATTRIBUTES.indexOf("surfaceDetail")];
    expect(sampled.some((value, index) => index % 3 === 1 && value > .5)).toBe(true);
  });
});
