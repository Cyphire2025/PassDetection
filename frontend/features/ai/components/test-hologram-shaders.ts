import { CORNEA_APERTURE, IRIS_EXPANSION } from "./test-hologram-eyes";
import { PARTICLE_CONTAINMENT } from "./test-hologram-containment";
import { HEAD_FIELD_GLSL } from "./test-hologram-field-glsl";

/** Anatomy is sampled where each grain is now, never from its initial vertex. */
export const HEAD_VERTEX = `
${PARTICLE_CONTAINMENT}
${HEAD_FIELD_GLSL}
uniform vec4 articulation;
uniform float closure, blink, time, motion, pixelRatio, viewportHeight, pointScale, speechEnergy;
uniform vec3 cursor;
attribute vec2 lookup;
uniform sampler2D displacement, velocity;
varying vec3 vHeadNormal, vViewPosition, vEyeRegion, vSurfaceDetail;
varying float vFade, vSpeed, vHover, vSeed, vPointCoverage, vGrainRadius, vDisturbance;
void main() {
  vec4 state = texture2D(displacement, lookup);
  vec3 canonical = motion > .5 ? (enclosureToHead*vec4(state.xyz,1.0)).xyz : position;
  vec4 shape = headField(canonical);
  vec3 eye = headEyeRegion(canonical);
  vec3 detail = headSurfaceDetail(canonical);
  vec3 surfaceNormal = headSurfaceNormal(canonical);
  vec3 p = canonical + headMorph(canonical, articulation.x, articulation.y, articulation.z, closure, articulation.w, blink);
  if (eye.z > .5 && eye.z < 1.5) p.xy += eye.xy * ${IRIS_EXPANSION};
  vEyeRegion = eye;
  vSurfaceDetail = vec3(detail.xy,clamp(-shape.a*5.0,0.0,1.0));
  vDisturbance = state.w*motion;
  vSpeed = min(length(texture2D(velocity,lookup).xyz)*3.8,1.5)*motion;
  vSeed = fract(sin(dot(lookup,vec2(17.13,93.71)))*43758.54);
  float faceDetail = smoothstep(.10,.30,canonical.z)*(1.0-smoothstep(.36,.52,abs(canonical.x)))
    *(1.0-smoothstep(.45,.65,canonical.y))*smoothstep(-.70,-.45,canonical.y);
  vec4 view = modelViewMatrix*vec4(p,1.0);
  gl_Position = projectionMatrix*view;
  vHeadNormal = normalize(normalMatrix*surfaceNormal);
  vViewPosition = -view.xyz;
  vFade = smoothstep(-.92,-.74,canonical.y);
  vec2 separation = gl_Position.xy/max(gl_Position.w,.01)-cursor.xy;
  separation.x *= projectionMatrix[1][1]/projectionMatrix[0][0];
  vHover = exp(-dot(separation,separation)*22.0)*cursor.z*motion;
  float modelScale = length(modelViewMatrix[0].xyz);
  float size = pointScale*modelScale*viewportHeight*pixelRatio*projectionMatrix[1][1]/max(-view.z,.2);
  float detached = smoothstep(.025,.12,shape.a)*smoothstep(.03,.40,vDisturbance);
  size *= mix(mix(.88,.65,faceDetail),mix(1.18,.80,faceDetail),detached);
  size *= eye.z > .5 ? .4 : 1.0;
  float shimmer = 1.0+sin(time*.7+vSeed*19.0)*.018*motion;
  float requestedSize = size*(2.05+pow(vSeed,.7)*1.05)*(1.0+vSpeed*.16+speechEnergy*.035*motion)*shimmer;
  gl_PointSize = clamp(requestedSize,max(.8,pixelRatio*1.15),12.0*pixelRatio);
  vGrainRadius = gl_PointSize*max(-view.z,.2)/max(viewportHeight*pixelRatio*projectionMatrix[1][1],1.0);
  float enclosureScale = length(headToEnclosure[0].xyz);
  float margin = vGrainRadius*enclosureScale/max(modelScale,.0001)+.004;
  p = confineHead(p,margin);
  view = modelViewMatrix*vec4(p,1.0);
  gl_Position = projectionMatrix*view;
  vViewPosition = -view.xyz;
  vPointCoverage = min(1.0,requestedSize*requestedSize);
}
`;

