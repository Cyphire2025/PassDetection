import { CORNEA_APERTURE, IRIS_EXPANSION } from "./test-hologram-eyes";
import { PARTICLE_CONTAINMENT } from "./test-hologram-containment";
import { MAX_PARTICLE_OFFSET, POINTER_RETURN_SECONDS, POINTER_TRAIL_LENGTH } from "./test-hologram-interaction";

/** Authored anatomy stays attached to every grain, including during displacement. */
export const HEAD_VERTEX = `
${PARTICLE_CONTAINMENT}
uniform vec4 articulation;
uniform float closure, blink, time, motion, pixelRatio, viewportHeight, pointScale, speechEnergy, ambientMotion, responseGlow;
uniform vec3 cursor;
uniform vec4 pointerStrokes[${POINTER_TRAIL_LENGTH}], pointerEnergies[${POINTER_TRAIL_LENGTH}];
uniform vec3 pointerRight, pointerUp;
attribute vec3 jawShape, roundShape, wideShape, closureShape, fricativeShape, blinkShape, eyeRegion, surfaceDetail;
varying vec3 vHeadNormal, vViewPosition, vEyeRegion, vSurfaceDetail;
varying float vFade, vSpeed, vHover, vSeed, vPointCoverage, vGrainRadius, vDisturbance;
void main() {
  vec3 canonical = position;
  vec3 eye = eyeRegion;
  vec3 p = position + jawShape*articulation.x + roundShape*articulation.y + wideShape*articulation.z
    + closureShape*closure + fricativeShape*articulation.w + blinkShape*blink;
  vec4 restView = modelViewMatrix*vec4(p,1.0), restClip = projectionMatrix*restView;
  vec2 screen = restClip.xy/max(restClip.w,.01);
  float aspect = projectionMatrix[1][1]/projectionMatrix[0][0];
  float ndcScale = projectionMatrix[1][1]*length(modelViewMatrix[0].xyz)/max(-restView.z,.2);
  vec3 offset = vec3(0.0);
  float wake = 0.0;
  for (int i=0;i<${POINTER_TRAIL_LENGTH};i++) {
    vec4 stroke = pointerStrokes[i], energy = pointerEnergies[i];
    float age = max(0.0,time-energy.x);
    float release = 1.0-smoothstep(0.0,${POINTER_RETURN_SECONDS},age);
    vec2 a = (screen-stroke.xy)*vec2(aspect,1.0), b = (stroke.zw-stroke.xy)*vec2(aspect,1.0);
    vec2 delta = (a-b*clamp(dot(a,b)/max(dot(b,b),.000001),0.0,1.0))/max(ndcScale,.001);
    float local = exp(-dot(delta,delta)/.025)*energy.y*release*motion;
    wake = max(wake,local);
    offset += (pointerRight*energy.z+pointerUp*energy.w+normal*.18)*local*.075;
  }
  offset *= min(1.0,${MAX_PARTICLE_OFFSET}/max(length(offset),.00001));
  // Small bounded breathing never changes the anatomical silhouette or accumulates drift.
  vec3 drift = sin(position.yzx*19.0+vec3(time*.8,time*.65,time*.73))* .006*ambientMotion*motion;
  p += offset + drift;
  if (eye.z > .5 && eye.z < 1.5) p.xy += eye.xy * ${IRIS_EXPANSION};
  vEyeRegion = eye;
  vSurfaceDetail = surfaceDetail;
  vDisturbance = wake;
  vSpeed = wake*1.5;
  vSeed = fract(sin(dot(position,vec3(17.13,93.71,41.19)))*43758.54);
  float faceDetail = smoothstep(.10,.30,canonical.z)*(1.0-smoothstep(.36,.52,abs(canonical.x)))
    *(1.0-smoothstep(.45,.65,canonical.y))*smoothstep(-.70,-.45,canonical.y);
  vec4 view = modelViewMatrix*vec4(p,1.0);
  gl_Position = projectionMatrix*view;
  // Hair locks keep their geometry, but a broad scalp normal avoids tiny dark
  // recesses dominating the small-screen silhouette after quantization/LOD.
  vec3 scalpNormal = normalize(vec3(canonical.x,(canonical.y-.25)*.7,canonical.z));
  vec3 shadingNormal = normalize(mix(normal,scalpNormal,smoothstep(.62,.80,canonical.y)*.65));
  vHeadNormal = normalize(normalMatrix*shadingNormal);
  vViewPosition = -view.xyz;
  vFade = smoothstep(-.92,-.74,canonical.y);
  vec2 separation = gl_Position.xy/max(gl_Position.w,.01)-cursor.xy;
  separation.x *= projectionMatrix[1][1]/projectionMatrix[0][0];
  vHover = exp(-dot(separation,separation)*22.0)*cursor.z*motion;
  float modelScale = length(modelViewMatrix[0].xyz);
  float size = pointScale*modelScale*viewportHeight*pixelRatio*projectionMatrix[1][1]/max(-view.z,.2);
  float detached = smoothstep(.02,.12,length(offset));
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
uniform float dark, opacity, speechEnergy, time, motion, responseGlow;
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
  float illumination = clamp(form * (.54 + diffuse * .46) + diffuse * .045 + specular * .010 - vSurfaceDetail.x * .04 - vSurfaceDetail.y * .24 - vSurfaceDetail.z * .06, 0.0, 1.0);
  vec3 frost = mix(vec3(.33, .368, .475), vec3(.60613, .65034, .81581), illumination);
  frost *= .99 + vSeed * .02;
  // Idle reassembly keeps diffuse form. Only a local pointer wake or speech
  // disturbance promotes moving grains into the luminous plume range.
  float moving = smoothstep(.005, .50, vDisturbance);
  vec3 luminous = mix(vec3(.48,.56,.70), vec3(.72,.86,1.02), illumination);
  frost = mix(frost, luminous, moving * .68);
  frost += vec3(.18,.32,.46)*moving*(.20+vSpeed*.18);
  // A sustained pearl/cyan response distinguishes playback, including quiet syllables.
  frost = mix(frost,vec3(.63,.82,1.06)*(.42+illumination*.70),responseGlow*.72);
  frost += vec3(.08,.15,.24)*responseGlow*(.25+speechEnergy*.45);
  frost = eyeColor(frost, illumination);
  gl_FragColor = vec4(frost, alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;
