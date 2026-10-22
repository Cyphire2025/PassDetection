import type { HumanHeadGeometry } from "./human-head-geometry";
import { CORNEA_APERTURE } from "./test-hologram-eyes";

type Region = { faces: number[]; cumulative: number[]; area: number; share: number };

/** Keep skin and authored eyes detailed without letting overlapping hair locks
 * consume most of the surface budget. Every result remains on its source face.
 */
export function fillHeadSurface(mesh: HumanHeadGeometry, source: Float32Array[], output: Float32Array[], count: number, random: () => number): void {
  const p = mesh.positions, indices = mesh.triangles;
  const eyes = source[source.length - 2], detail = source[source.length - 1];
  const regions: Region[] = [.60, .36, .025, .015].map((share) => ({ faces: [], cumulative: [], area: 0, share }));
  const minimum = [Infinity, Infinity, Infinity], maximum = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < p.length; i++) {
    minimum[i % 3] = Math.min(minimum[i % 3], p[i]); maximum[i % 3] = Math.max(maximum[i % 3], p[i]);
  }
  for (let face = 0; face < indices.length; face += 3) {
    const a = indices[face] * 3, b = indices[face + 1] * 3, c = indices[face + 2] * 3;
    const eye = eyes[a + 2];
    // The renderer discards this optically clear chamber. Do not allocate grains
    // to it; triangles crossing its boundary are sampled with the same predicate.
    if (eye > 1.5 && [a, b, c].every((v) => Math.hypot(eyes[v], eyes[v + 1]) < CORNEA_APERTURE)) continue;
    const region = regions[eye > 1.5 ? 3 : eye > .5 ? 2 : (detail[a] + detail[b] + detail[c]) / 3 > .03 ? 1 : 0];
    const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2];
    const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2];
    const area = Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) * .5;
    if (area <= 0) continue;
    region.area += area; region.faces.push(face); region.cumulative.push(region.area);
  }
  const active = regions.filter((region) => region.area > 0), totalShare = active.reduce((sum, region) => sum + region.share, 0);
  if (!active.length) throw new Error("Head geometry has no sampleable surface");
  const quotas = active.map((region) => count * region.share / totalShare), counts = quotas.map(Math.floor);
  const order = quotas.map((value, i) => ({ i, remainder: value - counts[i] })).sort((a, b) => b.remainder - a.remainder);
  for (let left = count - counts.reduce((a, b) => a + b, 0), i = 0; i < left; i++) counts[order[i].i]++;
  let point = 0;
  active.forEach((region, regionIndex) => {
    const quota = counts[regionIndex];
    if (!quota) return;
    // A nominal neighbour spacing gives bounded 27-cell searches. Four candidate
    // draws favour empty patches over clusters, without a quadratic relaxation.
    const cell = Math.sqrt(region.area / quota), cellSquared = cell * cell;
    const strideX = Math.ceil((maximum[0] - minimum[0]) / cell) + 3;
    const strideY = Math.ceil((maximum[1] - minimum[1]) / cell) + 3, strideZ = strideX * strideY;
    const grid = new Map<number, number[]>();
    const keyAt = (x: number, y: number, z: number) => Math.floor((x - minimum[0]) / cell) + 1
      + (Math.floor((y - minimum[1]) / cell) + 1) * strideX + (Math.floor((z - minimum[2]) / cell) + 1) * strideZ;
    const best = new Float64Array(7), candidate = new Float64Array(7);
    for (let local = 0; local < quota; local++, point++) {
      let bestDistance = -1;
      for (let attempt = 0; attempt < 4; attempt++) {
        let valid = false;
        for (let retry = 0; retry < 64 && !valid; retry++) {
          const target = random() * region.area;
          let low = 0, high = region.faces.length - 1;
          while (low < high) { const middle = (low + high) >>> 1; if (region.cumulative[middle] < target) low = middle + 1; else high = middle; }
          const face = region.faces[low], a = indices[face] * 3, b = indices[face + 1] * 3, c = indices[face + 2] * 3;
          const u = Math.sqrt(random()), v = random(), w0 = 1 - u, w1 = u * (1 - v), w2 = u * v;
          const eyeX = eyes[a] * w0 + eyes[b] * w1 + eyes[c] * w2, eyeY = eyes[a + 1] * w0 + eyes[b + 1] * w1 + eyes[c + 1] * w2;
          if (eyes[a + 2] > 1.5 && Math.hypot(eyeX, eyeY) < CORNEA_APERTURE) continue;
          candidate.set([face, w0, w1, w2]);
          for (let axis = 0; axis < 3; axis++) candidate[axis + 4] = p[a + axis] * w0 + p[b + axis] * w1 + p[c + axis] * w2;
          valid = true;
        }
        if (!valid) throw new Error("Unable to sample the visible eye surface");
        const x = candidate[4], y = candidate[5], z = candidate[6], key = keyAt(x, y, z);
        let distance = cellSquared;
        for (let dz = -1; dz <= 1; dz++) for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const neighbours = grid.get(key + dx + dy * strideX + dz * strideZ);
          if (neighbours) for (const previous of neighbours) {
            const offset = previous * 3;
            distance = Math.min(distance, (x - output[0][offset]) ** 2 + (y - output[0][offset + 1]) ** 2 + (z - output[0][offset + 2]) ** 2);
          }
        }
        if (distance > bestDistance) { bestDistance = distance; best.set(candidate); }
        if (distance >= cellSquared) break;
      }
      const face = best[0], a = indices[face] * 3, b = indices[face + 1] * 3, c = indices[face + 2] * 3;
      for (let attribute = 0; attribute < source.length; attribute++) for (let axis = 0; axis < 3; axis++) {
        output[attribute][point * 3 + axis] = source[attribute][a + axis] * best[1] + source[attribute][b + axis] * best[2] + source[attribute][c + axis] * best[3];
      }
      const key = keyAt(best[4], best[5], best[6]), bucket = grid.get(key);
      if (bucket) bucket.push(point); else grid.set(key, [point]);
    }
  });
}
