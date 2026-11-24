import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BoxGeometry, BufferAttribute, BufferGeometry, DoubleSide, Mesh, MeshBasicMaterial, Raycaster, Triangle, Vector3 } from "three";
import { decodeHumanHead, HEAD_MORPHS, type HumanHeadGeometry } from "./human-head-geometry";
import { createShortHairHead } from "./test-hologram-hair";
import { HEAD_ATTRIBUTES, sampleHead } from "./test-hologram-particles";
import { createHeadVolume } from "./test-hologram-volume";
import { CORNEA_APERTURE, eyeRegions } from "./test-hologram-eyes";

function boxes(...ranges: [number, number][]): HumanHeadGeometry {
  const positions: number[] = [], normals: number[] = [], triangles: number[] = [];
  for (const [back, front] of ranges) {
    const box = new BoxGeometry(2, 2, front - back).translate(0, 0, (back + front) / 2);
    const offset = positions.length / 3;
    positions.push(...box.getAttribute("position").array); normals.push(...box.getAttribute("normal").array);
    triangles.push(...Array.from(box.index!.array, (index) => index + offset)); box.dispose();
  }
  const morphs = Object.fromEntries(HEAD_MORPHS.map((name, morph) => [name, Float32Array.from(positions, (value, index) =>
    value * .01 * (morph + 1) + .003 * (index % 3))])) as HumanHeadGeometry["morphs"];
  return { positions: new Float32Array(positions), normals: new Float32Array(normals),
    triangles: new Uint16Array(triangles), edges: new Uint16Array(), morphs };
}

