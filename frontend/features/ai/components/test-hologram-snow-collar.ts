import { BufferAttribute, BufferGeometry, Mesh, ShaderMaterial, Vector3, type Texture } from "three";
import { LANDSCAPE_GROUND_FOOTPRINT } from "./test-landscape-layout";
import { createHologramSpill, HOLOGRAM_SPILL, type HologramSpillUniforms } from "./test-hologram-spill";

function powderProfile(x: number, z: number, radius: number) {
  const angle = Math.atan2(x, z), outer = 1.13 + Math.sin(angle * 7) * .035 + Math.sin(angle * 19) * .015;
  const across = (Math.hypot(x, z) / radius - .94) / (outer - .94);
  const t = Math.max(0, Math.min(1, across)), windward = .24 + .20 * (.5 + .5 * Math.sin(angle * 5 + Math.sin(angle * 11)));
  return { across, mound: Math.pow(Math.sin(t * Math.PI), 1.6) * (1 - t) * windward };
}

/** Subdivide authored triangles independently, preserving every UV-chart seam. */
export function snowCollarGeometry(ground: BufferGeometry) {
  const steps = 8, radius = LANDSCAPE_GROUND_FOOTPRINT / 2;
  const positions: number[] = [], normals: number[] = [], uvs: number[] = [], sourceY: number[] = [], across: number[] = [], indices: number[] = [];
  const source = ground.getAttribute("position"), normal = ground.getAttribute("normal"), uv = ground.getAttribute("uv"), triangles = ground.getIndex();
  if (!triangles || !normal || !uv) throw new Error("Powder collar requires textured terrain triangles");
  const points = [new Vector3(), new Vector3(), new Vector3()], point = new Vector3(), n = new Vector3();
  for (let face = 0; face < triangles.count; face += 3) {
    const vertices = [triangles.getX(face), triangles.getX(face + 1), triangles.getX(face + 2)];
    points.forEach((p, index) => p.fromBufferAttribute(source, vertices[index]));
    const minX = Math.min(...points.map((p) => p.x)), maxX = Math.max(...points.map((p) => p.x));
    const minZ = Math.min(...points.map((p) => p.z)), maxZ = Math.max(...points.map((p) => p.z));
    const nearest = Math.hypot(Math.max(minX, Math.min(0, maxX)), Math.max(minZ, Math.min(0, maxZ)));
    if (nearest > radius * 1.18 || Math.max(...points.map((p) => Math.hypot(p.x, p.z))) < radius * .94) continue;
    const rows: number[] = [];
    for (let row = 0; row <= steps; row++) {
      rows.push(positions.length / 3);
      for (let column = 0; column <= steps - row; column++) {
        const weights = [1 - (row + column) / steps, row / steps, column / steps];
        point.set(0, 0, 0); n.set(0, 0, 0); let u = 0, v = 0;
        for (let index = 0; index < 3; index++) {
          point.addScaledVector(points[index], weights[index]); const vertex = vertices[index];
          n.x += normal.getX(vertex) * weights[index]; n.y += normal.getY(vertex) * weights[index]; n.z += normal.getZ(vertex) * weights[index];
          u += uv.getX(vertex) * weights[index]; v += uv.getY(vertex) * weights[index];
        }
        const profile = powderProfile(point.x, point.z, radius), epsilon = .015;
        const dx = (powderProfile(point.x + epsilon, point.z, radius).mound - powderProfile(point.x - epsilon, point.z, radius).mound) / (2 * epsilon);
        const dz = (powderProfile(point.x, point.z + epsilon, radius).mound - powderProfile(point.x, point.z - epsilon, radius).mound) / (2 * epsilon);
        n.x -= dx * n.y; n.z -= dz * n.y; n.normalize();
        positions.push(point.x, point.y + .003 + profile.mound, point.z); normals.push(n.x, n.y, n.z);
        uvs.push(u, v); sourceY.push(point.y); across.push(profile.across);
      }
    }
    for (let row = 0; row < steps; row++) for (let column = 0; column < steps - row; column++) {
      const a = rows[row] + column, b = rows[row + 1] + column, c = a + 1;
      indices.push(a, b, c);
      if (column < steps - row - 1) indices.push(b, b + 1, c);
    }
  }
  if (!positions.length) throw new Error("Powder collar lies outside the original textured ground");
  const geometry = new BufferGeometry().setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
  geometry.setAttribute("normal", new BufferAttribute(new Float32Array(normals), 3));
  geometry.setAttribute("uv", new BufferAttribute(new Float32Array(uvs), 2));
  geometry.setAttribute("sourceY", new BufferAttribute(new Float32Array(sourceY), 1));
  geometry.setAttribute("across", new BufferAttribute(new Float32Array(across), 1));
  geometry.setIndex(indices); geometry.computeBoundingSphere(); return geometry;
}

