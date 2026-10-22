import { HOLOGRAM_SPILL } from "./test-hologram-spill";

/** Original compact integration shaders, independent of Igloo's application code. */
export const LANDSCAPE_VERTEX = `
varying vec2 vUv;
varying vec3 vWorld, vLocal, vWorldNormal;
varying float vDepth;
void main() {
  vUv = uv; vLocal = position;
  vec4 world = modelMatrix * vec4(position, 1.0);
  vec4 view = viewMatrix * world;
  vWorld = world.xyz; vDepth = -view.z;
  vec3 viewNormal = normalize(normalMatrix * normal);
  vWorldNormal = vec3(dot(viewMatrix[0].xyz, viewNormal), dot(viewMatrix[1].xyz, viewNormal), dot(viewMatrix[2].xyz, viewNormal));
  gl_Position = projectionMatrix * view;
}
`;

const ENVIRONMENT = `
uniform float time;
uniform vec2 resolution;
uniform vec3 colorLow, colorHigh;
varying vec2 vUv;
varying vec3 vWorld, vLocal, vWorldNormal;
varying float vDepth;
vec3 skyColor() {
  vec2 screen = gl_FragCoord.xy / resolution;
  float blend = pow((screen.x + screen.y) * .5, 2.0);
  return mix(colorLow, colorHigh, blend);
}
`;

const SNOW_FIELD = `
uniform vec4 snowIsland;
vec3 sampleSnowField(vec2 worldXZ) {
  // All added relief samples one field, so intersecting copies cannot disagree
  // about baked lighting or wind brightness at the same world-space point.
  // A ~370px island spans 5.6 world units, close to the authored patch density.
  vec2 uv = abs(mod(worldXZ * .18, 2.0) - 1.0);
  uv = mix(snowIsland.xy, snowIsland.zw, uv);
  vec3 snow = texture2D(tMap, uv).rgb;
  float drift = texture2D(tWind, worldXZ * .08 - time * vec2(.08, .10)).r;
  return snow + drift * .055;
}
vec3 snowSurface() {
  vec3 snow = sampleSnowField(vWorld.xz);
  snow *= .90 + .10 * smoothstep(-2.6, .4, vWorld.y);
  return mix(snow, skyColor(), smoothstep(35.0, 150.0, vDepth));
}
`;

export const TERRAIN_FRAGMENT = `
${ENVIRONMENT}
uniform sampler2D tMap, tWind;
uniform float mountain, radiusScale, edgePass, worldSnow;
uniform vec2 edge;
${SNOW_FIELD}
${HOLOGRAM_SPILL}
void main() {
  vec3 color = texture2D(tMap, vUv).rgb;
  if (mountain > .5) {
    float fogHeight = clamp(.5 - vWorld.y / 20.0, 0.0, 1.0);
    float fogDistance = clamp(vDepth / 200.0, 0.0, 1.0) * .75;
    vec3 haze = skyColor() * 1.1 + smoothstep(.5, 1.0, color.r);
    color = mix(color, haze, clamp(fogHeight + fogDistance, 0.0, 1.0));
  } else if (worldSnow > .5) {
    color = snowSurface();
  } else {
    vec2 windSpace = vWorld.xz + vWorld.xy;
    float drift = texture2D(tWind, windSpace * .1 - time * vec2(.25, .30)).r;
    drift *= texture2D(tWind, windSpace * .15 - time * vec2(.18, .225)).r;
    drift *= 1.0 - clamp(vLocal.y * .5 + .75, 0.0, 1.0);
    color = min(vec3(1.0), color + drift * color.r * .95);
  }
  color = hologramSpill(color, vWorld, vWorldNormal);
  float fade = 1.0 - smoothstep(edge.x, edge.y, length(vLocal.xz) * radiusScale);
  if (edgePass < .5) {
    if (fade < .999) discard;
    gl_FragColor = vec4(color, 1.0);
  } else {
    if (fade < .002 || fade >= .999) discard;
    gl_FragColor = vec4(color, fade);
  }
}
`;

export const SKY_FRAGMENT = `${ENVIRONMENT}
uniform sampler2D tWind;
void main() {
  vec2 screen = gl_FragCoord.xy / resolution;
  vec2 uv = screen * vec2(1.25, .8) + vec2(time * .0012, time * .0004);
  float broad = texture2D(tWind, uv * .58 + vec2(.21, .43)).r;
  float detail = texture2D(tWind, uv * 1.4 + vec2(.62, .18)).r;
  float cloud = smoothstep(.28, .79, broad * .78 + detail * .22);
  float light = smoothstep(.08, .95, screen.x);
  float altitude = smoothstep(.32, .85, screen.y);
  vec3 color = mix(skyColor(), vec3(.83, .87, .94), cloud * (.16 + light * .30) * altitude);
  gl_FragColor = vec4(color, 1.0);
}
`;

export const FLOOR_FRAGMENT = `${ENVIRONMENT}
uniform sampler2D tMap, tWind;
${SNOW_FIELD}
${HOLOGRAM_SPILL}
void main() {
  gl_FragColor = vec4(hologramSpill(snowSurface(), vWorld, vWorldNormal), 1.0);
}
`;

