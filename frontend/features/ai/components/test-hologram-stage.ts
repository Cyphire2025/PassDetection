import { BufferAttribute, BufferGeometry, DoubleSide, Group, LineLoop, LineSegments, Mesh, PlaneGeometry, ShaderMaterial } from "three";
import { containmentLines } from "./test-hologram-particles";

const LINE_VERTEX = `
varying vec3 vPosition;
void main() { vPosition = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
const LINE_FRAGMENT = `
uniform float time, dark, opacity, strength, patterned;
varying vec3 vPosition;
void main() {
  float weave = .12 + .88 * smoothstep(.55, .98, sin(vPosition.y * 27.0 + atan(vPosition.z, vPosition.x) * 4.0 - time * .65));
  float pattern = mix(1.0, weave, patterned);
  float radiance = mix(.10, 1.15 + strength * .45, dark);
  gl_FragColor = vec4(vec3(radiance), strength * pattern * opacity);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;
const GLOW_VERTEX = `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
const GLOW_FRAGMENT = `
uniform float dark, opacity, strength;
varying vec2 vUv;
void main() {
  float radius = length((vUv - .5) * 2.0);
  float glow = exp(-radius * radius * 5.5) * (1.0 - smoothstep(.65, 1.0, radius));
  gl_FragColor = vec4(vec3(mix(.14, .8, dark)), glow * strength * opacity);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

function stageMaterial(patterned: number, glow = false) {
  return new ShaderMaterial({ name: glow ? "Hologram atmosphere" : "Hologram line light",
    uniforms: { time: { value: 0 }, dark: { value: 1 }, opacity: { value: 1 }, strength: { value: 0 }, patterned: { value: patterned } },
    vertexShader: glow ? GLOW_VERTEX : LINE_VERTEX, fragmentShader: glow ? GLOW_FRAGMENT : LINE_FRAGMENT,
    transparent: true, depthTest: true, depthWrite: false, side: DoubleSide, toneMapped: true });
}

function circle(radius: number, segments = 160) {
  const points = new Float32Array(segments * 3);
  for (let index = 0; index < segments; index++) {
    const angle = index / segments * Math.PI * 2;
    points[index * 3] = Math.cos(angle) * radius;
    points[index * 3 + 2] = Math.sin(angle) * radius;
  }
  return new BufferGeometry().setAttribute("position", new BufferAttribute(points, 3));
}

/** Original procedural enclosure and optical base; no external artwork or textures. */
export function createHologramStage() {
  const group = new Group(); group.name = "Hologram stage";
  const cageMaterial = stageMaterial(1);
  const cageGeometry = new BufferGeometry().setAttribute("position", new BufferAttribute(containmentLines(), 3));
  const cage = new LineSegments(cageGeometry, cageMaterial); cage.name = "Interaction enclosure";
  cage.renderOrder = 4; cage.visible = false; group.add(cage);

  const ringMaterials = [stageMaterial(0), stageMaterial(0), stageMaterial(1)];
  const ringGeometries = [.63, .84, 1.01].map((radius) => circle(radius));
  const rings = ringGeometries.map((geometry, index) => {
    const ring = new LineLoop(geometry, ringMaterials[index]);
    ring.position.y = -1.09 - index * .025; ring.position.z = -.05;
    ring.renderOrder = -1; ring.name = `Optical base ${index + 1}`; group.add(ring); return ring;
  });
  const baseMaterial = stageMaterial(0, true), atmosphereMaterial = stageMaterial(0, true);
  const baseGeometry = new PlaneGeometry(2.5, 2.5), atmosphereGeometry = new PlaneGeometry(2.7, 3.2);
  const base = new Mesh(baseGeometry, baseMaterial); base.rotation.x = -Math.PI / 2;
  base.position.set(0, -1.13, -.05); base.renderOrder = -2; group.add(base);
  const atmosphere = new Mesh(atmosphereGeometry, atmosphereMaterial);
  atmosphere.position.set(0, -.02, -.94); atmosphere.renderOrder = -3; group.add(atmosphere);
  const materials = [cageMaterial, ...ringMaterials, baseMaterial, atmosphereMaterial];
  const geometries = [cageGeometry, ...ringGeometries, baseGeometry, atmosphereGeometry];
  let disposed = false;
  return {
    group,
    update(time: number, barrier: number, dark: boolean, opacity: number) {
      if (disposed) return;
      const interaction = Math.max(0, Math.min(1, barrier));
      const alpha = Math.max(0, Math.min(1, opacity));
      group.visible = alpha > .002;
      for (const material of materials) {
        material.uniforms.time.value = time; material.uniforms.dark.value = Number(dark); material.uniforms.opacity.value = alpha;
      }
      cage.visible = interaction > .005;
      cage.rotation.set(Math.sin(time * .12) * .025, time * .045, Math.sin(time * .09) * .018);
      cageMaterial.uniforms.strength.value = interaction * .055;
      for (let index = 0; index < rings.length; index++) {
        rings[index].rotation.y = time * (.025 + index * .008);
        ringMaterials[index].uniforms.strength.value = (dark ? .13 : .10) * (1 - index * .2) + interaction * .08;
      }
      baseMaterial.uniforms.strength.value = (dark ? .07 : .035) + interaction * .035;
      atmosphereMaterial.uniforms.strength.value = dark ? .038 : .018;
    },
    dispose() {
      if (disposed) return;
      disposed = true; group.removeFromParent(); group.clear();
      for (const geometry of geometries) geometry.dispose();
      for (const material of materials) material.dispose();
    },
  };
}
