import { Mesh, MeshBasicMaterial, PlaneGeometry, Raycaster, ShaderMaterial, Vector3, type BufferGeometry, type Texture } from "three";
import { LANDSCAPE_GROUND_FOOTPRINT } from "./test-landscape-layout";
import { createSnowCollar } from "./test-hologram-snow-collar";
import type { HologramSpillUniforms } from "./test-hologram-spill";

/** The source igloo ground is untransformed around the world origin. */
export function groundContactGeometry(ground: BufferGeometry) {
  const width = LANDSCAPE_GROUND_FOOTPRINT * 1.22;
  const geometry = new PlaneGeometry(width, width, 32, 32).rotateX(-Math.PI / 2);
  const temporary = new MeshBasicMaterial(), terrain = new Mesh(ground, temporary);
  const ray = new Raycaster(new Vector3(), new Vector3(0, -1, 0)), position = geometry.getAttribute("position");
  try {
    for (let index = 0; index < position.count; index++) {
      ray.ray.origin.set(position.getX(index), 20, position.getZ(index));
      const hit = ray.intersectObject(terrain, false)[0];
      if (!hit) throw new Error("Pedestal contact lies outside the original ground");
      position.setY(index, hit.point.y + .006);
    }
    position.needsUpdate = true; geometry.computeVertexNormals(); geometry.computeBoundingSphere(); return geometry;
  } catch (error) { geometry.dispose(); throw error; }
  finally { temporary.dispose(); }
}

/** A small draped shadow remains in world space when the portrait turns. */
export function createPedestalGroundContact(ground: BufferGeometry, snow?: Texture, wind?: Texture, spill?: HologramSpillUniforms) {
  const geometry = groundContactGeometry(ground), opacity = { value: 0 };
  const material = new ShaderMaterial({
    name: "Terrain-conforming pedestal contact", uniforms: { opacity }, transparent: true, depthWrite: false, toneMapped: false,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1,
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "uniform float opacity; varying vec2 vUv; void main() { float radius = length(vUv - .5) * 2.0; float alpha = (1.0 - smoothstep(.72, 1.0, radius)) * opacity * .14; if (alpha < .001) discard; gl_FragColor = vec4(vec3(.09), alpha); }",
  });
  const mesh = new Mesh(geometry, material); mesh.name = "Pedestal grounded contact"; mesh.renderOrder = 3;
  let collar: ReturnType<typeof createSnowCollar>;
  try { collar = createSnowCollar(ground, snow, wind, spill); }
  catch (error) { geometry.dispose(); material.dispose(); throw error; }
  mesh.add(collar.mesh);
  let disposed = false;
  return {
    mesh,
    update(value: number, time = 0) {
      if (disposed) return;
      opacity.value = Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;
      collar.update(opacity.value, time);
    },
    dispose() { if (disposed) return; disposed = true; collar.dispose(); mesh.removeFromParent(); geometry.dispose(); material.dispose(); },
  };
}