const VERTEX = `
attribute float sourceY, across;
varying vec2 vUv;
varying vec3 vWorld, vNormal;
varying float vSourceY, vAcross;
void main() {
  vUv = uv; vSourceY = sourceY; vAcross = across; vNormal = normal;
  vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
const FRAGMENT = `
${HOLOGRAM_SPILL}
uniform sampler2D tSnow, tWind;
uniform float opacity, time, hasSnow, hasWind;
varying vec2 vUv;
varying vec3 vWorld, vNormal;
varying float vSourceY, vAcross;
void main() {
  float feather = smoothstep(0.0, .08, vAcross) * (1.0 - smoothstep(.72, 1.0, vAcross));
  if (opacity * feather < .005) discard;
  vec3 snow = mix(vec3(.44, .52, .66), texture2D(tSnow, vUv).rgb, hasSnow);
  // The same authored UVs and wind field make the outer skirt meet the ground.
  vec2 windSpace = vWorld.xz + vec2(vWorld.x, vSourceY);
  float drift = texture2D(tWind, windSpace * .1 - time * vec2(.25, .30)).r;
  drift *= texture2D(tWind, windSpace * .15 - time * vec2(.18, .225)).r;
  drift *= 1.0 - clamp(vSourceY * .5 + .75, 0.0, 1.0);
  snow = min(vec3(1.0), snow + drift * snow.r * .95 * hasWind);
  float mound = clamp((vWorld.y - vSourceY - .003) / .18, 0.0, 1.0);
  float light = max(dot(normalize(vNormal), normalize(vec3(-.6, 1.0, 1.2))), 0.0);
  snow = snow * (1.0 + (light - .6) * mound * .18) + mound * .025;
  snow = hologramSpill(snow, vWorld, vNormal);
  gl_FragColor = vec4(snow, opacity * feather);
}
`;

/** Owns only its powder geometry/material; shared landscape maps stay borrowed. */
export function createSnowCollar(ground: BufferGeometry, snow?: Texture, wind?: Texture, spill: HologramSpillUniforms = createHologramSpill().uniforms) {
  const geometry = snowCollarGeometry(ground);
  const uniforms = { ...spill, opacity: { value: 0 }, time: { value: 0 }, tSnow: { value: snow ?? null }, tWind: { value: wind ?? null }, hasSnow: { value: Number(Boolean(snow)) }, hasWind: { value: Number(Boolean(wind)) } };
  const material = new ShaderMaterial({ name: "Terrain-integrated powder mound", uniforms, vertexShader: VERTEX, fragmentShader: FRAGMENT, transparent: true, depthWrite: true, toneMapped: false });
  const mesh = new Mesh(geometry, material); mesh.name = "Irregular pedestal powder collar"; mesh.renderOrder = 3;
  let disposed = false;
  return {
    mesh,
    update(opacity: number, time: number) {
      if (disposed) return;
      uniforms.opacity.value = Number.isFinite(opacity) ? Math.max(0, Math.min(1, opacity)) : 0;
      uniforms.time.value = Number.isFinite(time) ? time : 0;
    },
    dispose() { if (disposed) return; disposed = true; mesh.removeFromParent(); geometry.dispose(); material.dispose(); },
  };
}