const FACE_LIGHT = `
uniform float dark, opacity, speechEnergy, time, motion;
varying vec3 vHeadNormal, vViewPosition;
varying vec3 vEyeRegion;
varying vec3 vSurfaceDetail;
varying float vFade, vSpeed, vHover, vSeed, vPointCoverage, vGrainRadius, vDisturbance;
bool clearCornea() { return vEyeRegion.z > 1.5 && length(vEyeRegion.xy) < ${CORNEA_APERTURE}; }
float anatomyLight(vec3 n) {
  float key = max(dot(n, normalize(vec3(-.65, .65, 1.1))), 0.0);
  float fill = max(dot(n, normalize(vec3(.8, -.1, .5))), 0.0);
  float rim = pow(1.0 - clamp(dot(n, normalize(vViewPosition)), 0.0, 1.0), 2.7);
  return clamp(.07 + key * .76 + fill * .085 + rim * .12, 0.0, 1.15);
}
float anatomyLight() { return anatomyLight(normalize(vHeadNormal)); }
vec3 eyeColor(vec3 frost, float form) {
  if (vEyeRegion.z > .5 && vEyeRegion.z < 1.5) {
    float radius = length(vEyeRegion.xy);
    float pupil = 1.0 - smoothstep(.31, .46, radius);
    float limbus = smoothstep(.66, .94, radius);
    vec3 iris = mix(vec3(.38563, .42897, .54795), vec3(.44121, .49056, .61582), form);
    return mix(iris, vec3(.33915, .37581, .47849), max(pupil, limbus * .80));
  }
  if (vEyeRegion.z > 1.5) return mix(vec3(.46, .50, .57), vec3(.61, .65, .71), form);
  return frost;
}
`;

export const HEAD_FRAGMENT = `
${FACE_LIGHT}
uniform mat4 projectionMatrix;
void main() {
  if (clearCornea()) discard;
  vec2 point = gl_PointCoord * 2.0 - 1.0;
  point.y = -point.y;
  point *= vec2(.88 + vSeed * .20, 1.08 - vSeed * .14);
  float grainAngle = atan(point.y, point.x);
  point *= 1.0 + sin(grainAngle * 5.0 + vSeed * 31.0) * .055;
  float radius = dot(point, point);
  if (radius > 1.0) discard;
  float edge = 1.0 - smoothstep(.82, 1.0, radius);
  float alpha = edge * vPointCoverage * vFade * opacity;
  if (alpha < .005) discard;
  vec3 sphereNormal = vec3(point, sqrt(max(0.0, 1.0 - radius)));
  // Rounded impostors write their own curved depth, so near grains occlude far
  // grains instead of accumulating a flat translucent layer over the face.
  vec4 grainClip = projectionMatrix * vec4(-vViewPosition + vec3(0.0, 0.0, sphereNormal.z * vGrainRadius), 1.0);
  gl_FragDepth = grainClip.z / grainClip.w * .5 + .5;
  vec3 lightDirection = normalize(vec3(-.5, .7, 1.0));
  float diffuse = .12 + .88 * max(dot(sphereNormal, lightDirection), 0.0);
  float specular = pow(max(dot(sphereNormal, normalize(lightDirection + vec3(0.0, 0.0, 1.0))), 0.0), 9.0);
  float anatomy = anatomyLight();
  // These cool endpoints account for the shared landscape LUT and output tone
  // mapping: cool gray shadows and soft snow highlights, without saturated blue.
  // Broad facial form and each grain's rounded relief remain separate scales.
  float form = pow(clamp((anatomy - .09) / .90, 0.0, 1.0), 1.4);
  // Interior grains remain opaque, rounded material. A bounded depth shadow
  // reveals volume through surface gaps without turning the fill into haze.
  // A grain in a facial recess cannot receive the same bright fill as a grain
  // facing the key light. Couple its rounded relief to the anatomical lighting.
  float illumination = clamp(form * (.32 + diffuse * .68) + diffuse * .045 + specular * .015 - vSurfaceDetail.x * .04 - vSurfaceDetail.y * .24 - vSurfaceDetail.z * .10, 0.0, 1.0);
  vec3 frost = mix(vec3(.33, .368, .475), vec3(.60613, .65034, .81581), illumination);
  frost *= .99 + vSeed * .02;
  // Idle reassembly keeps diffuse form. Only a local pointer wake or speech
  // disturbance promotes moving grains into the luminous plume range.
  float excitation = clamp(.04 + smoothstep(.08, .65, vDisturbance) * .88 + speechEnergy * .25, 0.0, 1.0);
  float moving = smoothstep(.18, 1.3, vSpeed) * excitation;
  vec3 luminous = mix(vec3(.64, .73, .83), vec3(.87, .94, 1.0), diffuse);
  frost = mix(frost, luminous, moving * .92);
  frost += vec3(vHover * .008 + speechEnergy * .02 * anatomy);
  frost = eyeColor(frost, illumination);
  gl_FragColor = vec4(frost, alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;
