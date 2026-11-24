import { CatmullRomCurve3, CubicBezierCurve3, Ray, Triangle, Vector3 } from "three";
import type { HumanHeadGeometry } from "./human-head-geometry";

type Point = [number, number, number];
const ease = (value: number) => { const t = Math.max(0, Math.min(1, value)); return t * t * (3 - 2 * t); };

/** Projects a groom onto the actual scalp, not an enclosing ellipsoid. */
function scalpProjector(source: HumanHeadGeometry) {
  const origin = new Vector3(0, .32, -.08), ray = new Ray();
  const a = new Vector3(), b = new Vector3(), c = new Vector3(), hit = new Vector3();
  const selected = new Vector3(), barycentric = new Vector3(), direction = new Vector3();
  const faces: number[] = [];
  for (let i = 0; i < source.triangles.length; i += 3) {
    if ([0, 1, 2].some((corner) => source.positions[source.triangles[i + corner] * 3 + 1] > .22)) faces.push(i);
  }
  return (guide: Vector3) => {
    direction.subVectors(guide, origin).normalize(); ray.set(origin, direction);
    let best = -1, distance = 0;
    for (const face of faces) {
      a.fromArray(source.positions, source.triangles[face] * 3);
      b.fromArray(source.positions, source.triangles[face + 1] * 3);
      c.fromArray(source.positions, source.triangles[face + 2] * 3);
      if (!ray.intersectTriangle(a, b, c, false, hit)) continue;
      const squared = hit.distanceToSquared(origin);
      if (squared <= distance || hit.y < .20 || (hit.z > .30 && hit.y < .38 && Math.abs(hit.x) < .43)) continue;
      distance = squared; best = face; selected.copy(hit);
    }
    if (best < 0) throw new Error(`Swept hair guide left the authored scalp: ${guide.toArray().join(",")}`);
    a.fromArray(source.positions, source.triangles[best] * 3);
    b.fromArray(source.positions, source.triangles[best + 1] * 3);
    c.fromArray(source.positions, source.triangles[best + 2] * 3);
    Triangle.getBarycoord(selected, a, b, c, barycentric);
    const normal = new Vector3();
    for (let i = 0; i < 3; i++) {
      a.fromArray(source.normals, source.triangles[best + i] * 3);
      normal.addScaledVector(a, barycentric.getComponent(i));
    }
    return { position: selected.clone(), normal: normal.normalize() };
  };
}

/** Closed tapered ribbons form soft, overlapping 3D waves on both sides of a part. */
export function appendSweptLocks(source: HumanHeadGeometry, positions: number[], normals: number[], triangles: number[], detail?: number[], appearance: "female" | "male" = "female"): number {
  const before = positions.length / 3, project = scalpProjector(source);
  const segments = 24, sides = 8;
  const volume = appearance === "female" ? 1 : .82;
  const append = (controls: Point[], index: number, width: number, lift: number) => {
    const guides = controls.map((point) => new Vector3(...point));
    const curve = guides.length === 4 ? new CubicBezierCurve3(...guides as [Vector3, Vector3, Vector3, Vector3])
      : new CatmullRomCurve3(guides, false, "centripetal");
    const centers: Vector3[] = [], outward: Vector3[] = [];
    for (let segment = 0; segment <= segments; segment++) {
      const t = segment / segments, scalp = project(curve.getPoint(t));
      const envelope = Math.sin(Math.PI * t);
      const wave = Math.sin(t * Math.PI * 3.4 + index * .73) * .006 * envelope;
      centers.push(scalp.position.addScaledVector(scalp.normal, .008 + envelope * lift + wave));
      outward.push(scalp.normal);
    }
    const start = positions.length / 3;
    for (let segment = 0; segment <= segments; segment++) {
      const t = segment / segments, tangent = centers[Math.min(segments, segment + 1)].clone().sub(centers[Math.max(0, segment - 1)]).normalize();
      const across = new Vector3().crossVectors(tangent, outward[segment]).normalize();
      const up = new Vector3().crossVectors(across, tangent).normalize();
      const taper = .16 + .84 * ease(t / .11) * (1 - ease((t - .79) / .21));
      const halfWidth = width * taper, depth = width * .45 * taper;
      for (let side = 0; side < sides; side++) {
        const angle = side / sides * Math.PI * 2, cosine = Math.cos(angle), sine = Math.sin(angle);
        const point = centers[segment].clone().addScaledVector(across, cosine * halfWidth).addScaledVector(up, sine * depth);
        const normal = across.clone().multiplyScalar(cosine / halfWidth).addScaledVector(up, sine / depth).normalize();
        positions.push(point.x, point.y, point.z); normals.push(normal.x, normal.y, normal.z);
        // The scalp blocks ambient light beneath each rounded lock; its outward
        // crest remains exposed. This static signal follows the actual geometry.
        detail?.push(1, .08 + .65 * (1 - Math.max(0, normal.dot(outward[segment]))), 0);
      }
    }
    if (positions.length / 3 >= 65_536) throw new Error("Swept hair exceeds the head geometry budget.");
    for (let segment = 0; segment < segments; segment++) for (let side = 0; side < sides; side++) {
      const a = start + segment * sides + side, b = start + segment * sides + (side + 1) % sides;
      triangles.push(a, a + sides, b, b, a + sides, b + sides);
    }
    for (let side = 1; side < sides - 1; side++) {
      triangles.push(start, start + side, start + side + 1);
      const end = start + segments * sides; triangles.push(end, end + side + 1, end + side);
    }
  };
  for (let strand = 0; strand < 22; strand++) {
    const z = .54 - strand * .047;
    append([[-.17, .86, z], [.10, .94, z + .06], [.62, .68, z - .02], [.60, .35, z - .09]], strand, .018 + strand % 3 * .0025, (.035 + Math.sin(strand * .63) * .005) * volume);
  }
  for (let strand = 0; strand < 14; strand++) {
    const z = .53 - strand * .072;
    append([[-.20, .86, z], [-.47, .90, z + .04], [-.67, .61, z - .04], [-.60, .34, z - .12]], strand + 23, .018 + strand % 2 * .002, .028 * volume);
  }
  for (let strand = 0; strand < 9; strand++) {
    const x = -.40 + strand * .10;
    append([[x, .84, -.35], [x + .045, .79, -.65], [x - .035, .47, -.79], [x, .24, -.75]], strand + 39, .025, .022 * volume);
  }
  // Low side-parted forelocks follow the scalp into the temples instead of
  // stacking lifted curls above the forehead into a quiff.
  for (let layer = 0; layer < 5; layer++) {
    const t = layer / 4;
    append([[.20 - t * .06, .75 + t * .18, .49 - t * .12], [-t * .04, .80 + t * .17, .64 - t * .14],
      [-.24 - t * .05, .72 + t * .17, .70 - t * .15], [-.48 - t * .03, .51 + t * .18, .58 - t * .13],
      [-.58, .33 + t * .12, .30 - t * .05]], layer + 48, .038 + Math.sin(layer * 1.1) * .004, (.040 + t * .012) * volume);
  }
  for (let layer = 0; layer < 5; layer++) {
    const t = layer / 4;
    append([[-.13, .61 + t * .17, .66 - t * .13], [-.38, .65 + t * .17, .75 - t * .15],
      [-.65, .48 + t * .13, .55 - t * .10], [-.65, .38 + t * .13, .40 - t * .09],
      [-.61, .28 + t * .12, .23 - t * .04]], layer + 56, .035 + t * .004, (.045 + t * .010) * volume);
  }
  return positions.length / 3 - before;
}
