import type { HumanHeadGeometry } from "./human-head-geometry";

const cache = new WeakMap<HumanHeadGeometry, Float32Array>();
// The authored iris lies behind a separate corneal shell. That shell is clear
// across the iris; its surrounding sclera still participates in depth testing.
export const CORNEA_APERTURE = .67;
export const IRIS_EXPANSION = .009;

/** Label the authored eye components, never draw eye markings on the face mesh. */
export function eyeRegions(mesh: HumanHeadGeometry): Float32Array {
  const cached = cache.get(mesh);
  if (cached) return cached;
  const count = mesh.positions.length / 3, parents = Uint16Array.from({ length: count }, (_, i) => i);
  const root = (vertex: number) => {
    while (parents[vertex] !== vertex) { parents[vertex] = parents[parents[vertex]]; vertex = parents[vertex]; }
    return vertex;
  };
  for (let i = 0; i < mesh.triangles.length; i += 3) {
    const a = root(mesh.triangles[i]);
    parents[root(mesh.triangles[i + 1])] = a; parents[root(mesh.triangles[i + 2])] = a;
  }
  const components = new Map<number, number[]>();
  for (let vertex = 0; vertex < count; vertex++) {
    const key = root(vertex), component = components.get(key);
    if (component) component.push(vertex); else components.set(key, [vertex]);
  }
  const result = new Float32Array(mesh.positions.length);
  for (const vertices of components.values()) {
    if (vertices.length < 100 || vertices.length > 800) continue;
    const minimum = [Infinity, Infinity, Infinity], maximum = [-Infinity, -Infinity, -Infinity];
    for (const vertex of vertices) for (let axis = 0; axis < 3; axis++) {
      const value = mesh.positions[vertex * 3 + axis];
      minimum[axis] = Math.min(minimum[axis], value); maximum[axis] = Math.max(maximum[axis], value);
    }
    const center = minimum.map((value, axis) => (value + maximum[axis]) / 2);
    const span = minimum.map((value, axis) => maximum[axis] - value);
    // Both reviewed appearances share this topology. Bounds distinguish the
    // small, flat iris discs from spherical eyes and all disconnected hair locks.
    if (Math.abs(center[0]) < .15 || Math.abs(center[0]) > .35 || center[1] < .08
      || center[1] > .30 || center[2] < .30 || center[2] > .60) continue;
    const iris = span[0] > .07 && span[0] < .13 && span[1] > .07 && span[1] < .13 && span[2] < .025;
    const eyeball = span.every((value) => value > .14 && value < .23);
    if (!iris && !eyeball) continue;
    for (const vertex of vertices) {
      result[vertex * 3] = (mesh.positions[vertex * 3] - center[0]) / (span[0] / 2);
      result[vertex * 3 + 1] = (mesh.positions[vertex * 3 + 1] - center[1]) / (span[1] / 2);
      result[vertex * 3 + 2] = iris ? 1 : 2;
    }
  }
  cache.set(mesh, result);
  return result;
}
