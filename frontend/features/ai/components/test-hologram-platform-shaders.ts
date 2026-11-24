export const PLATFORM_VERTEX = `
varying vec3 vWorld, vNormal, vLocal;
varying float vUp;
varying vec2 vUv;
void main() {
  vUv = uv; vLocal = position;
  vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
  vec3 viewNormal = normalize(normalMatrix * normal);
  vNormal = vec3(dot(viewMatrix[0].xyz, viewNormal), dot(viewMatrix[1].xyz, viewNormal), dot(viewMatrix[2].xyz, viewNormal));
  vUp = vNormal.y;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
const SNOW_COLOR = `
uniform float hasSnow, snowSpan;
uniform sampler2D tSnow;
uniform vec4 snowIsland;
vec3 snowColor(vec2 worldXZ) {
  vec2 uv = mix(snowIsland.xy, snowIsland.zw, clamp(worldXZ / snowSpan + .5, 0.0, 1.0));
  return mix(vec3(.36), texture2D(tSnow, uv).rgb, hasSnow);
}
`;
export const STONE_FRAGMENT = `
uniform float opacity;
${SNOW_COLOR}
varying vec3 vWorld, vNormal, vLocal;
varying float vUp;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float grain(vec2 p) {
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + 1.0), f.x), f.y);
}
float stoneHeight(vec3 p, vec3 weights) {
  vec3 broad = vec3(grain(p.zy * 9.0), grain(p.xz * 9.0), grain(p.xy * 9.0));
  vec3 fine = vec3(grain(p.zy * 34.0), grain(p.xz * 34.0), grain(p.xy * 34.0));
  return dot(broad, weights) * .045 + dot(fine, weights) * .012;
}
void main() {
  if (opacity < .002) discard;
  float cap = smoothstep(.4, .95, vUp);
  vec3 weights = pow(abs(normalize(vNormal)), vec3(4.0));
  weights /= max(dot(weights, vec3(1.0)), .0001);
  // Surface-gradient bump mapping changes the diffuse response, rather than
  // painting noise onto an otherwise perfectly smooth manufactured surface.
  vec3 normal = normalize(vNormal), dx = dFdx(vWorld), dy = dFdy(vWorld);
  vec3 acrossY = cross(dy, normal), acrossX = cross(normal, dx);
  float determinant = dot(dx, acrossY), height = stoneHeight(vWorld, weights);
  vec3 gradient = (acrossY * dFdx(height) + acrossX * dFdy(height)) / max(abs(determinant), .0000001);
  normal = normalize(normal - sign(determinant) * gradient);
  float light = max(0.0, dot(normal, normalize(vec3(-.6, 1.0, 1.2))));
  vec3 snow = snowColor(vec2(vWorld.z, vWorld.y * 2.5) * .30) * weights.x;
  snow += snowColor(vWorld.xz * .30) * weights.y;
  snow += snowColor(vec2(vWorld.x, vWorld.y * 2.5) * .30) * weights.z;
  float variation = clamp((dot(snow, vec3(.2126, .7152, .0722)) - .42) * .24, -.05, .05);
  float weathering = (height / .057 - .5) * .075;
  // Linear colors calibrated through the common LUT and output transform.
  vec3 color = mix(vec3(.36649, .41951, .52818), vec3(.47439, .52616, .61440), cap);
  float bevel = smoothstep(.12, .45, vUp) * (1.0 - smoothstep(.75, .98, vUp));
  float radius = length(vLocal.xz);
  float groove = exp(-pow((radius - .81) / .009, 2.0)) * cap * .022;
  float powder = smoothstep(.91, .995, radius) * cap * (.015 + grain(vWorld.xz * 37.0) * .022);
  gl_FragColor = vec4(color + variation + weathering + (light - .6) * .14 + bevel * .018 + powder - groove, opacity);
}
`;
export const BAND_FRAGMENT = `
uniform float opacity;
varying vec2 vUv;
void main() {
  float roundedEdge = smoothstep(0.0, .16, vUv.y) * (1.0 - smoothstep(.84, 1.0, vUv.y));
  // A recessed luminous wall with softened edges, not a thin torus outline.
  gl_FragColor = vec4(vec3(.76, .889, 1.02) * (.89 + roundedEdge * .11), opacity * (.72 + roundedEdge * .28));
}
`;
export const CYLINDER_VERTEX = `
varying vec3 vCylinder;
void main() {
  vCylinder = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_PointSize = 2.0;
}
`;
export const CYLINDER_FRAGMENT = `
uniform float time, strength;
uniform vec2 heightBounds;
varying vec3 vCylinder;
void main() {
  if (strength < .002 || length(vCylinder.xz) < .002) discard;
  // Positive phase follows positive Y rotation: counterclockwise from above.
  float angle = atan(-vCylinder.z, vCylinder.x), phase = time * .48;
  float angularDistance = atan(sin(angle - phase), cos(angle - phase));
  float height = (vCylinder.y - heightBounds.x) / (heightBounds.y - heightBounds.x);
  float heightCenter = .5 + .48 * sin(phase * .65);
  float distance = length(vec2(angularDistance / .68, (height - heightCenter) / .27));
  if (distance >= 1.0) discard;
  float envelope = 1.0 - smoothstep(.62, 1.0, distance);
  float ripple = exp(-pow((distance - .46) / .18, 2.0));
  #ifdef CYLINDER_NODES
    float radius = length(gl_PointCoord - .5) * 2.0;
    if (radius > 1.0) discard;
    float coverage = 1.0 - smoothstep(.25, 1.0, radius);
  #else
    float coverage = 1.0;
  #endif
  float alpha = strength * envelope * (.32 + ripple * .68) * coverage;
  if (alpha < .002) discard;
  gl_FragColor = vec4(vec3(.74, .84, .98) + ripple * .08, alpha);
}
`;
