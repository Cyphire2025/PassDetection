import type { HumanHeadGeometry } from "./human-head-geometry";
import { CORNEA_APERTURE, eyeRegions } from "./test-hologram-eyes";

export type HeadBoundary = { triangle: number; weights: [number, number, number]; z: number; crossing: number };
export type HeadInterval = { back: HeadBoundary; front: HeadBoundary };

// Half-open projected triangles count a shared edge once, but still count each
// overlapping closed component independently (including coplanar boundaries).
function ownsEdge(p: Float32Array, a: number, b: number, orientation: number): boolean {
  const dx = (p[b] - p[a]) * orientation, dy = (p[b + 1] - p[a + 1]) * orientation;
  return dy > 0 || dy === 0 && dx < 0;
}

/** Subtract only the clear optical chamber, bounded by actual iris/cornea hits. */
function withoutCornea(mesh: HumanHeadGeometry, regions: Float32Array, hits: HeadBoundary[], intervals: HeadInterval[]): HeadInterval[] {
  const kind = (hit: HeadBoundary) => regions[mesh.triangles[hit.triangle] * 3 + 2];
  for (const cornea of hits) {
    if (kind(cornea) !== 2 || cornea.crossing >= 0) continue;
    const x = boundaryAttribute(mesh, regions, cornea, 0), y = boundaryAttribute(mesh, regions, cornea, 1);
    if (Math.hypot(x, y) >= CORNEA_APERTURE) continue;
    let iris: HeadBoundary | undefined;
    for (const hit of hits) if (kind(hit) === 1 && hit.z < cornea.z) iris = hit;
    if (!iris) continue;
    const clipped: HeadInterval[] = [];
    for (const interval of intervals) {
      if (interval.front.z <= iris.z || interval.back.z >= cornea.z) { clipped.push(interval); continue; }
      if (interval.back.z < iris.z - .000001) clipped.push({ back: interval.back, front: iris });
      if (interval.front.z > cornea.z + .000001) clipped.push({ back: cornea, front: interval.front });
    }
    intervals = clipped;
  }
  return intervals;
}

/** XY bins accelerate signed Z scanlines through the actual authored solid. */
export function createHeadVolume(mesh: HumanHeadGeometry) {
  const p = mesh.positions, indices = mesh.triangles, regions = eyeRegions(mesh), side = 64;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for (let i = 0; i < p.length; i += 3) {
    minX = Math.min(minX, p[i]); maxX = Math.max(maxX, p[i]); minY = Math.min(minY, p[i + 1]); maxY = Math.max(maxY, p[i + 1]);
    minZ = Math.min(minZ, p[i + 2]); maxZ = Math.max(maxZ, p[i + 2]);
  }
  const xCell = (x: number) => Math.max(0, Math.min(side - 1, Math.floor((x - minX) / Math.max(maxX - minX, .00001) * side)));
  const yCell = (y: number) => Math.max(0, Math.min(side - 1, Math.floor((y - minY) / Math.max(maxY - minY, .00001) * side)));
  const bins: number[][] = Array.from({ length: side * side }, () => []);
  for (let face = 0; face < indices.length; face += 3) {
    const a = indices[face] * 3, b = indices[face + 1] * 3, c = indices[face + 2] * 3;
    const left = xCell(Math.min(p[a], p[b], p[c])), right = xCell(Math.max(p[a], p[b], p[c]));
    const bottom = yCell(Math.min(p[a + 1], p[b + 1], p[c + 1])), top = yCell(Math.max(p[a + 1], p[b + 1], p[c + 1]));
    for (let row = bottom; row <= top; row++) for (let column = left; column <= right; column++) bins[row * side + column].push(face);
  }
  return {
    bounds: { minX, maxX, minY, maxY, minZ, maxZ },
    intervals(x: number, y: number): HeadInterval[] {
      if (x < minX || x > maxX || y < minY || y > maxY) return [];
      const hits: HeadBoundary[] = [];
      for (const triangle of bins[yCell(y) * side + xCell(x)]) {
        const a = indices[triangle] * 3, b = indices[triangle + 1] * 3, c = indices[triangle + 2] * 3;
        const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], vx = p[c] - p[a], vy = p[c + 1] - p[a + 1];
        const determinant = ux * vy - uy * vx;
        if (Math.abs(determinant) < 1e-12) continue;
        const dx = x - p[a], dy = y - p[a + 1];
        const w1 = (dx * vy - dy * vx) / determinant, w2 = (ux * dy - uy * dx) / determinant, w0 = 1 - w1 - w2;
        if (Math.min(w0, w1, w2) < -1e-8) continue;
        const orientation = Math.sign(determinant);
        if (Math.abs(w0) < 1e-8 && !ownsEdge(p, b, c, orientation)
          || Math.abs(w1) < 1e-8 && !ownsEdge(p, c, a, orientation)
          || Math.abs(w2) < 1e-8 && !ownsEdge(p, a, b, orientation)) continue;
        hits.push({ triangle, weights: [w0, w1, w2], z: p[a + 2] * w0 + p[b + 2] * w1 + p[c + 2] * w2, crossing: determinant < 0 ? 1 : -1 });
      }
      hits.sort((a, b) => a.z - b.z);
      const intervals: HeadInterval[] = [];
      let winding = 0, back: HeadBoundary | undefined;
      for (let index = 0; index < hits.length;) {
        const boundary = hits[index], before = winding;
        do { winding += hits[index].crossing; index++; }
        while (index < hits.length && Math.abs(hits[index].z - boundary.z) < 1e-7);
        if (before <= 0 && winding > 0) back = boundary;
        if (before > 0 && winding <= 0 && back) {
          if (boundary.z - back.z > .008) intervals.push({ back, front: boundary });
          back = undefined;
        }
      }
      return withoutCornea(mesh, regions, hits, intervals);
    },
  };
}

export function boundaryAttribute(mesh: HumanHeadGeometry, values: Float32Array, boundary: HeadBoundary, axis: number): number {
  let value = 0;
  for (let corner = 0; corner < 3; corner++) value += values[mesh.triangles[boundary.triangle + corner] * 3 + axis] * boundary.weights[corner];
  return value;
}
