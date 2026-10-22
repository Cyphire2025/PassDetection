import { HEAD_MORPHS, type HumanHeadGeometry } from "./human-head-geometry";
import { appendSweptLocks } from "./test-hologram-hair-locks";

const smooth = (low: number, high: number, value: number) => {
  const t = Math.max(0, Math.min(1, (value - low) / (high - low)));
  return t * t * (3 - 2 * t);
};

/** Forehead, temples and nape are separate from the eyes, ears and lower face. */
function scalpWeight(x: number, y: number, z: number) {
  const front = smooth(-.12, .42, z);
  const hairline = .22 + .32 * front - .08 * smooth(.05, .5, -z);
  return smooth(hairline, hairline + .085, y) * (1 - smooth(.48, .60, Math.abs(x)) * (1 - smooth(.27, .38, y)));
}

function heightAt(x: number, y: number, z: number) {
  const weight = scalpWeight(x, y, z), crown = smooth(.40, .87, y);
  const part = Math.exp(-Math.pow((x + .17 - z * .15) / .037, 2));
  return weight * (.008 + crown * .014 - part * crown * .010);
}

/** One-time, bounded scalp refinement. No asset, random state or runtime groom. */
export function styleHeadHair(source: HumanHeadGeometry, appearance: "female" | "male" = "female"): HumanHeadGeometry & { surfaceDetail: Float32Array } {
  const positions = Array.from(source.positions), normals = Array.from(source.normals);
  const detail = Array.from({ length: source.positions.length }, () => 0);
  const morphs = HEAD_MORPHS.map((key) => Array.from(source.morphs[key]));
  const triangles: number[] = [];
  const point = (index: number, axis: number) => source.positions[index * 3 + axis];
  const weight = (index: number) => scalpWeight(point(index, 0), point(index, 1), point(index, 2));
  const cuts = 4;
  for (let triangle = 0; triangle < source.triangles.length; triangle += 3) {
    const corners = Array.from(source.triangles.subarray(triangle, triangle + 3));
    if (!corners.some((index) => weight(index) > 0)) { triangles.push(...corners); continue; }
    const rows: number[][] = [];
    for (let row = 0; row <= cuts; row++) {
      rows[row] = [];
      for (let column = 0; column <= cuts - row; column++) {
        const blend = [1 - (row + column) / cuts, column / cuts, row / cuts];
        const vertex = positions.length / 3;
        if (vertex >= 65_536) throw new Error("Short hair exceeds the head geometry budget.");
        rows[row].push(vertex);
        const p = [0, 0, 0], n = [0, 0, 0];
        for (let axis = 0; axis < 3; axis++) for (let i = 0; i < 3; i++) {
          p[axis] += point(corners[i], axis) * blend[i];
          n[axis] += source.normals[corners[i] * 3 + axis] * blend[i];
        }
        const length = Math.hypot(...n) || 1;
        for (let axis = 0; axis < 3; axis++) n[axis] /= length;
        const height = heightAt(...p as [number, number, number]);
        // A quiet cap closes the gaps beneath the separately sculpted swept locks.
        const gradient = [0, 1, 2].map((axis) => {
          const plus = [...p], minus = [...p]; plus[axis] += .001; minus[axis] -= .001;
          return (heightAt(...plus as [number, number, number]) - heightAt(...minus as [number, number, number])) / .002;
        });
        const normalGradient = gradient.reduce((sum, value, axis) => sum + value * n[axis], 0);
        const normal = n.map((value, axis) => value - (gradient[axis] - value * normalGradient));
        const normalLength = Math.hypot(...normal) || 1;
        for (let axis = 0; axis < 3; axis++) {
          positions.push(p[axis] + n[axis] * height);
          normals.push(normal[axis] / normalLength);
        }
        const scalp = scalpWeight(...p as [number, number, number]);
        detail.push(scalp, scalp * .65, 0);
        for (let morph = 0; morph < HEAD_MORPHS.length; morph++) for (let axis = 0; axis < 3; axis++) {
          morphs[morph].push(corners.reduce((sum, index, i) => sum + source.morphs[HEAD_MORPHS[morph]][index * 3 + axis] * blend[i], 0));
        }
      }
    }
    for (let row = 0; row < cuts; row++) for (let column = 0; column < cuts - row; column++) {
      triangles.push(rows[row][column], rows[row][column + 1], rows[row + 1][column]);
      if (column < cuts - row - 1) triangles.push(rows[row][column + 1], rows[row + 1][column + 1], rows[row + 1][column]);
    }
  }
  const lockVertices = appendSweptLocks(source, positions, normals, triangles, detail, appearance);
  for (const morph of morphs) for (let i = 0; i < lockVertices * 3; i++) morph.push(0);
  const edges: number[] = [], seen = new Set<string>();
  for (let index = 0; index < triangles.length; index += 3) for (let side = 0; side < 3; side++) {
    const a = triangles[index + side], b = triangles[index + (side + 1) % 3];
    const key = `${Math.min(a, b)}:${Math.max(a, b)}`;
    if (!seen.has(key)) { seen.add(key); edges.push(a, b); }
  }
  return { positions: Float32Array.from(positions), normals: Float32Array.from(normals),
    surfaceDetail: Float32Array.from(detail),
    triangles: Uint16Array.from(triangles), edges: Uint16Array.from(edges),
    morphs: Object.fromEntries(HEAD_MORPHS.map((key, index) => [key, Float32Array.from(morphs[index])])) as HumanHeadGeometry["morphs"] };
}

export const createShortHairHead = styleHeadHair;