describe("particle-only head volume", () => {
  it("unions overlapping solids, including coplanar entries, without filling an exterior gap", () => {
    const intervals = (head: HumanHeadGeometry) => createHeadVolume(head).intervals(0, 0).map(({ back, front }) => [back.z, front.z]);
    expect(intervals(boxes([-1, 1]))).toEqual([[-1, 1]]); // Shared triangle diagonal.
    expect(intervals(boxes([-1, 1], [0, 2]))).toEqual([[-1, 2]]);
    expect(intervals(boxes([-1, 1], [-1, 2]))).toEqual([[-1, 2]]);
    expect(intervals(boxes([-2, -1], [1, 2]))).toEqual([[-2, -1], [1, 2]]);
    expect(createHeadVolume(boxes([-1, 1])).intervals(1.01, 0)).toEqual([]);
  });

  it("keeps the fixed budget, a detailed outer layer, and stratified true interior with linear morphs", () => {
    const head = boxes([-1, 1]), original = head.positions.slice(), count = 4096;
    const sampled = sampleHead(head, count), repeated = sampleHead(head, count), surfaceCount = Math.ceil(count * .6);
    expect(sampled).toEqual(repeated); expect(head.positions).toEqual(original);
    for (const attribute of sampled) expect(attribute).toHaveLength(count * 3);
    const positions = sampled[0], detail = sampled[HEAD_ATTRIBUTES.indexOf("surfaceDetail")], layers = new Array<number>(8).fill(0);
    for (let point = 0; point < count; point++) {
      const offset = point * 3, x = positions[offset], y = positions[offset + 1], z = positions[offset + 2];
      expect(Math.hypot(...sampled[1].subarray(offset, offset + 3))).toBeCloseTo(1, 5);
      if (point < surfaceCount) {
        expect(Math.max(Math.abs(x), Math.abs(y), Math.abs(z))).toBeCloseTo(1, 6);
        expect(detail[offset + 2]).toBe(0);
      } else {
        expect(Math.max(Math.abs(x), Math.abs(y))).toBeLessThan(1); expect(Math.abs(z)).toBeLessThanOrEqual(.950001);
        expect(detail[offset + 2]).toBeCloseTo(1 - Math.abs(z), 6);
        layers[Math.min(7, Math.floor((z + .95) / 1.9 * 8))]++;
      }
      for (let morph = 0; morph < HEAD_MORPHS.length; morph++) for (let axis = 0; axis < 3; axis++) {
        expect(sampled[morph + 2][offset + axis]).toBeCloseTo(positions[offset + axis] * .01 * (morph + 1) + .003 * axis, 6);
      }
    }
    expect(Math.max(...layers) - Math.min(...layers)).toBeLessThanOrEqual(1);
    expect(layers.reduce((total, value) => total + value)).toBe(count - surfaceCount);
  });

  // Validate the full particle budget with instrumented geometry on slower CI CPUs.
  it.each(["female", "male"] as const)("fills the actual %s head with articulated interior grains and no exterior filler", (appearance) => {
    const source = Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;
    const head = createShortHairHead(decodeHumanHead(source, appearance)), started = performance.now();
    const count = 65_536, sampled = sampleHead(head, count), elapsed = performance.now() - started;
    console.info(`${appearance} ${count}-particle volume sampling: ${elapsed.toFixed(1)}ms`);
    const surfaceCount = Math.ceil(count * .6), positions = sampled[0], detail = sampled[HEAD_ATTRIBUTES.indexOf("surfaceDetail")];
    const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(head.positions, 3));
    geometry.setIndex(new BufferAttribute(head.triangles, 1));
    const material = new MeshBasicMaterial({ side: DoubleSide }), mesh = new Mesh(geometry, material), direction = new Vector3(0, 0, 1);
    mesh.updateMatrixWorld();
    let deep = 0, articulated = 0;
    for (let point = surfaceCount; point < count; point++) {
      const offset = point * 3;
      expect(detail[offset + 2]).toBeGreaterThanOrEqual(.049999); expect(detail[offset + 2]).toBeLessThanOrEqual(1);
      if (detail[offset + 2] > .5) deep++;
      if (Math.hypot(...sampled[2].subarray(offset, offset + 3)) > .005) articulated++;
      expect(sampled[HEAD_ATTRIBUTES.indexOf("eyeRegion")].subarray(offset, offset + 3)).toEqual(new Float32Array(3));
      if ((point - surfaceCount) % 401 !== 0) continue;
      const origin = new Vector3().fromArray(positions, offset);
      const intersections = new Raycaster(origin, direction).intersectObject(mesh);
      // Independent Three.js triangle raycasts: a point in the solid has one
      // more outward than inward crossing on its remaining path to infinity.
      expect(intersections.reduce((winding, hit) => winding + Math.sign(hit.face!.normal.z), 0)).toBeGreaterThan(0);
    }
    expect(deep).toBeGreaterThan((count - surfaceCount) * .4); expect(articulated).toBeGreaterThan(300);
    for (const values of sampled) expect(values.every(Number.isFinite)).toBe(true);
    geometry.dispose(); material.dispose();
  }, 30_000);

  it.each(["female", "male"] as const)("keeps the %s optical chamber clear while retaining the volume behind each iris", (appearance) => {
    const source = Uint8Array.from(readFileSync(resolve("public/ai/human-head/head-v1.bin"))).buffer;
    const head = createShortHairHead(decodeHumanHead(source, appearance)), regions = eyeRegions(head), volume = createHeadVolume(head);
    const indices: number[] = [];
    for (let face = 0; face < head.triangles.length; face += 3) if (regions[head.triangles[face] * 3 + 2] > .5) {
      indices.push(...head.triangles.subarray(face, face + 3));
    }
    const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(head.positions, 3));
    geometry.setIndex(indices);
    const material = new MeshBasicMaterial({ side: DoubleSide }), mesh = new Mesh(geometry, material);
    mesh.updateMatrixWorld();
    let clearChambers = 0;
    for (const side of [-1, 1]) for (let ix = -8; ix <= 8; ix++) for (let iy = -8; iy <= 8; iy++) {
      const x = side * .234 + ix * .0045, y = .172 + iy * .0045;
      const hits = new Raycaster(new Vector3(x, y, 3), new Vector3(0, 0, -1)).intersectObject(mesh);
      const cornea = hits.find((hit) => {
        const face = hit.face!;
        if (regions[face.a * 3 + 2] !== 2) return false;
        const weights = Triangle.getBarycoord(hit.point, new Vector3().fromArray(head.positions, face.a * 3),
          new Vector3().fromArray(head.positions, face.b * 3), new Vector3().fromArray(head.positions, face.c * 3), new Vector3())!;
        const region = new Vector3();
        [face.a, face.b, face.c].forEach((vertex, corner) => region.addScaledVector(new Vector3().fromArray(regions, vertex * 3), weights.getComponent(corner)));
        return Math.hypot(region.x, region.y) < CORNEA_APERTURE && hit.face!.normal.z > 0;
      });
      const iris = hits.find((hit) => regions[hit.face!.a * 3 + 2] === 1 && cornea && hit.point.z < cornea.point.z);
      if (!cornea || !iris) continue;
      const intervals = volume.intervals(x, y);
      for (const { back, front } of intervals) {
        expect(Math.min(front.z, cornea.point.z) - Math.max(back.z, iris.point.z)).toBeLessThanOrEqual(.000001);
      }
      // The center of the head remains solid along every clear eye ray: this
      // removes a shallow optical chamber, not a tunnel through the skull.
      expect(intervals.some(({ back, front }) => back.z < 0 && front.z > 0)).toBe(true);
      clearChambers++;
    }
    expect(clearChambers).toBeGreaterThan(400);
    geometry.dispose(); material.dispose();
  });
});
