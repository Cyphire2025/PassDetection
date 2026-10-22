import { readFileSync } from "node:fs";
import { BufferGeometry, Mesh, MeshBasicMaterial, Raycaster, ShaderMaterial, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { createPedestalGroundContact, groundContactGeometry } from "./test-hologram-ground-contact";
import { decodeLandscapeGeometry } from "./test-landscape-assets";
import { PEDESTAL, pedestalDiscGeometry } from "./test-hologram-platform";
import { STONE_EDGE_CHIP } from "./test-hologram-stone-geometry";
import { LANDSCAPE_GROUND_ANCHOR, PLATFORM_HORIZONTAL_SCALE, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

const loadGround = () => decodeLandscapeGeometry(Uint8Array.from(readFileSync("public/ai/test-landscape/ground.bin")).buffer);

describe("physical pedestal contact", () => {
  it("drapes the contact shadow onto original terrain instead of leaving a floating flat plane", () => {
    const ground = loadGround(), contact = groundContactGeometry(ground), material = new MeshBasicMaterial();
    try {
      const terrain = new Mesh(ground, material), ray = new Raycaster(new Vector3(), new Vector3(0, -1, 0));
      const position = contact.getAttribute("position"); let min = Infinity, max = -Infinity;
      for (let index = 0; index < position.count; index += 7) {
        ray.ray.origin.set(position.getX(index), 20, position.getZ(index));
        const height = ray.intersectObject(terrain, false)[0].point.y;
        expect(position.getY(index) - height).toBeCloseTo(.006, 5);
        min = Math.min(min, position.getY(index)); max = Math.max(max, position.getY(index));
      }
      expect(max - min).toBeGreaterThan(.1);
    } finally { ground.dispose(); contact.dispose(); material.dispose(); }
  });

  it("leaves no exposed air gap below the base while the entire upper cap clears the snow", () => {
    const ground = loadGround(), base = pedestalDiscGeometry(true), material = new MeshBasicMaterial();
    try {
      const terrain = new Mesh(ground, material), disc = new Mesh(base, material), tier = PEDESTAL[0];
      const horizontalScale = WORLD_SCULPTURE_SCALE * PLATFORM_HORIZONTAL_SCALE;
      disc.position.set(0, WORLD_SCULPTURE_POSITION[1] + tier.y * WORLD_SCULPTURE_SCALE, 0);
      disc.scale.set(tier.radius * horizontalScale, tier.height * WORLD_SCULPTURE_SCALE, tier.radius * horizontalScale); disc.updateMatrixWorld();
      const ray = new Raycaster(new Vector3(), new Vector3()), radius = tier.radius * horizontalScale;
      const baseTop = WORLD_SCULPTURE_POSITION[1] + (tier.y + tier.height / 2) * WORLD_SCULPTURE_SCALE;
      const upper = PEDESTAL[1], upperRadius = upper.radius * horizontalScale;
      const capHeight = WORLD_SCULPTURE_POSITION[1] + (upper.y + upper.height / 2) * WORLD_SCULPTURE_SCALE;
      expect(WORLD_SCULPTURE_POSITION[1] + (tier.y - tier.height / 2) * WORLD_SCULPTURE_SCALE).toBeCloseTo(LANDSCAPE_GROUND_ANCHOR[1] - .02);
      for (let index = 0; index < 48; index++) {
        const angle = index * Math.PI / 24, x = Math.sin(angle), z = Math.cos(angle);
        ray.set(new Vector3(x * radius, 20, z * radius), new Vector3(0, -1, 0));
        const height = ray.intersectObject(terrain, false)[0].point.y;
        // A nearby snow ridge may bury the outer lower ledge. Test its exposed
        // wall, rather than requiring a wall to extend above that buried ledge.
        const wallHeight = Math.min(height - .015, baseTop - tier.height * WORLD_SCULPTURE_SCALE * .35);
        ray.set(new Vector3(x * (radius + .5), wallHeight, z * (radius + .5)), new Vector3(-x, 0, -z));
        const hit = ray.intersectObject(disc, false)[0];
        expect(hit, `buried side at ${index * 7.5} degrees`).toBeDefined();
        expect(hit.distance).toBeGreaterThanOrEqual(.499);
        expect(hit.distance).toBeLessThan(.502 + radius * STONE_EDGE_CHIP);
        ray.set(new Vector3(x * upperRadius, 20, z * upperRadius), new Vector3(0, -1, 0));
        expect(ray.intersectObject(terrain, false)[0].point.y, `upper cap clearance at ${index * 7.5} degrees`).toBeLessThan(capHeight);
      }
    } finally { ground.dispose(); base.dispose(); material.dispose(); }
  });

  it("owns only the contact patch and leaves the borrowed ground geometry alive", () => {
    const ground = loadGround(), contact = createPedestalGroundContact(ground);
    let groundDisposals = 0, meshDisposals = 0, materialDisposals = 0;
    ground.addEventListener("dispose", () => groundDisposals++);
    const mesh = contact.mesh as Mesh<BufferGeometry, ShaderMaterial>;
    mesh.geometry.addEventListener("dispose", () => meshDisposals++); mesh.material.addEventListener("dispose", () => materialDisposals++);
    contact.update(.8); expect(mesh.material.uniforms.opacity.value).toBe(.8);
    contact.dispose(); contact.dispose(); contact.update(1);
    expect(groundDisposals).toBe(0); expect(meshDisposals).toBe(1); expect(materialDisposals).toBe(1);
    expect(mesh.material.uniforms.opacity.value).toBe(.8); ground.dispose();
  });
});
