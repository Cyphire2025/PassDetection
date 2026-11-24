import { AdditiveBlending, CircleGeometry, CylinderGeometry, DoubleSide, Group, Mesh, ShaderMaterial } from "three";

export const PROJECTOR = { apertureRadius: .32, bottom: -1.09, top: -.89, lowerRadius: .20, upperRadius: .34 } as const;

const VERTEX = `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
const APERTURE = `
uniform float opacity, time, energy;
varying vec2 vUv;
void main() {
  float radius = length(vUv - .5) * 2.0;
  float ring = exp(-pow((radius - .65) / .055, 2.0));
  float core = exp(-radius * radius * 35.0) * .45;
  float halo = exp(-pow((radius - .65) / .21, 2.0)) * .15;
  float breath = .93 + .07 * sin(time * 1.2) + energy * .14;
  float alpha = (ring * .65 + core + halo) * breath * opacity;
  if (alpha < .001) discard;
  gl_FragColor = vec4(vec3(.74, .88, 1.1), alpha);
}
`;
const RAYS = `
uniform float opacity, time, energy;
varying vec2 vUv;
void main() {
  float height = vUv.y;
  float angle = vUv.x * 6.2831853;
  float strands = pow(max(0.0, sin(angle * 9.0 + sin(angle * 3.0) * .8 + time * .035)), 12.0);
  strands += pow(max(0.0, sin(angle * 17.0 - time * .025)), 24.0) * .30;
  float envelope = smoothstep(0.0, .07, height) * pow(1.0 - height, 1.8);
  float alpha = (.018 + strands * .115) * envelope * opacity * (1.0 + energy * .35);
  if (alpha < .001) discard;
  gl_FragColor = vec4(vec3(.72, .86, 1.05), alpha);
}
`;
const unit = (value: number) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;

/** Soft light stays centered on the stone; it never follows a rotating head. */
export function createHologramProjector() {
  const group = new Group(); group.name = "Centered hologram projector";
  const uniforms = { opacity: { value: 0 }, time: { value: 0 }, energy: { value: 0 } };
  const material = (name: string, fragmentShader: string) => new ShaderMaterial({ name, uniforms, vertexShader: VERTEX, fragmentShader,
    transparent: true, depthTest: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false, side: DoubleSide });
  const apertureGeometry = new CircleGeometry(PROJECTOR.apertureRadius, 64);
  const rayGeometry = new CylinderGeometry(PROJECTOR.upperRadius, PROJECTOR.lowerRadius, PROJECTOR.top - PROJECTOR.bottom, 64, 1, true);
  const apertureMaterial = material("Projector aperture", APERTURE), rayMaterial = material("Projector upward rays", RAYS);
  const aperture = new Mesh(apertureGeometry, apertureMaterial); aperture.name = "Projector center light";
  aperture.rotation.x = -Math.PI / 2; aperture.position.y = -1.095; aperture.renderOrder = 2;
  const rays = new Mesh(rayGeometry, rayMaterial); rays.name = "Projector fanned light rays";
  rays.position.y = (PROJECTOR.top + PROJECTOR.bottom) / 2; rays.renderOrder = 2;
  group.add(aperture, rays);
  let disposed = false;
  return {
    group,
    update(time: number, opacity: number, energy: number) {
      if (disposed) return;
      uniforms.time.value = Number.isFinite(time) ? time : 0;
      uniforms.opacity.value = unit(opacity); uniforms.energy.value = unit(energy);
      group.visible = uniforms.opacity.value > .002;
    },
    dispose() {
      if (disposed) return;
      disposed = true; group.removeFromParent(); group.clear();
      apertureGeometry.dispose(); rayGeometry.dispose(); apertureMaterial.dispose(); rayMaterial.dispose();
    },
  };
}
