// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";
import { BufferAttribute, BufferGeometry, DataUtils, DoubleSide, Mesh, MeshBasicMaterial, Raycaster, Triangle, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { decodeHumanHead } from "./human-head-geometry";
import { prepareTestHead } from "./test-hologram-adult-head";
import { decodeHeadFieldData, HEAD_FIELD_SIDE, type HeadFieldData } from "./test-head-field-format";
import { eyeRegions } from "./test-hologram-eyes";

const root = resolve("public/ai/human-head");
function sample(data: HeadFieldData, field: number, position: Vector3, channel: number) {
  const p = position.toArray().map((value, axis) => Math.max(0, Math.min(63, (value - data.min[axis]) / data.size[axis] * 64 - .5)));
  const base = p.map(Math.floor), fraction = p.map((value, axis) => value - base[axis]);
  let value = 0;
  for (let z = 0; z < 2; z++) for (let y = 0; y < 2; y++) for (let x = 0; x < 2; x++) {
    const index = ((Math.min(63, base[2] + z) * 64 + Math.min(63, base[1] + y)) * 64 + Math.min(63, base[0] + x)) * 4 + channel;
    value += DataUtils.fromHalfFloat(data.arrays[field][index]) * (x ? fraction[0] : 1 - fraction[0])
      * (y ? fraction[1] : 1 - fraction[1]) * (z ? fraction[2] : 1 - fraction[2]);
  }
  return value;
}
const percentile = (values: number[], fraction: number) => [...values].sort((a, b) => a - b)[Math.floor((values.length - 1) * fraction)];

describe("baked fields against independent Three.js triangle intersections", () => {
  it.each(["female", "male"] as const)("preserves the %s boundary, gradient direction and articulated facial locations", (appearance) => {
    const head = prepareTestHead(decodeHumanHead(Uint8Array.from(readFileSync(resolve(root, "head-v1.bin"))).buffer, appearance), appearance);
    const data = decodeHeadFieldData(Uint8Array.from(gunzipSync(readFileSync(resolve(root, `fields-${appearance}-v1.bin.gz`)))).buffer, appearance);
    const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(head.positions, 3));
    geometry.setIndex(new BufferAttribute(head.triangles, 1));
    const material = new MeshBasicMaterial({ side: DoubleSide }), mesh = new Mesh(geometry, material), ray = new Raycaster();
    mesh.updateMatrixWorld();
    const surfaceErrors: number[] = [], morphErrors: number[] = [], directions: number[] = [];
    let inside = 0, outside = 0;
    const a = new Vector3(), b = new Vector3(), c = new Vector3(), weights = new Vector3();
    try {
      for (let row = 0; row < 11; row++) for (let column = 0; column < 9; column++) {
        ray.set(new Vector3(-.36 + column * .09, -.6 + row * .09, 2), new Vector3(0, 0, -1));
        const hit = ray.intersectObject(mesh)[0]; if (!hit?.face) continue;
        const corners = [hit.face.a, hit.face.b, hit.face.c];
        a.fromArray(head.positions, corners[0] * 3); b.fromArray(head.positions, corners[1] * 3); c.fromArray(head.positions, corners[2] * 3);
        Triangle.getBarycoord(hit.point, a, b, c, weights);
        const interpolate = (values: Float32Array) => new Vector3(...[0, 1, 2].map((axis) =>
          corners.reduce((sum, vertex, corner) => sum + values[vertex * 3 + axis] * weights.getComponent(corner), 0)));
        const normal = interpolate(head.normals).normalize(), gradient = new Vector3(...[0, 1, 2].map((axis) => sample(data, 0, hit.point, axis))).normalize();
        surfaceErrors.push(Math.abs(sample(data, 0, hit.point, 3))); directions.push(normal.dot(gradient));
        const expected = interpolate(head.morphs.jaw), actual = new Vector3(...[0, 1, 2].map((axis) => sample(data, 1, hit.point, axis)));
        morphErrors.push(actual.distanceTo(expected));
        if (sample(data, 0, hit.point.clone().addScaledVector(normal, -.09), 3) < 0) inside++;
        if (sample(data, 0, hit.point.clone().addScaledVector(normal, .09), 3) > 0) outside++;
      }
      const voxelDiagonal = Math.hypot(...data.size) / HEAD_FIELD_SIDE;
      console.info(`${appearance} fields: boundary p95=${percentile(surfaceErrors, .95).toFixed(4)}, jaw p95=${percentile(morphErrors, .95).toFixed(4)}, outward=${outside}/${surfaceErrors.length}, inward=${inside}/${surfaceErrors.length}`);
      expect(surfaceErrors.length).toBeGreaterThan(70); expect(percentile(surfaceErrors, .95)).toBeLessThan(voxelDiagonal);
      expect(percentile(morphErrors, .95)).toBeLessThan(.025);
      expect(percentile(directions, .5)).toBeGreaterThan(.7);
      expect(outside / surfaceErrors.length).toBeGreaterThan(.95); expect(inside / surfaceErrors.length).toBeGreaterThan(.85);
    } finally { geometry.dispose(); material.dispose(); }
  });

  it.each(["female", "male"] as const)("resolves both %s iris regions and keeps optical-chamber samples outside the solid", (appearance) => {
    const head = prepareTestHead(decodeHumanHead(Uint8Array.from(readFileSync(resolve(root, "head-v1.bin"))).buffer, appearance), appearance), regions = eyeRegions(head);
    const data = decodeHeadFieldData(Uint8Array.from(gunzipSync(readFileSync(resolve(root, `fields-${appearance}-v1.bin.gz`)))).buffer, appearance);
    const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(head.positions, 3));
    geometry.setIndex(new BufferAttribute(head.triangles, 1));
    const material = new MeshBasicMaterial({ side: DoubleSide }), mesh = new Mesh(geometry, material), ray = new Raycaster();
    mesh.updateMatrixWorld();
    let tested = 0, clear = 0, tagged = 0;
    try {
      for (const side of [-1, 1]) for (let y = .145; y <= .205; y += .01) for (let x = .205; x <= .265; x += .01) {
        ray.set(new Vector3(x * side, y, 2), new Vector3(0, 0, -1));
        const hits = ray.intersectObject(mesh);
        const cornea = hits.find((hit) => hit.face && regions[hit.face.a * 3 + 2] === 2);
        const iris = hits.find((hit) => hit.face && regions[hit.face.a * 3 + 2] === 1);
        if (!cornea || !iris) continue;
        const midpoint = cornea.point.clone().lerp(iris.point, .5);
        tested++; if (sample(data, 0, midpoint, 3) > 0) clear++;
        if (sample(data, 7, iris.point, 2) > .5) tagged++;
      }
      console.info(`${appearance} optical field: clear=${clear}/${tested}, iris metadata=${tagged}/${tested}`);
      expect(tested).toBeGreaterThan(40); expect(clear / tested).toBeGreaterThan(.6); expect(tagged / tested).toBeGreaterThan(.8);
    } finally { geometry.dispose(); material.dispose(); }
  });
});
