import { Box3, BufferGeometry, LineSegments, Material, Mesh, MeshBasicMaterial, Points, Raycaster, ShaderMaterial, Texture, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { CONTAINMENT, containmentCylinderGeometry, createPortraitPlatform, PEDESTAL, PEDESTAL_BAND, pedestalDiscGeometry } from "./test-hologram-platform";
import { LANDSCAPE_GROUND_FOOTPRINT, PLATFORM_HORIZONTAL_SCALE, PORTRAIT_HEAD_SCALE, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

describe("anchored portrait pedestal", () => {
  it("renders only cylinder walls with a transparent roof and floor", () => {
    const geometry = containmentCylinderGeometry(true), material = new MeshBasicMaterial();
    try {
      const mesh = new Mesh(geometry, material), ray = new Raycaster();
      ray.set(new Vector3(.2, 2, .1), new Vector3(0, -1, 0));
      expect(ray.intersectObject(mesh, false)).toHaveLength(0);
      ray.set(new Vector3(2, 0, 0), new Vector3(-1, 0, 0));
      expect(ray.intersectObject(mesh, false)[0].distance).toBeCloseTo(2 - CONTAINMENT.radius, 2);
      const points = geometry.getAttribute("position");
      for (let i = 0; i < points.count; i++) expect(Math.hypot(points.getX(i), points.getZ(i))).toBeCloseTo(CONTAINMENT.radius, 6);
    } finally { geometry.dispose(); material.dispose(); }
  });
  it("encloses the portrait with a closed outward-facing cylinder, including both caps", () => {
    const geometry = containmentCylinderGeometry(), material = new MeshBasicMaterial();
    try {
      const mesh = new Mesh(geometry, material), positions = geometry.getAttribute("position"), indices = geometry.getIndex()!;
      const incidence = new Map<string, number>();
      for (let index = 0; index < indices.count; index += 3) for (let edge = 0; edge < 3; edge++) {
        const a = indices.getX(index + edge), b = indices.getX(index + (edge + 1) % 3), key = `${Math.min(a, b)}:${Math.max(a, b)}`;
        incidence.set(key, (incidence.get(key) ?? 0) + 1);
      }
      expect([...incidence.values()].every((count) => count === 2)).toBe(true);
      expect(positions.count).toBeLessThan(6000);
      const ray = new Raycaster();
      for (let degrees = 0; degrees < 360; degrees += 15) {
        const angle = degrees * Math.PI / 180;
        ray.set(new Vector3(Math.sin(angle) * 2, 0, Math.cos(angle) * 2), new Vector3(-Math.sin(angle), 0, -Math.cos(angle)));
        const hit = ray.intersectObject(mesh, false)[0];
        expect(hit, `exterior ray at ${degrees} degrees`).toBeDefined();
        expect(hit.distance).toBeCloseTo(2 - CONTAINMENT.radius, 2);
      }
      for (const [origin, direction, expectedY] of [[2, -1, CONTAINMENT.top], [-2, 1, CONTAINMENT.bottom]]) {
        ray.set(new Vector3(.2, origin, .1), new Vector3(0, direction, 0));
        expect(ray.intersectObject(mesh, false)[0]?.point.y).toBeCloseTo(expectedY);
      }
      geometry.computeBoundingBox();
      expect(geometry.boundingBox!.max.y).toBeGreaterThan(1.05);
      expect(CONTAINMENT.radius * PLATFORM_HORIZONTAL_SCALE).toBeGreaterThan(.67 * PORTRAIT_HEAD_SCALE + .20);
      expect(PEDESTAL[1].y + PEDESTAL[1].height / 2).toBeCloseTo(CONTAINMENT.bottom);
    } finally { geometry.dispose(); material.dispose(); }
  });

  it("uses reproducible varied short cells without long radial cap spokes", () => {
    const geometry = containmentCylinderGeometry(), duplicate = containmentCylinderGeometry();
    try {
      const positions = geometry.getAttribute("position"), indices = geometry.getIndex()!;
      expect(positions.array).toEqual(duplicate.getAttribute("position").array);
      expect(indices.array).toEqual(duplicate.getIndex()!.array);
      const a = new Vector3(), b = new Vector3(), c = new Vector3(), ab = new Vector3(), ac = new Vector3();
      const sideLengths: number[] = [];
      for (let index = 0; index < indices.count; index += 3) {
        a.fromBufferAttribute(positions, indices.getX(index)); b.fromBufferAttribute(positions, indices.getX(index + 1)); c.fromBufferAttribute(positions, indices.getX(index + 2));
        expect(ab.subVectors(b, a).cross(ac.subVectors(c, a)).lengthSq()).toBeGreaterThan(1e-10);
        for (const [start, end] of [[a, b], [b, c], [c, a]]) {
          const length = start.distanceTo(end);
          expect(length).toBeLessThan(CONTAINMENT.radius * .20);
          if (Math.abs(start.y) < .8 && Math.abs(end.y) < .8) sideLengths.push(length);
        }
      }
      sideLengths.sort((left, right) => left - right);
      expect(sideLengths[Math.floor(sideLengths.length * .9)] / sideLengths[Math.floor(sideLengths.length * .1)]).toBeGreaterThan(1.5);
      for (let index = 0; index < positions.count; index++) {
        expect(Math.hypot(positions.getX(index), positions.getZ(index))).toBeLessThanOrEqual(CONTAINMENT.radius + 1e-6);
        expect(positions.getY(index)).toBeGreaterThanOrEqual(CONTAINMENT.bottom - 1e-6);
        expect(positions.getY(index)).toBeLessThanOrEqual(CONTAINMENT.top + 1e-6);
      }
    } finally { geometry.dispose(); duplicate.dispose(); }
  });

  it("uses low bevelled solid discs and borrows the snow texture without taking ownership", () => {
    const geometry = pedestalDiscGeometry(), material = new MeshBasicMaterial(), platform = createPortraitPlatform(), texture = new Texture();
    let textureDisposals = 0; texture.addEventListener("dispose", () => textureDisposals++);
    try {
      const disc = new Mesh(geometry, material), ray = new Raycaster();
      for (const radius of [0, .5, .97, .99]) {
        ray.set(new Vector3(radius, 2, 0), new Vector3(0, -1, 0));
        expect(ray.intersectObject(disc, false).length).toBeGreaterThan(0);
      }
      const totalHeight = PEDESTAL[1].y + PEDESTAL[1].height / 2 - (PEDESTAL[0].y - PEDESTAL[0].height / 2);
      expect(totalHeight).toBeGreaterThanOrEqual(.12); expect(totalHeight).toBeLessThanOrEqual(.16);
      // The full-height luminous wall fills the recess and stays inside its cap.
      expect(PEDESTAL_BAND.y - PEDESTAL_BAND.height / 2).toBeCloseTo(PEDESTAL[0].y + PEDESTAL[0].height / 2);
      expect(PEDESTAL_BAND.y + PEDESTAL_BAND.height / 2).toBeCloseTo(PEDESTAL[1].y - PEDESTAL[1].height / 2);
      expect(PEDESTAL_BAND.radius).toBeLessThan(PEDESTAL[1].radius);
      const base = platform.group.getObjectByName("Stone pedestal tier 1") as Mesh;
      platform.group.updateMatrixWorld(true);
      const bounds = new Box3().setFromObject(base);
      const width = (bounds.max.x - bounds.min.x) * WORLD_SCULPTURE_SCALE;
      expect(width).toBeLessThanOrEqual(LANDSCAPE_GROUND_FOOTPRINT + .00001);
      expect(width).toBeGreaterThan(LANDSCAPE_GROUND_FOOTPRINT - .04);
      expect(platform.group.scale.y).toBe(1);
      const surface = (platform.group.getObjectByName("Stone pedestal tier 1") as Mesh<BufferGeometry, ShaderMaterial>).material;
      platform.setSnowTexture(texture); expect(surface.uniforms.tSnow.value).toBe(texture);
      platform.dispose(); expect(textureDisposals).toBe(0);
      const replacement = new Texture(); platform.setSnowTexture(replacement);
      expect(surface.uniforms.tSnow.value).toBe(texture); replacement.dispose();
    } finally { geometry.dispose(); material.dispose(); platform.dispose(); texture.dispose(); }
  });

  it("reacts to speech or interaction without moving the pedestal or enclosure", () => {
    const platform = createPortraitPlatform();
    try {
      const cage = platform.group.getObjectByName("Cylindrical interaction enclosure") as LineSegments<BufferGeometry, ShaderMaterial>;
      platform.group.updateMatrixWorld(true);
      const matrices = platform.group.children.map((child) => child.matrixWorld.clone());
      platform.update(0, 0, 1); expect(cage.visible).toBe(true); expect(platform.group.visible).toBe(true);
      const idle = cage.material.uniforms.strength.value;
      expect(idle).toBeGreaterThan(0); expect(idle).toBeLessThan(.2);
      platform.update(13, 0, 1, .7); expect(cage.visible).toBe(true); expect(cage.material.uniforms.strength.value).toBeGreaterThan(idle);
      platform.update(18, 1, 1, 0); expect(cage.visible).toBe(true);
      platform.group.updateMatrixWorld(true);
      platform.group.children.forEach((child, index) => expect(child.matrixWorld.equals(matrices[index])).toBe(true));
      platform.update(Infinity, Number.NaN, Infinity, Infinity);
      expect(platform.group.visible).toBe(false); expect(cage.visible).toBe(false);
      expect(cage.material.uniforms.time.value).toBe(0); expect(cage.material.uniforms.strength.value).toBe(0);
    } finally { platform.dispose(); }
  });

  it("retires shared geometries and materials exactly once and makes late updates inert", () => {
    const platform = createPortraitPlatform(), resources = new Set<BufferGeometry | Material>(), disposed = new Map<BufferGeometry | Material, number>();
    platform.group.traverse((object) => {
      if (object instanceof Mesh || object instanceof LineSegments || object instanceof Points) {
        resources.add(object.geometry);
        if (Array.isArray(object.material)) object.material.forEach((surface) => resources.add(surface));
        else resources.add(object.material);
      }
    });
    resources.forEach((resource) => resource.addEventListener("dispose", () => disposed.set(resource, (disposed.get(resource) ?? 0) + 1)));
    expect(resources.size).toBeLessThanOrEqual(14);
    platform.dispose(); platform.dispose(); platform.update(100, 1, 1, 1);
    expect(platform.group.children).toHaveLength(0);
    expect(disposed.size).toBe(resources.size); expect([...disposed.values()].every((count) => count === 1)).toBe(true);
  });
});
