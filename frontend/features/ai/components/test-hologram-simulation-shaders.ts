// Original integration shared by both state outputs, which read the same previous frame.
const ADVANCE = `
uniform sampler2D uRest;
uniform sampler2D uFluid;
uniform float uDt;
uniform float uTime;
uniform mat4 uModel;
uniform mat4 uInverseModel;
uniform mat4 uViewProjection;
uniform vec3 uCameraRight;
uniform vec3 uCameraUp;

vec3 curlField(vec3 p, float time) {
  // Curl of three cross-axis sinusoidal potentials: smooth, divergence-free detail.
  return vec3(
    -0.75 * cos(p.z * 2.7 + time * 0.37) - 0.35 * sin(p.y * 5.1 - time * 0.23),
    -0.85 * cos(p.x * 3.1 - time * 0.29) + 0.28 * sin(p.z * 4.7 + time * 0.31),
    -0.65 * cos(p.y * 2.3 + time * 0.33) + 0.30 * sin(p.x * 5.3 - time * 0.19)
  );
}

void advance(vec2 uv, out vec3 displacement, out vec3 velocity) {
  vec3 rest = texture2D(uRest, uv).xyz;
  vec3 oldDisplacement = texture2D(textureDisplacement, uv).xyz;
  vec3 oldVelocity = texture2D(textureVelocity, uv).xyz;
  vec4 clip = uViewProjection * uModel * vec4(rest + oldDisplacement, 1.0);
  vec2 screen = clip.xy / max(clip.w, 0.0001) * 0.5 + 0.5;
  float visible = step(0.001, clip.w) * step(0.0, screen.x) * step(screen.x, 1.0)
    * step(0.0, screen.y) * step(screen.y, 1.0);
  vec2 flow = texture2D(uFluid, clamp(screen, 0.0, 1.0)).xy * visible;
  vec3 worldForce = uCameraRight * flow.x + uCameraUp * flow.y;
  vec3 force = (uInverseModel * vec4(worldForce, 0.0)).xyz * 12.0;
  force += curlField(rest * 1.7, uTime) * 0.22;
  force *= min(1.0, 24.0 / max(length(force), 0.00001));

  // Exact critically damped spring with constant force over this step. No Euler
  // instability or frame-dependent friction; offsets remain separate from visemes.
  const float omega = 7.0;
  vec3 equilibrium = force / (omega * omega);
  vec3 relative = oldDisplacement - equilibrium;
  vec3 tangent = oldVelocity + omega * relative;
  float decay = exp(-omega * uDt);
  displacement = (relative + tangent * uDt) * decay + equilibrium;
  velocity = (oldVelocity - omega * tangent * uDt) * decay;
  float distanceFromRest = length(displacement);
  if (distanceFromRest > 0.24) {
    vec3 outward = displacement / distanceFromRest;
    displacement = outward * 0.24;
    velocity -= outward * max(dot(velocity, outward), 0.0);
  }
  velocity *= min(1.0, 1.4 / max(length(velocity), 0.00001));
}
`;

export const DISPLACEMENT_STEP = `${ADVANCE}
void main() {
  vec2 uv = gl_FragCoord.xy / resolution.xy;
  vec3 displacement, velocity;
  advance(uv, displacement, velocity);
  gl_FragColor = vec4(displacement, 1.0);
}
`;

export const VELOCITY_STEP = `${ADVANCE}
void main() {
  vec2 uv = gl_FragCoord.xy / resolution.xy;
  vec3 displacement, velocity;
  advance(uv, displacement, velocity);
  float speed = mix(texture2D(textureVelocity, uv).w, length(velocity), 1.0 - exp(-12.0 * uDt));
  gl_FragColor = vec4(velocity, speed);
}
`;
