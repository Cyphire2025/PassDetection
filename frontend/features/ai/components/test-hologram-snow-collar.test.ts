import { readFileSync } from "node:fs";
import { DoubleSide, Mesh, MeshBasicMaterial, Raycaster, Texture, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { decodeLandscapeGeometry } from "./test-landscape-assets";
import { createSnowCollar, snowCollarGeometry } from "./test-hologram-snow-collar";

const loadGround = () => decodeLandscapeGeometry(Uint8Array.from(readFileSync("public/ai/test-landscape/ground.bin")).buffer);

describe("terrain-integrated pedestal powder", () => {
  it("raises a real irregular mound while retaining exact ground heights and atlas UVs at its skirt", () => {
    const ground = loadGround(), collar = snowCollarGeometry(ground), material = new MeshBasicMaterial();
    const ray = new Raycaster(new Vector3(), new Vector3(0, -1, 0));
    try {
      const positions = collar.getAttribute("position"), sourceY = collar.getAttribute("sourceY"), across = collar.getAttribute("across");
      let maxMound = 0, minRim = Infinity, maxRim = 0;
      for (let index = 0; index < positions.count; index += 7) {
        const mound = positions.getY(index) - sourceY.getX(index) - .003;
        expect(mound).toBeGreaterThanOrEqual(-.000001); maxMound = Math.max(maxMound, mound);
        if (across.getX(index) <= 0 || across.getX(index) >= 1) expect(mound).toBeCloseTo(0, 5);
        if (across.getX(index) > .95 && across.getX(index) < 1) {
          const radius = Math.hypot(positions.getX(index), positions.getZ(index)); minRim = Math.min(minRim, radius); maxRim = Math.max(maxRim, radius);
        }
      }
      expect(maxMound).toBeGreaterThan(.16); expect(maxMound).toBeLessThan(.28);
      expect(maxRim - minRim).toBeGreaterThan(.20); expect(positions.count).toBeLessThan(50000);
      const collarMesh = new Mesh(collar, material);
      ray.ray.origin.set(positions.getX(600), 20, positions.getZ(600));
      expect(ray.intersectObject(collarMesh, false).length).toBeGreaterThan(0);
    } finally { collar.dispose(); ground.dispose(); material.dispose(); }
  });

  // Exhaustive atlas probes use full terrain raycasts, including under CI coverage.
  it("never interpolates across unrelated atlas charts inside a powder triangle", () => {
    const ground = loadGround(), collar = snowCollarGeometry(ground), material = new MeshBasicMaterial({ side: DoubleSide }), source = new Mesh(ground, material);
    const ray = new Raycaster(new Vector3(), new Vector3(0, -1, 0));
    try {
      const positions = collar.getAttribute("position"), uv = collar.getAttribute("uv"), sourceY = collar.getAttribute("sourceY"), triangles = collar.getIndex()!;
      // Test triangle interiors: seam vertices may legitimately have two UVs,
      // but an interpolated interior must belong entirely to one authored chart.
      for (let face = 0; face < triangles.count; face += 3 * 19) {
        let x = 0, z = 0, y = 0, u = 0, v = 0;
        for (let corner = 0; corner < 3; corner++) {
          const vertex = triangles.getX(face + corner);
          x += positions.getX(vertex) / 3; z += positions.getZ(vertex) / 3; y += sourceY.getX(vertex) / 3;
          u += uv.getX(vertex) / 3; v += uv.getY(vertex) / 3;
        }
        ray.ray.origin.set(x, 20, z);
        // The authored terrain contains overhangs. Match the source surface's
        // height instead of assuming the first downward hit is the only layer.
        const hit = ray.intersectObject(source, false).find((intersection) => Math.abs(intersection.point.y - y) < .00001);
        expect(hit).toBeDefined();
        expect(u).toBeCloseTo(hit!.uv!.x, 4); expect(v).toBeCloseTo(hit!.uv!.y, 4);
      }
    } finally { collar.dispose(); ground.dispose(); material.dispose(); }
  }, 30_000);

  it("retires its geometry and surface exactly once without disposing shared terrain or textures", () => {
    const ground = loadGround(), snow = new Texture(), wind = new Texture(), collar = createSnowCollar(ground, snow, wind);
    let owned = 0, borrowed = 0;
    for (const resource of [ground, snow, wind]) resource.addEventListener("dispose", () => borrowed++);
    collar.mesh.geometry.addEventListener("dispose", () => owned++); collar.mesh.material.addEventListener("dispose", () => owned++);
    collar.update(.7, 12); expect(collar.mesh.material.uniforms.opacity.value).toBe(.7);
    collar.dispose(); collar.dispose(); collar.update(1, 14);
    expect(owned).toBe(2); expect(borrowed).toBe(0); expect(collar.mesh.material.uniforms.time.value).toBe(12);
    ground.dispose(); snow.dispose(); wind.dispose();
  });
});
