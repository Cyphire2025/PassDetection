import { Vector3 } from "three";
import { PEDESTAL_BAND } from "./test-hologram-platform";
import { PLATFORM_HORIZONTAL_SCALE, PORTRAIT_HEAD_OFFSET_Y, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

const unit = (value: number) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;

/** Shared, allocation-free light state for the ground and its powder collar. */
export function createHologramSpill() {
  const base = new Vector3(...WORLD_SCULPTURE_POSITION);
  base.y += PEDESTAL_BAND.y * WORLD_SCULPTURE_SCALE;
  const face = new Vector3(...WORLD_SCULPTURE_POSITION);
  face.y += PORTRAIT_HEAD_OFFSET_Y * WORLD_SCULPTURE_SCALE;
  const uniforms = {
    hologramBase: { value: base }, hologramFace: { value: face },
    hologramRingRadius: { value: PEDESTAL_BAND.radius * WORLD_SCULPTURE_SCALE * PLATFORM_HORIZONTAL_SCALE },
    hologramGlow: { value: 0 },
  };
  return { uniforms, update(opacity: number, speech: number) { uniforms.hologramGlow.value = unit(opacity) * (1 + .16 * unit(speech)); } };
}

export type HologramSpillUniforms = ReturnType<typeof createHologramSpill>["uniforms"];

/** Bounded diffuse area-light approximation; it adds no pass or shadow map. */
export const HOLOGRAM_SPILL = `
uniform vec3 hologramBase, hologramFace;
uniform float hologramRingRadius, hologramGlow;
float spillDiffuse(vec3 delta, vec3 normal, float reach, float spread) {
  float distanceSquared = dot(delta, delta);
  if (distanceSquared >= reach * reach) return 0.0;
  float cutoff = max(1.0 - distanceSquared / (reach * reach), 0.0);
  float facing = max(dot(normal, delta * inversesqrt(max(distanceSquared, .0001))), 0.0);
  return facing * cutoff * cutoff / (1.0 + distanceSquared / spread);
}
vec3 hologramSpill(vec3 color, vec3 world, vec3 normal) {
  if (hologramGlow <= 0.0) return color;
  vec3 fromFace = world - hologramFace;
  if (dot(fromFace, fromFace) >= 256.0) return color;
  vec2 radial = world.xz - hologramBase.xz;
  radial *= inversesqrt(max(dot(radial, radial), .0001));
  vec3 ring = hologramBase + vec3(radial.x, 0.0, radial.y) * hologramRingRadius;
  vec3 n = normalize(normal);
  float light = .045 * spillDiffuse(ring - world, n, 7.0, 4.0);
  light += .055 * spillDiffuse(-fromFace, n, 16.0, 25.0);
  // Modulate by the existing snow color, preserving its authored fine relief.
  return color + vec3(.84, .95, 1.08) * light * hologramGlow * (.35 + .65 * clamp(color, 0.0, 1.0));
}
`;
