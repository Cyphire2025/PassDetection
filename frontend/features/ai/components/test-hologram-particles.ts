import { HEAD_MORPHS, type HumanHeadGeometry } from "./human-head-geometry";
import { eyeRegions } from "./test-hologram-eyes";
import { boundaryAttribute, createHeadVolume } from "./test-hologram-volume";
import { fillHeadSurface } from "./test-hologram-surface-sampling";

export const HEAD_ATTRIBUTES = ["position", "normal", ...HEAD_MORPHS.map((key) => `${key}Shape`), "eyeRegion", "surfaceDetail"] as const;

export function meshAttributes(mesh: HumanHeadGeometry & { surfaceDetail?: Float32Array }): Float32Array[] {
  return [mesh.positions, mesh.normals, ...HEAD_MORPHS.map((key) => mesh.morphs[key]), eyeRegions(mesh),
    mesh.surfaceDetail ?? new Float32Array(mesh.positions.length)];
}

/** Detailed surface plus true interior grains, within the same fixed GPU budget. */
export function sampleHead(mesh: HumanHeadGeometry, count: number): Float32Array[] {
  if (!Number.isInteger(count) || count < 1) throw new Error("Invalid head particle count");
  const source = meshAttributes(mesh);
  const result = source.map(() => new Float32Array(count * 3));
  let seed = 941;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const surfaceCount = Math.ceil(count * .60);
  fillHeadSurface(mesh, source, result, surfaceCount, random);
  const volume = createHeadVolume(mesh), bounds = volume.bounds;
  let point = surfaceCount, attempts = 0;
  while (point < count && attempts++ < count * 40) {
    const x = bounds.minX + random() * (bounds.maxX - bounds.minX), y = bounds.minY + random() * (bounds.maxY - bounds.minY);
    const intervals = volume.intervals(x, y);
    const thickness = intervals.reduce((total, interval) => total + interval.front.z - interval.back.z, 0);
    if (random() * (bounds.maxZ - bounds.minZ) >= thickness) continue;
    // Stratify depth through the union, keeping all eight layers represented.
    let depth = ((point - surfaceCount) % 8 + random()) / 8 * thickness;
    const interval = intervals.find(({ back, front }) => { if (depth <= front.z - back.z) return true; depth -= front.z - back.z; return false; });
    if (!interval) continue;
    const t = .025 + .95 * depth / (interval.front.z - interval.back.z), offset = point * 3;
    for (let attribute = 0; attribute < source.length; attribute++) for (let axis = 0; axis < 3; axis++) {
      const back = boundaryAttribute(mesh, source[attribute], interval.back, axis), front = boundaryAttribute(mesh, source[attribute], interval.front, axis);
      result[attribute][offset + axis] = attribute === 1 ? (t < .5 ? back : front) : back * (1 - t) + front * t;
    }
    result[0].set([x, y, interval.back.z * (1 - t) + interval.front.z * t], offset);
    result[HEAD_ATTRIBUTES.indexOf("eyeRegion")].fill(0, offset, offset + 3);
    result[HEAD_ATTRIBUTES.indexOf("surfaceDetail")][offset + 2] = 2 * Math.min(t, 1 - t);
    point++;
  }
  if (point < count) throw new Error("Head geometry does not contain enough closed volume");
  for (let offset = 0; offset < count * 3; offset += 3) {
    const length = Math.hypot(result[1][offset], result[1][offset + 1], result[1][offset + 2]) || 1;
    for (let axis = 0; axis < 3; axis++) result[1][offset + axis] /= length;
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
