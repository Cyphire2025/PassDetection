import { HEAD_MORPHS, type HumanHeadGeometry } from "./human-head-geometry";

export const HEAD_ATTRIBUTES = ["position", "normal", ...HEAD_MORPHS.map((key) => `${key}Shape`)] as const;

export function meshAttributes(mesh: HumanHeadGeometry): Float32Array[] {
  return [mesh.positions, mesh.normals, ...HEAD_MORPHS.map((key) => mesh.morphs[key])];
}

/** Area-weighted, deterministic sampling preserves every authored facial morph. */
export function sampleHead(mesh: HumanHeadGeometry, count: number): Float32Array[] {
  const source = meshAttributes(mesh);
  const result = source.map(() => new Float32Array(count * 3));
  const areas = new Float32Array(mesh.triangles.length / 3);
  let area = 0, seed = 941;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  for (let face = 0; face < areas.length; face++) {
    const a = mesh.triangles[face * 3] * 3, b = mesh.triangles[face * 3 + 1] * 3, c = mesh.triangles[face * 3 + 2] * 3;
    const p = mesh.positions;
    const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2];
    const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2];
    area += Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx);
    areas[face] = area;
  }
  for (let point = 0; point < count; point++) {
    const target = random() * area;
    let low = 0, high = areas.length - 1;
    while (low < high) { const middle = (low + high) >>> 1; if (areas[middle] < target) low = middle + 1; else high = middle; }
    const a = mesh.triangles[low * 3] * 3, b = mesh.triangles[low * 3 + 1] * 3, c = mesh.triangles[low * 3 + 2] * 3;
    const u = Math.sqrt(random()), v = random(), w0 = 1 - u, w1 = u * (1 - v), w2 = u * v;
    for (let attribute = 0; attribute < source.length; attribute++) {
      const values = source[attribute], output = result[attribute];
      for (let axis = 0; axis < 3; axis++) output[point * 3 + axis] = values[a + axis] * w0 + values[b + axis] * w1 + values[c + axis] * w2;
    }
  }
  return result;
}

/** An original faceted ovoid enclosure, independent of head rotation. */
export function containmentLines(): Float32Array {
  const vertices: number[] = [];
  const rings = 28, segments = 48;
  const at = (ring: number, segment: number) => {
    const latitude = Math.PI * (.07 + .86 * ring / rings), angle = Math.PI * 2 * (segment + ring * .5) / segments;
    return [Math.sin(latitude) * Math.cos(angle) * 1.13, Math.cos(latitude) * 1.25, Math.sin(latitude) * Math.sin(angle) * 1.04];
  };
  for (let ring = 0; ring < rings; ring++) for (let segment = 0; segment < segments; segment++) {
    vertices.push(...at(ring, segment), ...at(ring, segment + 1), ...at(ring, segment), ...at(ring + 1, segment), ...at(ring, segment), ...at(ring + 1, segment - 1));
  }
  return new Float32Array(vertices);
}
