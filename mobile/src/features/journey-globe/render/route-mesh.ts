import { add, arcPoint, cross, greatCircle, multiply, normalize, type Vec3 } from './globe-math';

const SEGMENTS = 96;
const SIDES = 6;

/** A real 3D tube avoids device-dependent WebGL line widths. */
export function routeTube(origin: Vec3, destination: Vec3): Float32Array {
  const vertices: number[] = [];
  const ring = (t: number): Vec3[] => {
    const center = arcPoint(origin, destination, t);
    const radial = normalize(center);
    const next = arcPoint(origin, destination, Math.min(1, t + 0.001));
    const previous = arcPoint(origin, destination, Math.max(0, t - 0.001));
    const tangent = normalize(add(next, multiply(previous, -1)));
    const side = normalize(cross(tangent, radial));
    const up = normalize(cross(side, tangent));
    return Array.from({ length: SIDES }, (_, index) => {
      const angle = index / SIDES * Math.PI * 2;
      return add(center, add(multiply(side, Math.cos(angle) * 0.006), multiply(up, Math.sin(angle) * 0.006)));
    });
  };
  for (let segment = 0; segment < SEGMENTS; segment += 1) {
    const a = ring(segment / SEGMENTS);
    const b = ring((segment + 1) / SEGMENTS);
    for (let side = 0; side < SIDES; side += 1) {
      const next = (side + 1) % SIDES;
      vertices.push(...a[side]!, ...b[side]!, ...a[next]!, ...a[next]!, ...b[side]!, ...b[next]!);
    }
  }
  return new Float32Array(vertices);
}

/** Two concentric geographic pins with a raised center, visible from oblique angles. */
export function endpointMesh(point: Vec3, radius: number, ringOnly = false): Float32Array {
  const vertices: number[] = [];
  const normal = normalize(point);
  const side = normalize(cross(normal, Math.abs(normal[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]));
  const up = normalize(cross(normal, side));
  const center = multiply(normal, 1.024);
  const at = (angle: number, size: number) => add(center, add(multiply(side, Math.cos(angle) * size), multiply(up, Math.sin(angle) * size)));
  for (let index = 0; index < 32; index += 1) {
    const a = index / 32 * Math.PI * 2;
    const b = (index + 1) / 32 * Math.PI * 2;
    if (ringOnly) {
      vertices.push(...at(a, radius), ...at(b, radius), ...at(a, radius * 0.8));
      vertices.push(...at(b, radius), ...at(b, radius * 0.8), ...at(a, radius * 0.8));
    } else vertices.push(...center, ...at(a, radius), ...at(b, radius));
  }
  return new Float32Array(vertices);
}

const PLANE_TRIANGLES: readonly (readonly [number, number])[] = [
  // Tapered fuselage, swept wings and horizontal stabilizers, in the flight tangent frame.
  [0, 0.12], [-0.013, 0.065], [0.013, 0.065],
  [-0.013, 0.065], [-0.011, -0.065], [0.013, 0.065],
  [0.013, 0.065], [-0.011, -0.065], [0.011, -0.065],
  [-0.011, 0.035], [-0.094, -0.026], [-0.094, -0.045],
  [-0.011, 0.035], [-0.094, -0.045], [-0.011, -0.01],
  [0.011, 0.035], [0.094, -0.026], [0.094, -0.045],
  [0.011, 0.035], [0.094, -0.045], [0.011, -0.01],
  [0, -0.044], [-0.04, -0.08], [-0.04, -0.09],
  [0, -0.044], [-0.04, -0.09], [0, -0.07],
  [0, -0.044], [0.04, -0.08], [0.04, -0.09],
  [0, -0.044], [0.04, -0.09], [0, -0.07],
];

export function planeMesh(origin: Vec3, destination: Vec3, progress: number): Float32Array {
  const center = arcPoint(origin, destination, progress);
  const radial = normalize(center);
  const after = greatCircle(origin, destination, Math.min(1, progress + 0.001));
  const before = greatCircle(origin, destination, Math.max(0, progress - 0.001));
  const forward = normalize(add(after, multiply(before, -1)));
  const side = normalize(cross(forward, radial));
  const raised = add(center, multiply(radial, 0.022));
  return new Float32Array(PLANE_TRIANGLES.flatMap(([x, y]) =>
    add(raised, add(multiply(side, x), multiply(forward, y)))));
}