export const SMOKE_FRAGMENT = `
${ENVIRONMENT}
uniform sampler2D tWind;
void main() {
  vec2 uv = vUv * vec2(2.0, 1.0);
  float phase = time * .15 + step(6.0, vWorld.x) * .914;
  float haze = texture2D(tWind, uv + vec2(-phase, phase * .4)).r;
  haze *= texture2D(tWind, uv * 1.25 + vec2(-phase, .75)).r;
  haze *= texture2D(tWind, uv * .5 + vec2(-phase, -phase * .35)).r;
  float edge = (1.0 - vUv.y) * smoothstep(0.0, .1, vUv.y);
  edge *= smoothstep(0.0, .5, vUv.x) * (1.0 - smoothstep(.8, 1.0, vUv.x));
  // Increase optical density without changing the existing flow coordinates.
  // A smooth, capped opacity keeps relief visible through the brighter wisps.
  float density = min(1.0 - exp(-haze * edge * 8.0), .62);
  gl_FragColor = vec4(mix(skyColor(), vec3(.78, .84, .93), .58), density);
}
`;

export const SNOW_VERTEX = `
attribute float seed;
uniform float time, pixelRatio;
varying float vAlpha;
void main() {
  vec3 p = position;
  p.x += sin(time * .13 + seed * 40.0) * .5 + sin(time * .035 + seed * 19.0) * .8;
  p.y = mod(position.y + 10.0 - time * (.35 + seed * .30), 20.0) - 10.0;
  p.z += cos(time * .09 + seed * 31.0) * .25;
  vec4 view = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * view;
  gl_PointSize = clamp((1.3 + seed * 1.8) * 18.0 / max(-view.z, .5), .8, 4.0) * pixelRatio;
  vAlpha = (.15 + seed * .30) * smoothstep(.5, 2.0, -view.z) * (1.0 - smoothstep(30.0, 65.0, -view.z));
}
`;

export const SNOW_FRAGMENT = `
varying float vAlpha;
void main() {
  float radius = length(gl_PointCoord - .5) * 2.0;
  if (radius > 1.0) discard;
  gl_FragColor = vec4(vec3(1.0), (1.0 - smoothstep(.15, 1.0, radius)) * vAlpha);
}
`;

export const GRADE_FRAGMENT = `
uniform sampler2D tDiffuse;
uniform highp sampler3D lut;
uniform float lutSize;
uniform vec2 resolution;
varying vec2 vUv;
vec3 encode(vec3 c) { return mix(c * 12.92, 1.055 * pow(max(c, 0.0), vec3(1.0 / 2.4)) - .055, step(vec3(.0031308), c)); }
vec3 decode(vec3 c) { return mix(c / 12.92, pow(max((c + .055) / 1.055, 0.0), vec3(2.4)), step(vec3(.04045), c)); }
void main() {
  // One finish across terrain, stone and grains avoids pasted-on foregrounds.
  vec2 texel = .8 / max(resolution, vec2(1.0));
  vec3 source = texture2D(tDiffuse, vUv).rgb * .70;
  source += texture2D(tDiffuse, vUv + vec2(texel.x, 0)).rgb * .075;
  source += texture2D(tDiffuse, vUv - vec2(texel.x, 0)).rgb * .075;
  source += texture2D(tDiffuse, vUv + vec2(0, texel.y)).rgb * .075;
  source += texture2D(tDiffuse, vUv - vec2(0, texel.y)).rgb * .075;
  vec3 inputColor = encode(source);
  vec3 coordinate = clamp(inputColor, 0.0, 1.0) * (lutSize - 1.0);
  vec3 cell = floor(coordinate), fraction = coordinate - cell;
  // Sort the cube's fractional axes to choose its enclosing tetrahedron.
  vec3 first, second; float high, middle, low;
  if (fraction.x >= fraction.y && fraction.x >= fraction.z) {
    first = vec3(1, 0, 0); high = fraction.x;
    if (fraction.y >= fraction.z) { second = vec3(0, 1, 0); middle = fraction.y; low = fraction.z; }
    else { second = vec3(0, 0, 1); middle = fraction.z; low = fraction.y; }
  } else if (fraction.y >= fraction.z) {
    first = vec3(0, 1, 0); high = fraction.y;
    if (fraction.x >= fraction.z) { second = vec3(1, 0, 0); middle = fraction.x; low = fraction.z; }
    else { second = vec3(0, 0, 1); middle = fraction.z; low = fraction.x; }
  } else {
    first = vec3(0, 0, 1); high = fraction.z;
    if (fraction.x >= fraction.y) { second = vec3(1, 0, 0); middle = fraction.x; low = fraction.y; }
    else { second = vec3(0, 1, 0); middle = fraction.y; low = fraction.x; }
  }
  vec3 lowCorner = (cell + .5) / lutSize;
  vec3 result = texture(lut, lowCorner).rgb * (1.0 - high);
  result += texture(lut, lowCorner + first / lutSize).rgb * (high - middle);
  result += texture(lut, lowCorner + (first + second) / lutSize).rgb * (middle - low);
  result += texture(lut, lowCorner + 1.0 / lutSize).rgb * low;
  // Preserve emissive energy outside the LUT's display-referred range for bloom.
  gl_FragColor = vec4(decode(result) + max(source - 1.0, 0.0), 1.0);
}
`;
