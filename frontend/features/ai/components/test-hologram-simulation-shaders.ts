import { PARTICLE_CONTAINMENT } from "./test-hologram-containment";
import { HEAD_FIELD_GLSL } from "./test-hologram-field-glsl";

// Position is absolute enclosure-space; velocity stores only the decaying
// interaction impulse. Ambient flow is first-order and integrated just once.
const INPUT = `
uniform sampler2D uRest, uFluid;
uniform float uDt, uTime, uSpeechEnergy, uInitialize;
uniform mat4 uEnclosure, uInverseEnclosure, uViewProjection, uFrameDelta;
uniform vec3 uCameraRight, uCameraUp;
vec3 inputPosition(vec2 uv) {
  return uInitialize > .5 ? (headToEnclosure*vec4(texture2D(uRest,uv).xyz,1.0)).xyz
    : texture2D(textureDisplacement,uv).xyz;
}
vec4 pointerInput(vec3 position) {
  vec4 clip = uViewProjection*uEnclosure*vec4(position,1.0);
  vec2 screen = clip.xy/max(clip.w,.0001)*.5+.5;
  float visible = step(.001,clip.w)*step(0.0,screen.x)*step(screen.x,1.0)*step(0.0,screen.y)*step(screen.y,1.0);
  vec3 fluid = texture2D(uFluid,clamp(screen,0.0,1.0)).xyz*visible;
  vec3 right = normalize((uInverseEnclosure*vec4(uCameraRight,0.0)).xyz);
  vec3 up = normalize((uInverseEnclosure*vec4(uCameraUp,0.0)).xyz);
  vec3 force = (right*fluid.x+up*fluid.y)*31.5+up*fluid.z*3.6;
  force *= min(1.0,24.0/max(length(force),.00001));
  return vec4(force,clamp(fluid.z,0.0,1.0));
}
vec3 impulseAt(vec2 uv, vec3 force, float dt) {
  vec3 previous = uInitialize > .5 ? vec3(0.0) : texture2D(textureVelocity,uv).xyz;
  previous = (uFrameDelta*vec4(previous,0.0)).xyz;
  // Faster release, with the input gain scaled equally to preserve plume reach.
  float decay = exp(-7.5*dt);
  return previous*decay+force*(1.0-decay)/7.5;
}
`;

const FLOW = `
vec3 vectorPotential(vec3 p, float t) {
  return vec3(sin(p.y+t)*cos(p.z*.79),
    sin(p.z*.91+t*.73)*cos(p.x),
    sin(p.x*.83-t*.61)*cos(p.y));
}
vec3 boundedPotential(vec3 p, float t) {
  vec3 canonical = (enclosureToHead*vec4(p,1.0)).xyz;
  float distance = headField(canonical).a*length(headToEnclosure[0].xyz);
  // Curl of this boundary-modulated potential is tangent to the zero surface.
  float boundary = -.12*tanh(distance/.12);
  return boundary*(vectorPotential(p*4.6+vec3(2.1,-.7,3.2),t*.70)
    + vectorPotential(p*8.1+vec3(-3.7,2.4,1.1),t*.51)*.28);
}
vec3 volumeFlow(vec3 p, float t) {
  // Differentiate the same interpolated scalar, not normalized mesh normals.
  float e = .012;
  vec3 dx = (boundedPotential(p+vec3(e,0,0),t)-boundedPotential(p-vec3(e,0,0),t))/(2.0*e);
  vec3 dy = (boundedPotential(p+vec3(0,e,0),t)-boundedPotential(p-vec3(0,e,0),t))/(2.0*e);
  vec3 dz = (boundedPotential(p+vec3(0,0,e),t)-boundedPotential(p-vec3(0,0,e),t))/(2.0*e);
  return vec3(dy.z-dz.y,dz.x-dx.z,dx.y-dy.x)*.52;
}
vec3 transportFlow(vec3 p, float t, float shell) {
  if (shell < .5) return volumeFlow(p,t);
  vec4 field = headField((enclosureToHead*vec4(p,1.0)).xyz);
  vec3 gradient = normalize((headToEnclosure*vec4(field.xyz,0.0)).xyz);
  vec3 q = p*vec3(2.7,3.1,3.3)+vec3(t*.675,-t*.405,t*.635);
  float second = p.x*2.4+t*.284;
  vec3 potentialGradient = vec3(2.7*cos(q.x)*sin(q.y)-2.4*sin(q.z)*sin(second),
    3.1*sin(q.x)*cos(q.y),3.3*cos(q.z)*cos(second));
  // Cross-gradients circulate the densely sampled boundary layer without
  // compressing it into a few stagnation points or identifying a home vertex.
  return cross(potentialGradient,gradient)*.147;
}
`;

export const DISPLACEMENT_STEP = `
${PARTICLE_CONTAINMENT}
${HEAD_FIELD_GLSL}
${INPUT}
${FLOW}
void main() {
  vec2 uv = gl_FragCoord.xy/resolution.xy;
  vec3 position = inputPosition(uv);
  vec4 seed = texture2D(uRest,uv);
  float layerDistance = headField(seed.xyz).a;
  vec4 interaction = pointerInput(position);
  vec3 transported = (uFrameDelta*vec4(position,1.0)).xyz;
  float previousDistance = headField((enclosureToHead*vec4(transported,1.0)).xyz).a;
  // Transport the moving volume without attaching material to anatomical homes.
  // Detached plumes retain their world-space inertia outside the shape.
  position = mix(transported,position,smoothstep(.025,.18,previousDistance));
  float scale = length(headToEnclosure[0].xyz);
  float steps = clamp(ceil(uDt/.035),1.0,8.0), h = uDt/steps;
  for (int i=0;i<8;i++) {
    if (float(i)>=steps) break;
    float t = uTime-uDt+h*float(i);
    float energy = 1.0+uSpeechEnergy*.32;
    vec3 flow = transportFlow(position,t,seed.w)*energy;
    flow = transportFlow(position+flow*h*.5,t+h*.5,seed.w)*energy;
    vec3 impulse = impulseAt(uv,interaction.xyz,h*(float(i)+.5));
    vec4 shape = headField((enclosureToHead*vec4(position,1.0)).xyz);
    vec3 gradient = normalize((headToEnclosure*vec4(shape.xyz,0.0)).xyz);
    vec3 recovery = gradient*max(shape.a*scale-.012,0.0)*mix(13.0,2.5,interaction.w);
    position += (flow+impulse-recovery)*h;
    if (seed.w > .5) {
      vec4 advanced = headField((enclosureToHead*vec4(position,1.0)).xyz);
      vec3 normal = normalize((headToEnclosure*vec4(advanced.xyz,0.0)).xyz);
      float correction = clamp((advanced.a-layerDistance)*scale,-h*.55,h*.55);
      position -= normal*correction*(1.0-smoothstep(.01,.12,length(impulse)));
    }
    vec3 local = (enclosureToHead*vec4(position,1.0)).xyz;
    position = (headToEnclosure*vec4(confineHead(local,.018),1.0)).xyz;
  }
  float wake = max(interaction.w,texture2D(textureDisplacement,uv).w*exp(-3.4*uDt));
  gl_FragColor = vec4(position,wake);
}
`;

export const VELOCITY_STEP = `
${PARTICLE_CONTAINMENT}
${INPUT}
void main() {
  vec2 uv = gl_FragCoord.xy/resolution.xy;
  vec4 interaction = pointerInput(inputPosition(uv));
  vec3 impulse = impulseAt(uv,interaction.xyz,uDt);
  gl_FragColor = vec4(impulse,length(impulse));
}
`;
