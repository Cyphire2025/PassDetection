export const EARTH_VERTEX = `
attribute vec2 aPosition;
varying vec2 vScreen;
void main() { vScreen = aPosition; gl_Position = vec4(aPosition, 0.0, 1.0); }
`;

export const EARTH_FRAGMENT = `
precision highp float;
uniform sampler2D uLand;
uniform mat3 uCamera;
uniform vec2 uAspect;
uniform float uScale;
uniform float uCard;
varying vec2 vScreen;
const float PI = 3.14159265359;
void main() {
  vec2 xy = vScreen * uAspect / uScale;
  float r2 = dot(xy, xy);
  if (r2 > 1.06) discard;
  if (r2 > 1.0) {
    float air = (1.0 - smoothstep(1.0, 1.06, r2)) * 0.14;
    gl_FragColor = vec4(0.30, 0.68, 0.79, air);
    return;
  }
  vec3 normal = vec3(xy, sqrt(1.0 - r2));
  vec3 world = vec3(dot(uCamera[0], normal), dot(uCamera[1], normal), dot(uCamera[2], normal));
  float longitude = atan(world.x, world.z);
  float latitude = asin(clamp(world.y, -1.0, 1.0));
  vec2 uv = vec2(longitude / (2.0 * PI) + 0.5, 0.5 - latitude / PI);
  float land = texture2D(uLand, uv).r;
  float shade = max(0.0, dot(normal, normalize(vec3(-0.55, 0.7, 1.3))));
  vec3 ocean = mix(vec3(0.025, 0.29, 0.42), vec3(0.025, 0.22, 0.31), uCard);
  vec3 continent = mix(vec3(0.76, 0.85, 0.81), vec3(0.36, 0.55, 0.57), uCard);
  vec3 base = mix(ocean, continent, smoothstep(0.1, 0.9, land));
  // A restrained meridian grid gives scale without replacing real coastline data.
  float meridian = 1.0 - smoothstep(0.005, 0.018, abs(sin(longitude * 12.0)));
  float parallel = 1.0 - smoothstep(0.005, 0.018, abs(sin(latitude * 12.0)));
  base += vec3(0.15, 0.25, 0.27) * max(meridian, parallel) * 0.12 * (1.0 - land);
  vec3 color = base * (0.43 + 0.66 * shade);
  float waterLight = pow(max(0.0, dot(normal, normalize(vec3(-0.34, 0.38, 1.0)))), 34.0);
  color += vec3(0.18, 0.38, 0.43) * waterLight * (1.0 - land) * 0.3;
  color += vec3(0.09, 0.30, 0.36) * pow(1.0 - normal.z, 3.5) * 0.42;
  gl_FragColor = vec4(color, 1.0);
}
`;

export const OBJECT_VERTEX = `
attribute vec3 aPosition;
uniform mat3 uCamera;
uniform vec2 uAspect;
uniform float uScale;
varying vec3 vView;
void main() {
  vView = uCamera * aPosition;
  gl_Position = vec4(vView.xy * uScale / uAspect, 0.0, 1.0);
}
`;

export const OBJECT_FRAGMENT = `
precision highp float;
uniform vec4 uColor;
varying vec3 vView;
void main() {
  float radial = dot(vView.xy, vView.xy);
  // The Earth is rendered analytically, so use the same surface for occlusion.
  // Endpoints remain attached to geography even after dragging to its far side.
  if (radial < 1.0 && vView.z < sqrt(1.0 - radial) - 0.004) discard;
  gl_FragColor = uColor;
}
`;
