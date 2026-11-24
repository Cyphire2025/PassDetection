/** Listening ripples, thinking folds and speech waves share one continuous clock. */
export const STATE_MOTION = `
uniform float uPhase;
uniform float uStateMotion;
uniform float uVoice;
vec2 stateMotion(vec2 uv,float time){
  vec2 p=uv-.5;
  float radius=length(p*vec2(1.0,.62));
  vec2 direction=p*inversesqrt(dot(p,p)+.015);
  vec2 listening=direction*sin(radius*30.0-time*2.1)*(1.4+uVoice*5.0);
  vec2 thinking=vec2(sin(p.y*8.0+time*.65)*3.0,sin(p.x*11.0+time*.8)*7.0);
  vec2 speaking=vec2(sin(p.y*12.0-time*2.0),sin(p.x*17.0-time*3.2))*(2.0+uVoice*10.0);
  return (listening*max(0.0,1.0-abs(uPhase-1.0))+thinking*max(0.0,1.0-abs(uPhase-2.0))
    +speaking*max(0.0,1.0-abs(uPhase-3.0)))*uStateMotion;
}
`;
