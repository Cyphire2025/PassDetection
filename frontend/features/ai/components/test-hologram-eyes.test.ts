import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BufferAttribute, BufferGeometry, FrontSide, Mesh, MeshBasicMaterial, Raycaster, Triangle, Vector3 } from "three";
import { decodeHumanHead } from "./human-head-geometry";
import { CORNEA_APERTURE, IRIS_EXPANSION, eyeRegions } from "./test-hologram-eyes";
import { createShortHairHead } from "./test-hologram-hair";
import { HEAD_ATTRIBUTES, sampleHead } from "./test-hologram-particles";

const source = () => Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;

describe("authored 3D eye regions", () => {
  it.each(["female", "male"] as const)("labels only the separate %s iris and eyeball surfaces", (appearance) => {
    const original = decodeHumanHead(source(), appearance), head = createShortHairHead(original);
    const regions = eyeRegions(head), originalRegions = eyeRegions(original);
    expect(regions.subarray(0, original.positions.length)).toEqual(originalRegions);
    expect(regions.subarray(original.positions.length).every((value) => value === 0)).toBe(true);
    expect(eyeRegions(head)).toBe(regions);
    const totals = [0, 0, 0], sides = [0, 0];
    for (let vertex = 0; vertex < head.positions.length / 3; vertex++) {
      const kind = regions[vertex * 3 + 2]; totals[kind]++;
      if (kind === 0) continue;
      expect(Math.abs(regions[vertex * 3])).toBeLessThanOrEqual(1);
      expect(Math.abs(regions[vertex * 3 + 1])).toBeLessThanOrEqual(1);
      if (kind === 1) sides[head.positions[vertex * 3] > 0 ? 1 : 0]++;
    }
    // These are separate indexed surfaces in the reviewed asset, not circular
    // markings projected onto cheek, eyelid, or newly generated hair vertices.
    expect(totals.slice(1)).toEqual([802, 1028]); expect(sides).toEqual([401, 401]);
    for (let i = 0; i < head.triangles.length; i += 3) {
      const kinds = Array.from(head.triangles.subarray(i, i + 3), (vertex) => regions[vertex * 3 + 2]);
      expect(new Set(kinds).size).toBe(1);
    }
    const sampled = sampleHead(head, 16_384)[HEAD_ATTRIBUTES.indexOf("eyeRegion")];
    expect(sampled.every(Number.isFinite)).toBe(true);
    const sampledKinds = Array.from(sampled).filter((_, index) => index % 3 === 2);
    expect(sampledKinds.some((kind) => Math.abs(kind - 1) < .0001)).toBe(true);
    expect(sampledKinds.some((kind) => Math.abs(kind - 2) < .0001)).toBe(true);
    expect(sampledKinds.every((kind) => Math.abs(kind - Math.round(kind)) < .0001)).toBe(true);
  });

  it("exposes both real irises through the cornea while the authored blink closes them", () => {
    const head = decodeHumanHead(source(), "female"), regions = eyeRegions(head);
    const visibleRegion = (x: number, blink: number, clearCornea: boolean) => {
      const positions = Float32Array.from(head.positions, (value, index) => value + head.morphs.blink[index] * blink);
      for (let vertex = 0; vertex < positions.length / 3; vertex++) if (regions[vertex * 3 + 2] === 1) {
        positions[vertex * 3] += regions[vertex * 3] * IRIS_EXPANSION;
        positions[vertex * 3 + 1] += regions[vertex * 3 + 1] * IRIS_EXPANSION;
      }
      const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(positions, 3));
      geometry.setIndex(new BufferAttribute(head.triangles, 1));
      const material = new MeshBasicMaterial({ side: FrontSide }), mesh = new Mesh(geometry, material);
      mesh.updateMatrixWorld();
      const hits = new Raycaster(new Vector3(x, .172, 3), new Vector3(0, 0, -1)).intersectObject(mesh);
      let visible = -1;
      for (const hit of hits) {
        const face = hit.face!;
        const weights = Triangle.getBarycoord(hit.point, new Vector3().fromArray(positions, face.a * 3),
          new Vector3().fromArray(positions, face.b * 3), new Vector3().fromArray(positions, face.c * 3), new Vector3())!;
        const region = new Vector3();
        [face.a, face.b, face.c].forEach((vertex, index) => region.addScaledVector(new Vector3().fromArray(regions, vertex * 3), weights.getComponent(index)));
        if (clearCornea && region.z > 1.5 && Math.hypot(region.x, region.y) < CORNEA_APERTURE) continue;
        visible = Math.round(region.z); break;
      }
      geometry.dispose(); material.dispose(); return visible;
    };
    for (const x of [-.234, .234]) {
      expect(visibleRegion(x, 0, false)).toBe(2);
      expect(visibleRegion(x, 0, true)).toBe(1);
      expect(visibleRegion(x, 1, true)).toBe(0);
    }
  });
});
