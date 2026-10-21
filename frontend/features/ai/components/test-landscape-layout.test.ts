import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import sharp from "sharp";
import { Mesh, MeshBasicMaterial, PerspectiveCamera, Raycaster, Vector3, type BufferGeometry } from "three";
import { describe, expect, it } from "vitest";
import { decodeLandscapeGeometry } from "./test-landscape-assets";
import { applyLandscapePlacement, FOUNDATION_PLACEMENT, LANDSCAPE_PITCH_LIMIT, LANDSCAPE_POSITION, LANDSCAPE_TARGET, landscapeLookAround, ORIGINAL_MOUNTAINS, panoramicPlacements, SNOW_ISLAND, type Placement } from "./test-landscape-layout";

const geometry = (name: string) => decodeLandscapeGeometry(Uint8Array.from(readFileSync(resolve(`public/ai/test-landscape/${name}.bin`))).buffer);
const camera = () => {
  const result = new PerspectiveCamera(30, 16 / 9, .1, 2000);
  result.position.set(...LANDSCAPE_POSITION); result.lookAt(...LANDSCAPE_TARGET); return result;
};
const instances = (shape: BufferGeometry, surface: MeshBasicMaterial, placements: Placement[]) => placements.map((placement) => {
  const mesh = new Mesh(shape, surface); applyLandscapePlacement(mesh, placement); return mesh;
});

describe("panoramic alpine layout", () => {
  it("restores the exact forward pose and closes every full turn without translating", () => {
    const view = camera(), baseline = view.quaternion.clone(), position = view.position.clone(), look = landscapeLookAround(view);
    for (const turns of [-100, -1, 0, 1, 100]) {
      look(turns * Math.PI * 2, 0);
      expect(view.quaternion.angleTo(baseline)).toBeLessThan(1e-7); expect(view.position.equals(position)).toBe(true);
    }
    look(Math.PI / 2, 0); expect(view.quaternion.angleTo(baseline)).toBeCloseTo(Math.PI / 2);
    look(0, 0); expect(view.quaternion.equals(baseline)).toBe(true);
  });

  it("bounds pitch and resets malformed controls without poisoning camera matrices", () => {
    const view = camera(), look = landscapeLookAround(view);
    look(0, LANDSCAPE_PITCH_LIMIT); const upper = view.quaternion.clone();
    look(0, 1000); expect(view.quaternion.equals(upper)).toBe(true);
    look(0, -LANDSCAPE_PITCH_LIMIT); const lower = view.quaternion.clone();
    look(0, -1000); expect(view.quaternion.equals(lower)).toBe(true);
    look(Number.NaN, Infinity);
    expect(view.quaternion.equals(camera().quaternion)).toBe(true);
    expect(view.matrixWorld.elements.every(Number.isFinite)).toBe(true);
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
