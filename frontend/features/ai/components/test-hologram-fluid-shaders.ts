// Original screen-space, incompressible flow passes. Velocity is in UV/second.
const COMMON = `
uniform sampler2D uVelocity;
uniform sampler2D uPressure;
uniform sampler2D uDivergence;
uniform vec2 uTexel;
varying vec2 vUv;
vec2 boundedVelocity(vec2 value) {
  return value * min(1.0, 2.0 / max(length(value), 0.00001));
}
`;

export const FLUID_VERTEX = `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

export const FLUID_ADVECT = `${COMMON}
uniform float uDt;
uniform float uAspect;
uniform vec2 uPointer;
uniform vec2 uPrevious;
uniform vec2 uImpulse;
void main() {
  vec2 velocity = texture2D(uVelocity, vUv).xy;
  vec2 traced = clamp(vUv - velocity * uDt, uTexel * 0.5, 1.0 - uTexel * 0.5);
  velocity = texture2D(uVelocity, traced).xy * exp(-1.65 * uDt);
  vec2 scale = vec2(uAspect, 1.0);
  vec2 segment = (uPointer - uPrevious) * scale;
  vec2 relative = (vUv - uPrevious) * scale;
  float along = clamp(dot(relative, segment) / max(dot(segment, segment), 0.000001), 0.0, 1.0);
  vec2 distanceToPath = relative - along * segment;
  float weight = exp(-dot(distanceToPath, distanceToPath) / 0.0036);
  gl_FragColor = vec4(boundedVelocity(velocity + uImpulse * weight), 0.0, 1.0);
}
`;

export const FLUID_DIVERGENCE = `${COMMON}
void main() {
  float left = texture2D(uVelocity, vUv - vec2(uTexel.x, 0.0)).x;
  float right = texture2D(uVelocity, vUv + vec2(uTexel.x, 0.0)).x;
  float down = texture2D(uVelocity, vUv - vec2(0.0, uTexel.y)).y;
  float up = texture2D(uVelocity, vUv + vec2(0.0, uTexel.y)).y;
  vec2 center = texture2D(uVelocity, vUv).xy;
  if (vUv.x < uTexel.x) left = -center.x;
  if (vUv.x > 1.0 - uTexel.x) right = -center.x;
  if (vUv.y < uTexel.y) down = -center.y;
  if (vUv.y > 1.0 - uTexel.y) up = -center.y;
  gl_FragColor = vec4(0.5 * (right - left + up - down) / uTexel.x, 0.0, 0.0, 1.0);
}
`;

export const FLUID_PRESSURE = `${COMMON}
void main() {
  float left = texture2D(uPressure, vUv - vec2(uTexel.x, 0.0)).x;
  float right = texture2D(uPressure, vUv + vec2(uTexel.x, 0.0)).x;
  float down = texture2D(uPressure, vUv - vec2(0.0, uTexel.y)).x;
  float up = texture2D(uPressure, vUv + vec2(0.0, uTexel.y)).x;
  float divergence = texture2D(uDivergence, vUv).x;
  gl_FragColor = vec4((left + right + down + up - uTexel.x * uTexel.x * divergence) * 0.25, 0.0, 0.0, 1.0);
}
`;

export const FLUID_PROJECT = `${COMMON}
void main() {
  float left = texture2D(uPressure, vUv - vec2(uTexel.x, 0.0)).x;
  float right = texture2D(uPressure, vUv + vec2(uTexel.x, 0.0)).x;
  float down = texture2D(uPressure, vUv - vec2(0.0, uTexel.y)).x;
  float up = texture2D(uPressure, vUv + vec2(0.0, uTexel.y)).x;
  vec2 velocity = texture2D(uVelocity, vUv).xy - vec2(right - left, up - down) * (0.5 / uTexel.x);
  if (vUv.x < uTexel.x || vUv.x > 1.0 - uTexel.x) velocity.x = 0.0;
  if (vUv.y < uTexel.y || vUv.y > 1.0 - uTexel.y) velocity.y = 0.0;
  gl_FragColor = vec4(boundedVelocity(velocity), 0.0, 1.0);
}
`;
