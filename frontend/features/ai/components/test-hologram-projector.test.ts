import { readFileSync } from "node:fs";
import { AdditiveBlending, BufferAttribute, BufferGeometry, Group, Material, MathUtils, Mesh, MeshBasicMaterial, Raycaster, ShaderMaterial, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { createHologramProjector, PROJECTOR } from "./test-hologram-projector";
import { CONTAINMENT, PEDESTAL } from "./test-hologram-platform";
import { decodeHumanHead } from "./human-head-geometry";
import { LANDSCAPE_POSITION, PLATFORM_HORIZONTAL_SCALE, PORTRAIT_HEAD_OFFSET_Y, PORTRAIT_HEAD_SCALE, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

describe("centered 3D hologram projector", () => {
  it("starts above the solid cap and fans upward within the enclosure without writing depth", () => {
    const projector = createHologramProjector();
    try {
      const aperture = projector.group.getObjectByName("Projector center light") as Mesh<BufferGeometry, ShaderMaterial>;
      const rays = projector.group.getObjectByName("Projector fanned light rays") as Mesh<BufferGeometry, ShaderMaterial>;
      projector.group.updateMatrixWorld(true);
      expect(aperture.position.x).toBe(0); expect(aperture.position.z).toBe(0);
      expect(aperture.position.y).toBeGreaterThan(PEDESTAL[1].y + PEDESTAL[1].height / 2);
      const position = rays.geometry.getAttribute("position");
      let lowerRadius = 0, upperRadius = 0;
      for (let index = 0; index < position.count; index++) {
        const y = position.getY(index) + rays.position.y;
        expect(y).toBeGreaterThanOrEqual(PROJECTOR.bottom - 1e-6);
        expect(y).toBeLessThanOrEqual(PROJECTOR.top + 1e-6);
        const radius = Math.hypot(position.getX(index), position.getZ(index));
        if (y < (PROJECTOR.top + PROJECTOR.bottom) / 2) lowerRadius = Math.max(lowerRadius, radius);
        else upperRadius = Math.max(upperRadius, radius);
      }
      expect(lowerRadius).toBeLessThan(PROJECTOR.apertureRadius);
      expect(upperRadius).toBeGreaterThan(lowerRadius);
      expect(upperRadius).toBeLessThan(CONTAINMENT.radius);
      expect(PROJECTOR.top).toBeLessThan(PORTRAIT_HEAD_OFFSET_Y - .72 * PORTRAIT_HEAD_SCALE);
      for (const object of [aperture, rays]) {
        expect(object.material.depthTest).toBe(true); expect(object.material.depthWrite).toBe(false);
        expect(object.material.blending).toBe(AdditiveBlending);
      }
    } finally { projector.dispose(); }
  });

  // Keep every visibility probe; allow instrumented full-mesh raycasts on CI CPUs.
  it.each(["male", "female"] as const)("keeps short rays visible between the disk and actual %s neck", (appearance) => {
    const head = decodeHumanHead(Uint8Array.from(readFileSync("public/ai/human-head/head-v1.bin")).buffer, appearance);
    const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(head.positions, 3));
    geometry.setIndex(new BufferAttribute(head.triangles, 1));
    const material = new MeshBasicMaterial(), mesh = new Mesh(geometry, material), root = new Group();
    const camera = new Vector3(...LANDSCAPE_POSITION), point = new Vector3(), direction = new Vector3(), ray = new Raycaster();
    root.position.set(...WORLD_SCULPTURE_POSITION); root.scale.setScalar(WORLD_SCULPTURE_SCALE); root.rotation.y = Math.atan2(camera.x, camera.z);
    mesh.position.y = PORTRAIT_HEAD_OFFSET_Y; mesh.scale.setScalar(PORTRAIT_HEAD_SCALE); mesh.rotation.set(.02, -.18, 0, "YXZ"); root.add(mesh); root.updateMatrixWorld(true);
    const fade = (index: number) => MathUtils.smoothstep(head.positions[index * 3 + 1], -.89, -.72);
    try {
      for (const height of [.1, .35, .65]) {
        let visible = 0;
        for (let index = 0; index < 72; index++) {
          const angle = index * Math.PI / 36, radius = (PROJECTOR.lowerRadius + (PROJECTOR.upperRadius - PROJECTOR.lowerRadius) * height) * PLATFORM_HORIZONTAL_SCALE;
          point.set(Math.sin(angle) * radius, PROJECTOR.bottom + (PROJECTOR.top - PROJECTOR.bottom) * height, Math.cos(angle) * radius).applyMatrix4(root.matrixWorld);
          direction.subVectors(point, camera); const distance = direction.length(); ray.set(camera, direction.normalize());
          // Match interpolated vertex fade: fully invisible neck fragments do
          // not occlude rays, while the visible core still must write depth.
          const occluded = ray.intersectObject(mesh, false).some((hit) => {
            const face = hit.face!, bary = hit.barycoord!;
            const alpha = fade(face.a) * bary.x + fade(face.b) * bary.y + fade(face.c) * bary.z;
            return hit.distance < distance - .001 && alpha >= .005;
          });
          if (!occluded) visible++;
        }
        expect(visible, `${appearance} rays at ${height} fan height`).toBeGreaterThanOrEqual(6);
      }
    } finally { geometry.dispose(); material.dispose(); }
  }, 30_000);

  it("keeps its physical anchor unchanged through animation and retires every resource once", () => {
    const projector = createHologramProjector(), resources = new Set<BufferGeometry | Material>(), disposed: number[] = [];
    projector.group.traverse((object) => {
      if (object instanceof Mesh) { resources.add(object.geometry); resources.add(object.material); }
    });
    resources.forEach((resource) => resource.addEventListener("dispose", () => disposed.push(1)));
    projector.group.updateMatrixWorld(true);
    const matrices = projector.group.children.map((object) => object.matrixWorld.clone());
    projector.update(12, .8, 4); projector.group.updateMatrixWorld(true);
    projector.group.children.forEach((object, index) => expect(object.matrixWorld.equals(matrices[index])).toBe(true));
    const surface = (projector.group.children[0] as Mesh<BufferGeometry, ShaderMaterial>).material;
    expect(surface.uniforms.energy.value).toBe(1);
    projector.update(Infinity, Number.NaN, Infinity);
    expect(projector.group.visible).toBe(false); expect(surface.uniforms.time.value).toBe(0);
    projector.dispose(); projector.dispose(); projector.update(2, 1, 1);
    expect(disposed).toHaveLength(resources.size); expect(projector.group.children).toHaveLength(0);
  });
});
