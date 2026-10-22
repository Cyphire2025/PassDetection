import { CONTAINMENT } from "./test-hologram-platform";
import { PLATFORM_HORIZONTAL_SCALE } from "./test-landscape-layout";

/** The physical cage is fixed in sculpture space, independently of head turns. */
export const PARTICLE_CONTAINMENT = `
uniform mat4 headToEnclosure, enclosureToHead;
vec3 confineHead(vec3 point, float margin) {
  vec3 enclosed = (headToEnclosure * vec4(point, 1.0)).xyz;
  float radius = max(.01, ${CONTAINMENT.radius * PLATFORM_HORIZONTAL_SCALE} - margin);
  float radial = length(enclosed.xz);
  enclosed.xz *= min(1.0, radius / max(radial, .00001));
  enclosed.y = clamp(enclosed.y, ${CONTAINMENT.bottom} + margin, ${CONTAINMENT.top} - margin);
  return (enclosureToHead * vec4(enclosed, 1.0)).xyz;
}
`;
