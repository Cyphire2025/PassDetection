/** Liquid sculpture shaders adapted from Sculpture Hero by guglielmogiannattasio.it, supplied via 21st.dev. */

const NOISE = `
float hash(vec2 p){ p = fract(p*vec2(123.34,456.21)); p += dot(p,p+45.32); return fract(p.x*p.y); }
float vnoise(vec2 p){ vec2 i=floor(p); vec2 f=fract(p); vec2 u=f*f*f*(f*(f*6.0-15.0)+10.0);
  return mix(mix(hash(i),hash(i+vec2(1.0,0.0)),u.x), mix(hash(i+vec2(0.0,1.0)),hash(i+vec2(1.0,1.0)),u.x), u.y); }
vec2 ambientField(vec2 uv, float t){
  vec2 q = uv*vec2(3.2,1.7);
  vec2 a = vec2(vnoise(q+vec2(t*0.11,0.0))-0.5, vnoise(q+vec2(5.2,t*0.08)+3.1)-0.5);
  vec2 q2 = uv*vec2(7.5,4.0) + vec2(-t*0.19, t*0.13);
  vec2 b = vec2(vnoise(q2+1.7)-0.5, vnoise(q2+9.3)-0.5);
  return a + b*0.45;
}
`

/* energy of the material at a point: shared by image and particles so the
   cross-fade is exactly complementary */
const ENERGY = `
float energyAt(vec2 rectPx, vec2 mouse, float radius, float presence, float wakeEnergy){
  vec2 d = rectPx - mouse;
  float f = exp(-dot(d,d)/(radius*radius))*presence;
  return smoothstep(0.06, 0.5, f*1.15 + wakeEnergy*1.7);
}
`

const QUAD_VS = `#version 300 es
layout(location=0) in vec2 aPos;
out vec2 vUv;
void main(){ vUv = aPos*0.5+0.5; gl_Position = vec4(aPos,0.0,1.0); }
`

