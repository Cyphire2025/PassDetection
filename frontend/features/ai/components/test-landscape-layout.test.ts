import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import sharp from "sharp";
import { Mesh, MeshBasicMaterial, PerspectiveCamera, Raycaster, Vector3, type BufferGeometry } from "three";
import { describe, expect, it } from "vitest";
import { decodeLandscapeGeometry } from "./test-landscape-assets";
import { applyLandscapePlacement, FOUNDATION_PLACEMENT, LANDSCAPE_FOV, LANDSCAPE_GROUND_ANCHOR, LANDSCAPE_GROUND_FOOTPRINT, LANDSCAPE_POSITION, LANDSCAPE_TARGET, ORIGINAL_GROUND, ORIGINAL_MOUNTAINS, panoramicPlacements, SNOW_ISLAND, type Placement } from "./test-landscape-layout";

const geometry = (name: string) => decodeLandscapeGeometry(Uint8Array.from(readFileSync(resolve(`public/ai/test-landscape/${name}.bin`))).buffer);
const camera = () => {
  const result = new PerspectiveCamera(LANDSCAPE_FOV, 16 / 9, .1, 2000);
  result.position.set(...LANDSCAPE_POSITION); result.lookAt(...LANDSCAPE_TARGET); return result;
};
const instances = (shape: BufferGeometry, surface: MeshBasicMaterial, placements: Placement[]) => placements.map((placement) => {
  const mesh = new Mesh(shape, surface); applyLandscapePlacement(mesh, placement); return mesh;
});

describe("panoramic alpine layout", () => {
  it("anchors the portrait on the actual original ground at the reference camera distance", () => {
    const shape = geometry("ground"), surface = new MeshBasicMaterial();
    try {
      const meshes = instances(shape, surface, ORIGINAL_GROUND), ray = new Raycaster(new Vector3(0, 10, 0), new Vector3(0, -1, 0));
      const ground = ray.intersectObjects(meshes, false)[0].point;
      expect(ground.distanceTo(new Vector3(...LANDSCAPE_GROUND_ANCHOR))).toBeLessThan(1e-6);
      const view = camera(); view.aspect = 2; view.updateProjectionMatrix(); view.updateMatrixWorld();
      const projected = ground.clone().project(view);
      expect((projected.x + 1) / 2).toBeCloseTo(.5);
      expect((1 - projected.y) / 2).toBeCloseTo(.6924, 3);
      const right = new Vector3(1, 0, 0).applyQuaternion(view.quaternion).multiplyScalar(LANDSCAPE_GROUND_FOOTPRINT / 2);
      const left = ground.clone().sub(right).project(view), end = ground.clone().add(right).project(view);
      const width = (end.x - left.x) * 1536 / 2;
      // The more distant camera keeps the circular platform's perspective
      // flatter. At this fixed aspect its 9.3632-unit footprint is ~456px.
      expect(width).toBeGreaterThan(450); expect(width).toBeLessThan(465);
    } finally { shape.dispose(); surface.dispose(); }
  });

  it("places the original main summit near the reference skyline", () => {
    const shape = geometry("mountain"), surface = new MeshBasicMaterial();
    try {
      const mountain = new Mesh(shape, surface); applyLandscapePlacement(mountain, ORIGINAL_MOUNTAINS[2]);
      const view = camera(); view.aspect = 2; view.updateProjectionMatrix(); view.updateMatrixWorld();
      const positions = shape.getAttribute("position"), point = new Vector3();
      let summit = 1;
      for (let index = 0; index < positions.count; index++) {
        point.fromBufferAttribute(positions, index).applyMatrix4(mountain.matrixWorld).project(view);
        if (Math.abs(point.x) <= 1 && point.z < 1) summit = Math.min(summit, (1 - point.y) / 2);
      }
      expect(summit).toBeGreaterThan(.145); expect(summit).toBeLessThan(.16);
    } finally { shape.dispose(); surface.dispose(); }
  });

  it("covers surrounding horizon directions with actual opaque-inner mountain triangles", () => {
    const shape = geometry("mountain"), surface = new MeshBasicMaterial();
    try {
      const placements = panoramicPlacements(), meshes = instances(shape, surface, [...ORIGINAL_MOUNTAINS, ...placements.mountains]);
      const origin = new Vector3(...LANDSCAPE_POSITION), ray = new Raycaster(origin, new Vector3(), .1, 500), local = new Vector3();
      const heading = Math.atan2(LANDSCAPE_TARGET[0] - origin.x, LANDSCAPE_TARGET[2] - origin.z), missing: number[] = [];
      // The original forward valley remains intentionally open between peaks.
      for (let degrees = 65; degrees <= 295; degrees += 5) {
        const angle = heading + degrees * Math.PI / 180;
        ray.ray.direction.set(Math.sin(angle), 0, Math.cos(angle));
        const solid = ray.intersectObjects(meshes, false).some((hit) => {
          hit.object.worldToLocal(local.copy(hit.point)); return Math.hypot(local.x, local.z) * .1085 < .7;
        });
        if (!solid) missing.push(degrees);
      }
      expect(missing).toEqual([]);
      expect(placements.mountains.length).toBeLessThanOrEqual(16);
    } finally { shape.dispose(); surface.dispose(); }
  });

  it("keeps a continuous textured foundation beneath all headings and modest downward pitches", () => {
    const shape = geometry("patch"), surface = new MeshBasicMaterial();
    try {
      const floor = new Mesh(shape, surface);
      applyLandscapePlacement(floor, FOUNDATION_PLACEMENT);
      const ray = new Raycaster(new Vector3(...LANDSCAPE_POSITION), new Vector3(), .1, 500);
      for (let degrees = 0; degrees < 360; degrees += 5) for (const down of [.04, .12, .35, .6]) {
        const angle = degrees * Math.PI / 180;
        ray.ray.direction.set(Math.sin(angle) * Math.cos(down), -Math.sin(down), Math.cos(angle) * Math.cos(down));
        expect(ray.intersectObject(floor, false).length, `heading ${degrees}, depression ${down}`).toBeGreaterThan(0);
      }
    } finally { shape.dispose(); surface.dispose(); }
  });

  it("tiles only snow pixels inside the original atlas island and never its black padding", async () => {
    const { data, info } = await sharp(resolve("public/ai/test-landscape/ground-color.webp")).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
    const [u0, v0, u1, v1] = SNOW_ISLAND;
    let min = 255, max = 0, pixels = 0;
    for (let y = Math.floor(v0 * info.height); y <= Math.ceil(v1 * info.height); y++) for (let x = Math.floor(u0 * info.width); x <= Math.ceil(u1 * info.width); x++) {
      const offset = (y * info.width + x) * 4;
      min = Math.min(min, data[offset], data[offset + 1], data[offset + 2]);
      max = Math.max(max, data[offset], data[offset + 1], data[offset + 2]); pixels++;
      expect(data[offset + 3]).toBe(255);
    }
    expect(pixels).toBeGreaterThan(100_000); expect(min).toBeGreaterThan(64); expect(max - min).toBeGreaterThan(32);
    const patch = geometry("patch"), uv = patch.getAttribute("uv");
    try {
      const us = Array.from({ length: uv.count }, (_, index) => uv.getX(index)), vs = Array.from({ length: uv.count }, (_, index) => uv.getY(index));
      expect(u0).toBeGreaterThan(Math.min(...us)); expect(u1).toBeLessThan(Math.max(...us));
      expect(v0).toBeGreaterThan(Math.min(...vs)); expect(v1).toBeLessThan(Math.max(...vs));
    } finally { patch.dispose(); }
  });
});
