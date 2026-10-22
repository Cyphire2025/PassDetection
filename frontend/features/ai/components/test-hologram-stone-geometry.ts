import { LatheGeometry, Vector2 } from "three";

export const STONE_EDGE_CHIP = .004;

/** Radial cap subdivisions and chipped shoulders give the stone actual relief. */
export function pedestalDiscGeometry(buriedBase = false) {
  const profile = [[0, -.5], [.970, -.5], [.984, -.47], [.995, -.36], [1, -.20], [1, .20], [.995, .36], [.984, .47], [.970, .5]];
  for (let ring = 19; ring >= 0; ring--) profile.push([ring / 20 * .970, .5]);
  const geometry = new LatheGeometry(profile.map(([radius, y]) => new Vector2(radius, buriedBase && y < 0 ? y - .8 : y)), 160);
  const position = geometry.getAttribute("position");
  for (let index = 0; index < position.count; index++) {
    const x = position.getX(index), z = position.getZ(index), y = position.getY(index), radius = Math.hypot(x, z);
    const angle = Math.atan2(x, z);
    if (radius > .97) {
      const chip = STONE_EDGE_CHIP * Math.pow(.5 + .5 * Math.sin(angle * 29 + Math.sin(angle * 7) * 1.7), 2);
      position.setX(index, x * (1 - chip)); position.setZ(index, z * (1 - chip));
    }
    if (y >= .47) {
      const relief = Math.sin(x * 31 + Math.cos(z * 17)) * Math.sin(z * 27 + Math.cos(x * 13)) * .038;
      position.setY(index, y + relief * Math.min(1, radius * 8));
    }
  }
  position.needsUpdate = true; geometry.computeVertexNormals(); geometry.computeBoundingBox(); geometry.computeBoundingSphere();
  return geometry;
}