/* Flow map (cursor wake). RGBA8: velocity encoded around 128, energy in B. */
const FLOW_FS = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 o;
uniform sampler2D uPrev;
uniform vec2 uTexel;
uniform vec2 uMouse;
uniform vec2 uVel;
uniform vec2 uPointer;
uniform vec2 uPointerVel;
uniform float uPointerPresence;
uniform vec2 uSize;
uniform float uRadius;
uniform float uPresence;
uniform float uDecay;
vec2 decV(vec4 c){ return (c.rg*255.0-128.0)/127.0; }
void main(){
  vec2 v0 = decV(texture(uPrev, vUv));
  vec2 uv = vUv - v0*uTexel*2.5;
  vec4 c = texture(uPrev, uv)*0.52
    + 0.12*(texture(uPrev, uv+vec2(uTexel.x,0.0)) + texture(uPrev, uv-vec2(uTexel.x,0.0))
          + texture(uPrev, uv+vec2(0.0,uTexel.y)) + texture(uPrev, uv-vec2(0.0,uTexel.y)));
  vec2 v = decV(c);
  float p = c.b;
  vec2 d = (vUv-uMouse)*uSize;
  float f = exp(-dot(d,d)/(uRadius*uRadius))*uPresence;
  float sp = clamp(length(uVel)*2.5, 0.0, 1.0);
  v += uVel*f*0.22;
  p = max(p, f*sp);
  vec2 pd = (vUv-uPointer)*uSize;
  float pf = exp(-dot(pd,pd)/(uRadius*uRadius*.58))*uPointerPresence;
  v += uPointerVel*pf*.19;
  p = max(p,pf*clamp(length(uPointerVel)*2.5,0.0,1.0));
  v *= uDecay;
  p *= uDecay;
  v = sign(v)*max(abs(v)-1.2/127.0, 0.0);
  p = max(p-1.2/255.0, 0.0);
  v = clamp(v, -1.0, 1.0);
  o = vec4((v*127.0+128.0)/255.0, p, 1.0);
}
`

/* GPGPU step: state = (offset.xy, velocity.xy) in rect CSS px. */
const SIM_FS = `#version 300 es
precision highp float;
out vec4 o;
uniform sampler2D uState;
uniform sampler2D uHome;
uniform sampler2D uFlow;
uniform vec2 uSize;
uniform vec2 uMouse;
uniform float uRadius;
uniform float uPresence;
uniform float uStrength;
uniform float uSpread;
uniform float uTurb;
uniform float uReturn;
uniform float uTime;
uniform float uDt;
uniform float uIntro;
uniform vec2 uPointer;
uniform float uPointerPresence;
${NOISE}
vec2 curl(vec2 p){
  const float e = 0.35;
  float a = vnoise(p+vec2(0.0,e)) - vnoise(p-vec2(0.0,e));
  float b = vnoise(p+vec2(e,0.0)) - vnoise(p-vec2(e,0.0));
  return vec2(a, -b)/(2.0*e);
}
void main(){
  ivec2 ij = ivec2(gl_FragCoord.xy);
  vec4 hm = texelFetch(uHome, ij, 0);
  if(hm.w <= 0.0){ o = vec4(0.0); return; }
  vec4 st = texelFetch(uState, ij, 0);
  vec2 off = st.xy;
  vec2 vel = st.zw;
  float sd = hm.z;
  float light = 0.45 + sd*1.1;

  vec2 p = hm.xy*uSize + off;
  vec4 fl = texture(uFlow, clamp(p/uSize, 0.0, 1.0));
  vec2 wake = (fl.rg*255.0-128.0)/127.0;
  float pr = fl.b;

  vec2 toM = p - uMouse;
  float r2 = dot(toM,toM);
  float f = exp(-r2/(uRadius*uRadius))*uPresence;
  vec2 n = toM*inversesqrt(r2+1.0);
  float e = clamp(pr*2.0 + f, 0.0, 1.0);

  vec2 acc = vec2(0.0);
  // blown outward and swirled around the cursor
  acc += n*f*1.25*uStrength*uSpread*light;
  acc += vec2(-n.y, n.x)*f*1.45*uStrength*uSpread*(0.4+sd);
  // carried by the liquid wake
  acc += (wake*42.0*uSpread*light - vel)*e*0.08;
  // curl-noise turbulence where the material is disturbed (and during the intro)
  vec2 q = p*0.0095 + vec2(uTime*0.35, -uTime*0.2);
  vec2 c = curl(q) + 0.5*curl(q*2.3 + 7.1);
  acc += c*(e*1.2*uSpread + uIntro*1.5)*uTurb*light;
  // A real pointer remains independent of the voice-driven figure eight.
  vec2 pd = p-uPointer;
  float pf = exp(-dot(pd,pd)/(uRadius*uRadius*.58))*uPointerPresence;
  vec2 pn = pd*inversesqrt(dot(pd,pd)+16.0);
  acc += (pn*1.35+vec2(-pn.y,pn.x)*.7)*pf*uSpread*light;
  acc += c*pf*.6*uTurb;
  // elastic return home
  float k = (0.006 + 0.02*uReturn)*(0.65+sd*0.7)*(1.0 - uIntro*0.75);
  acc -= off*k;

  vel += acc*uDt;
  vel *= pow(mix(0.93, 0.955, e), uDt);
  off += vel*uDt;
  if(dot(off,off) < 0.0004 && dot(vel,vel) < 0.0004){ off = vec2(0.0); vel = vec2(0.0); }
  o = vec4(off, vel);
}
`

/* Particles: one instanced quad per particle, a capsule stretched along velocity. */
const PART_VS = `#version 300 es
precision highp float;
layout(location=0) in vec2 aCorner;
uniform sampler2D uState;
uniform sampler2D uHome;
uniform sampler2D uCol;
uniform sampler2D uFlow;
uniform int uTexW;
uniform int uIdleStride;
uniform vec4 uRect;
uniform vec2 uRes;
uniform vec2 uMouse;
uniform float uRadius;
uniform float uPresence;
uniform float uDot;
uniform float uTime;
uniform float uAmbient;
uniform float uStreak;
uniform float uIntroVis;
uniform float uRest;
uniform vec3 uTint;
uniform float uReply;
uniform float uReveal;
uniform vec2 uRevealSize;
uniform float uDark;
uniform vec2 uPointer;
uniform vec2 uPointerVel;
uniform float uPointerPresence;
uniform float uVoice;
out vec2 vLocal;
out float vHalfLen;
out float vR;
out vec3 vCol;
out float vA;
${NOISE}
${ENERGY}
// A rounded rectangle parameterized by arc length keeps the original material
// evenly spread across all four edges, including the corners.
vec4 boundary(float distance, vec2 size, float radius){
  vec2 halfSize = size*.5;
  float w = max(0.0, size.x-2.0*radius);
  float h = max(0.0, size.y-2.0*radius);
  float arc = 1.57079632679*radius;
  float side = w+h+2.0*arc;
  float d = mod(distance, side*2.0);
  bool opposite = d >= side;
  d = mod(d, side);
  vec2 point;
  vec2 normal;
  if(d < w){ point = vec2(-halfSize.x+radius+d, -halfSize.y); normal = vec2(0.0,-1.0); }
  else if(d < w+arc){
    float angle = -1.57079632679+(d-w)/max(radius,.01);
    normal = vec2(cos(angle),sin(angle));
    point = vec2(halfSize.x-radius,-halfSize.y+radius)+normal*radius;
  } else if(d < w+arc+h){ point = vec2(halfSize.x,-halfSize.y+radius+d-w-arc); normal = vec2(1.0,0.0); }
  else {
    float angle = (d-w-arc-h)/max(radius,.01);
    normal = vec2(cos(angle),sin(angle));
    point = vec2(halfSize.x-radius,halfSize.y-radius)+normal*radius;
  }
  if(opposite){ point = -point; normal = -normal; }
  return vec4(point,normal);
}
void main(){
  int id = gl_InstanceID*uIdleStride;
  ivec2 ij = ivec2(id % uTexW, id / uTexW);
  vec4 hm = texelFetch(uHome, ij, 0);
  vec4 st = texelFetch(uState, ij, 0);
  vec4 cl = texelFetch(uCol, ij, 0);

  float wakeE = texture(uFlow, hm.xy).b;
  float E = max(energyAt(hm.xy*uRect.zw, uMouse, uRadius, uPresence, wakeE),
    energyAt(hm.xy*uRect.zw,uPointer-uRect.xy,uRadius*.76,uPointerPresence,0.0));
  float lift = smoothstep(0.35, 2.5, length(st.xy));
  float looseGrain = uIdleStride > 1 ? 1.0 : step(0.982, hm.z);
  float idle = looseGrain*min(0.3, uAmbient*0.27);
  float a = max(max(E, lift), max(max(uRest, idle), 1.0-uIntroVis));
  a = max(a, smoothstep(0.0,.14,uReveal));
  if(a < 0.01 || hm.w <= 0.0){ gl_Position = vec4(2.0,2.0,2.0,1.0); return; }

  vec2 base = uRect.xy + hm.xy*uRect.zw + st.xy;
  base -= ambientField(hm.xy, uTime)*18.0*uAmbient;
  // Different seeds give the loose grains their own slow orbit. The material
  // stays horizontal and breathes without pretending that the microphone is on.
  float loosen = looseGrain*(1.0-E)*(1.0-uReveal);
  base += vec2(sin(hm.z*1537.0+uTime*.75), cos(hm.z*971.0+uTime*.61))
    *(4.0+hm.w*8.0)*uAmbient*loosen;
  if(uReveal > 0.0){
    vec2 extent = max(vec2(1.0), uRevealSize*uReveal);
    float radius = min(13.0,min(extent.x,extent.y)*.25);
    // hm.z and home UVs belong to each existing sculpture particle. No border
    // emitter, replacement buffer or extra instances are created for the reveal.
    float seed = hm.z;
    float layer = hash(hm.xy*371.0+seed);
    float band = clamp(min(uRevealSize.x,uRevealSize.y)*.09,13.0,37.0);
    float depth = 7.0+band*(.08+.92*pow(layer,1.25));
    // Travel on the OUTER lane's arc length. Offsetting an inner path made the
    // corners unnaturally fast and sparse, especially in the outer layers.
    vec2 laneSize = extent+vec2(depth*2.0);
    float laneRadius = radius+depth;
    float perimeter = 2.0*(laneSize.x+laneSize.y-4.0*laneRadius)+6.28318530718*laneRadius;
    float stream = hash(hm.xy*187.0+seed*7.0);
    float direction = stream < .5 ? -1.0 : 1.0;
    float travel = seed*perimeter+uTime*direction*(8.0+stream*10.0)
      + sin(seed*197.0+uTime*.38)*7.0;
    vec4 edge = boundary(travel,laneSize,laneRadius);
    vec2 tangent = vec2(-edge.w,edge.z);
    float orbit = seed*331.0+uTime*(.65+stream*.45);
    float swell = sin(travel*.018-uTime*.6)*2.0;
    vec2 eddy = tangent*cos(orbit)*3.6+edge.zw*(sin(orbit)*3.5+swell);
    // Voice lifts local folds without turning the entire cloud into a rigid belt.
    eddy += edge.zw*sin(travel*.025-uTime*1.2)*(1.0+uVoice*7.0);
    vec2 target = uRes*.5+edge.xy+eddy;
    vec2 pointerDelta = target-uPointer;
    float pointerFall = exp(-dot(pointerDelta,pointerDelta)/(uRadius*uRadius*.5))*uPointerPresence;
    vec2 pointerNormal = pointerDelta*inversesqrt(dot(pointerDelta,pointerDelta)+36.0);
    target += (pointerNormal*22.0+vec2(-pointerNormal.y,pointerNormal.x)*8.0
      + clamp(uPointerVel,vec2(-24.0),vec2(24.0))*.5)*pointerFall;
    float gather = smoothstep(.04,.94,uReveal);
    base = mix(base,target,gather);
    // The expanding panel physically pushes any remaining material it reaches.
    // Reversing the same progress returns each grain to its own original home.
    vec2 delta = base-uRes*.5;
    vec2 q = abs(delta)-(extent*.5-vec2(radius));
    vec2 outside = max(q,vec2(0.0));
    float distance = length(outside)+min(max(q.x,q.y),0.0)-radius;
    vec2 normal = length(outside) > .001 ? sign(delta)*normalize(outside)
      : q.x > q.y ? vec2(sign(delta.x+.001),0.0) : vec2(0.0,sign(delta.y+.001));
    base += normal*max(0.0,2.0-distance)*smoothstep(0.0,.08,uReveal);
  }

  vec2 v = st.zw;
  float sp = length(v);
  vec2 dir = sp > 0.001 ? v/sp : vec2(1.0,0.0);
  float r = uDot*hm.w*0.5;
  r = mix(r, max(.45,r*(.72+hm.z*.5)),uReveal);
  float len = min(sp*1.15, 13.0)*uStreak*(1.0-uReveal);
  vec2 lc = aCorner*vec2(r + len*0.5 + 1.0, r + 1.0);
  vec2 center = base - dir*len*0.5;
  vec2 world = center + dir*lc.x + vec2(-dir.y, dir.x)*lc.y;

  vec2 clip = world/uRes*2.0-1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  vLocal = lc;
  vHalfLen = len*0.5;
  vR = r;
  vec3 col = cl.rgb*uTint;
  // Retain the sand/silver material in dark mode; the keyed image background
  // must never tint the displaced grains to the page's near-black colour.
  col = mix(col, max(col,cl.rgb*.82+vec3(.05,.045,.035)),uDark);
  col = mix(col, vec3(col.r*.52, col.g*1.02, col.b*1.2), uReply*.78);
  // fast material catches the light, like liquid metal
  float glint = smoothstep(2.0, 16.0, sp);
  col = mix(col, min(col*1.14 + vec3(0.05,0.055,0.065), vec3(1.0)), glint*0.55);
  vCol = col;
  vA = a;
}
`

const PART_FS = `#version 300 es
precision highp float;
in vec2 vLocal;
in float vHalfLen;
in float vR;
in vec3 vCol;
in float vA;
uniform float uDpr;
out vec4 o;
void main(){
  vec2 q = vec2(max(abs(vLocal.x)-vHalfLen, 0.0), vLocal.y);
  float d = length(q) - vR;
  float feather = max(.72/uDpr,fwidth(d)*.65);
  float a = 1.0-smoothstep(-feather,feather,d);
  // comet tail: the trailing end thins out
  float tail = vHalfLen > 0.0 ? clamp(0.5 - vLocal.x/(2.0*(vHalfLen+vR)), 0.0, 1.0) : 0.0;
  a *= 1.0 - tail*0.55;
  a *= vA;
  if(a < 0.004) discard;
  o = vec4(vCol*a, a);
}
`

/* Image pass: the crisp sculpture, gently lensed, fading out where the
   material has turned liquid. */
const IMAGE_FS = `#version 300 es
precision highp float;
out vec4 o;
uniform sampler2D uImg;
uniform sampler2D uFlow;
uniform vec2 uRes;
uniform float uDpr;
uniform vec4 uRect;
uniform vec3 uBg;
uniform vec3 uImgBg;
uniform vec2 uMouse;
uniform float uPresence;
uniform float uRadius;
uniform float uStrength;
uniform float uTime;
uniform float uAmbient;
uniform float uIntroVis;
uniform float uRest;
uniform float uAlphaMode;
uniform float uDark;
uniform float uReply;
uniform float uReveal;
uniform vec2 uPointer;
uniform vec2 uPointerVel;
uniform float uPointerPresence;
${NOISE}
${ENERGY}
void main(){
  vec2 px = vec2(gl_FragCoord.x, uRes.y*uDpr - gl_FragCoord.y)/uDpr;
  vec2 size = uRect.zw;
  vec2 uv = (px-uRect.xy)/size;
  if(uv.x < -0.05 || uv.x > 1.05 || uv.y < -0.12 || uv.y > 1.12){ o = vec4(0.0); return; }
  vec4 fl = texture(uFlow, clamp(uv,0.0,1.0));
  vec2 vel = (fl.rg*255.0-128.0)/127.0;
  vec2 rp = uv*size;
  vec2 toM = rp - uMouse;
  float fall = exp(-dot(toM,toM)/(uRadius*uRadius))*uPresence;
  vec2 disp = -toM*0.22*uStrength*fall - vel*10.0*uStrength;
  disp += ambientField(uv, uTime)*18.0*uAmbient;
  vec2 pointerDelta = rp-uPointer;
  float pointerFall = exp(-dot(pointerDelta,pointerDelta)/(uRadius*uRadius*.58))*uPointerPresence;
  disp -= pointerDelta*.15*pointerFall+uPointerVel*.32*pointerFall;
  vec2 suv = uv + disp/size;
  vec4 tx = texture(uImg, suv);
  // Most pixels are empty. Key them before the detail filter, avoiding four
  // extra texture samples across the clear background on every idle frame.
  float key = uAlphaMode > 0.5 ? tx.a : smoothstep(mix(.012,.018,uDark), mix(.05,.13,uDark), length(tx.rgb-uImgBg));
  if(key < 0.001){ o = vec4(0.0); return; }
  vec2 texel = 1.0/vec2(textureSize(uImg, 0));
  vec3 around = texture(uImg, suv+vec2(texel.x,0.0)).rgb
    + texture(uImg, suv-vec2(texel.x,0.0)).rgb
    + texture(uImg, suv+vec2(0.0,texel.y)).rgb
    + texture(uImg, suv-vec2(0.0,texel.y)).rgb;
  vec3 col = clamp(tx.rgb + (tx.rgb*4.0-around)*0.055, 0.0, 1.0);
  vec2 e = smoothstep(vec2(0.0), vec2(0.004,0.01), suv) * smoothstep(vec2(1.0), vec2(0.996,0.99), suv);
  // cut-out images carry their own alpha; flat-background images are keyed by colour
  float k = key*e.x*e.y;
  float E = max(energyAt(rp, uMouse, uRadius, uPresence, fl.b),
    energyAt(rp,uPointer,uRadius*.76,uPointerPresence,0.0));
  float show = (1.0 - max(E, uRest))*uIntroVis;
  vec3 mat = uAlphaMode > 0.5 ? col : col*(uBg/max(uImgBg, vec3(0.001)));
  // Remove the pale source matte from partially covered edges on a dark page.
  // Core material and highlights keep their original warm metallic colours.
  if(uAlphaMode < .5) mat = mix(mat, clamp((col-uImgBg*(1.0-key))/max(key,.06),0.0,1.0), uDark);
  mat = mix(mat, vec3(mat.r*.52, mat.g*1.02, mat.b*1.2), uReply*.78);
  // premultiplied: empty areas stay transparent so the page (and the backdrop word) shows through
  float A = k*show*(1.0-smoothstep(0.0,.55,uReveal));
  o = vec4(mat*A, A);
}
`

/* ── helpers ─────────────────────────────────────────────────────────── */


export { QUAD_VS, FLOW_FS, SIM_FS, PART_VS, PART_FS, IMAGE_FS };
