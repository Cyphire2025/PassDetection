/** Original shaders. Three supplies position/normal, camera matrices and output transforms. */
export const HEAD_VERTEX = `
attribute vec3 jawShape, roundShape, wideShape, closureShape, fricativeShape, blinkShape;
uniform vec4 articulation;
uniform float closure, blink, time, motion, pixelRatio, viewportHeight, pointScale;
uniform vec3 cursor;
#ifdef PARTICLE_DYNAMICS
attribute vec2 lookup;
uniform sampler2D displacement, velocity;
#endif
varying vec3 vHeadNormal, vViewPosition;
varying float vFade, vSpeed, vHover, vSeed, vPointCoverage;
void main() {
  vec3 p = position + jawShape * articulation.x + roundShape * articulation.y
    + wideShape * articulation.z + fricativeShape * articulation.w
    + closureShape * closure + blinkShape * blink;
  vSpeed = 0.0;
  vPointCoverage = 1.0;
  #ifdef PARTICLE_DYNAMICS
    vec3 surfaceNormal = normalize(normal);
    vec3 offset = texture2D(displacement, lookup).xyz * motion;
    // Keep the rendered particles on the exterior of their authored surface.
    // The mesh still occludes the back of the head, but an inward curl must not
    // bury a whole region behind that stationary depth surface.
    offset -= surfaceNormal * min(dot(offset, surfaceNormal), 0.0);
    p += offset + surfaceNormal * .003;
    vSpeed = min(length(texture2D(velocity, lookup).xyz) * 5.5, 1.5) * motion;
  #endif
  vec4 view = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * view;
  vHeadNormal = normalize(normalMatrix * normal);
  vViewPosition = -view.xyz;
  vFade = smoothstep(-1.035, -.86, position.y);
  vSeed = fract(sin(dot(position, vec3(17.13, 93.71, 48.52))) * 43758.54);
  vec2 separation = gl_Position.xy / max(gl_Position.w, .01) - cursor.xy;
  separation.x *= projectionMatrix[1][1] / projectionMatrix[0][0];
  vHover = exp(-dot(separation, separation) * 22.0) * cursor.z * motion;
  #ifdef PARTICLE_DYNAMICS
    float size = pointScale * viewportHeight * pixelRatio * projectionMatrix[1][1] / max(-view.z, .2);
    float shimmer = 1.0 + sin(time * .7 + vSeed * 19.0) * .018 * motion;
    float requestedSize = size * (.82 + vSeed * .36) * (1.0 + vSpeed * .27) * shimmer;
    gl_PointSize = clamp(requestedSize, .65, 8.0 * pixelRatio);
    // Most drivers rasterize points at a minimum of one physical pixel. Reduce
    // coverage below that size so extra samples add detail instead of opacity.
    vPointCoverage = min(1.0, requestedSize * requestedSize);
  #endif
}
`;

const FACE_LIGHT = `
uniform float dark, opacity;
varying vec3 vHeadNormal, vViewPosition;
varying float vFade, vSpeed, vHover, vSeed, vPointCoverage;
float anatomyLight() {
  vec3 n = normalize(vHeadNormal);
  float key = max(dot(n, normalize(vec3(-.65, .65, 1.1))), 0.0);
  float fill = max(dot(n, normalize(vec3(.8, -.1, .5))), 0.0);
  float rim = pow(1.0 - clamp(dot(n, normalize(vViewPosition)), 0.0, 1.0), 2.7);
  return clamp(.12 + key * .70 + fill * .10 + rim * .18, 0.0, 1.15);
}
`;

export const HEAD_FRAGMENT = `
${FACE_LIGHT}
void main() {
  vec2 point = gl_PointCoord * 2.0 - 1.0;
  point.y = -point.y;
  float radius = dot(point, point);
  if (radius > 1.0) discard;
  vec3 sphereNormal = vec3(point, sqrt(max(0.0, 1.0 - radius)));
  vec3 lightDirection = normalize(vec3(-.5, .7, 1.0));
  float diffuse = .30 + .70 * max(dot(sphereNormal, lightDirection), 0.0);
  float specular = pow(max(dot(sphereNormal, normalize(lightDirection + vec3(0.0, 0.0, 1.0))), 0.0), 22.0);
  float anatomy = anatomyLight();
  float silver = (.035 + pow(anatomy, 1.5) * .90) * diffuse + specular * .22 * anatomy;
  float graphite = (.018 + pow(anatomy, 2.0) * .68) * (.65 + diffuse * .35) + specular * .12 * anatomy;
  float radiance = mix(graphite, silver, dark);
  radiance += vSpeed * mix(1.4, 2.8, dark) + vHover * mix(.45, .75, dark);
  float coverage = 1.0 - smoothstep(.68, 1.0, radius);
  float density = mix(.70 + vSeed * .10, .86 + vSeed * .12, dark);
  gl_FragColor = vec4(vec3(radiance), coverage * density * vPointCoverage * vFade * opacity);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

export const SURFACE_FRAGMENT = `
${FACE_LIGHT}
void main() {
  float anatomy = anatomyLight();
  float radiance = mix(.012 + pow(anatomy, 2.4) * .48, .035 + anatomy * .38, dark);
  // A translucent depth surface reveals the brow, nose and lips between particles.
  gl_FragColor = vec4(vec3(radiance), mix(.92, .40, dark) * vFade * opacity);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

export const WIRE_FRAGMENT = `
${FACE_LIGHT}
void main() {
  float anatomy = anatomyLight();
  float radiance = mix(.11 + anatomy * .19, .30 + anatomy * .48, dark);
  gl_FragColor = vec4(vec3(radiance), mix(.10, .12, dark) * (.35 + anatomy * .65) * vFade * opacity);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;
