/** Spatial fields use canonical adult-head coordinates, before world/head transforms. */
export const HEAD_FIELD_GLSL = `
precision highp sampler3D;
uniform sampler3D sdfVolume;
uniform sampler3D sdfJaw;
uniform sampler3D sdfRound;
uniform sampler3D sdfWide;
uniform sampler3D sdfClosure;
uniform sampler3D sdfFricative;
uniform sampler3D sdfBlink;
uniform sampler3D sdfEyes;
uniform sampler3D sdfDetail;
uniform vec3 sdfMin;
uniform vec3 sdfSize;

vec3 headFieldUV(vec3 canonical) { return clamp((canonical - sdfMin) / sdfSize, 0.0, 1.0); }
vec4 headField(vec3 canonical) {
  vec3 uv = headFieldUV(canonical);
  vec4 field = texture(sdfVolume, uv);
  // Extend the clamped volume outward, so a displaced particle still has a
  // finite inward recovery direction beyond the finite texture bounds.
  vec3 outside = canonical - clamp(canonical, sdfMin, sdfMin + sdfSize);
  float distanceOutside = length(outside);
  if (distanceOutside > .00001) return vec4(outside / distanceOutside, max(0.0, field.a) + distanceOutside);
  float magnitude = length(field.rgb);
  return vec4(magnitude > .00001 ? field.rgb / magnitude : vec3(0.0, 1.0, 0.0), field.a);
}
vec3 headSurfaceNormal(vec3 canonical) {
  vec3 uv = headFieldUV(canonical);
  vec3 normal = vec3(texture(sdfJaw, uv).a, texture(sdfRound, uv).a, texture(sdfWide, uv).a);
  return normal / max(length(normal), .00001);
}
vec3 headEyeRegion(vec3 canonical) { return texture(sdfEyes, headFieldUV(canonical)).rgb; }
vec3 headSurfaceDetail(vec3 canonical) { return texture(sdfDetail, headFieldUV(canonical)).rgb; }
vec3 headMorph(vec3 canonical, float jaw, float roundness, float wide, float closure, float fricative, float blink) {
  vec3 uv = headFieldUV(canonical);
  return texture(sdfJaw, uv).rgb * jaw + texture(sdfRound, uv).rgb * roundness
    + texture(sdfWide, uv).rgb * wide + texture(sdfClosure, uv).rgb * closure
    + texture(sdfFricative, uv).rgb * fricative + texture(sdfBlink, uv).rgb * blink;
}
`;
