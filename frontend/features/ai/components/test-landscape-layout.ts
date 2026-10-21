import { Quaternion, Vector3, type Object3D, type PerspectiveCamera } from "three";

export type Placement = [position: number[], scale: number[], degrees: number[], order?: number];
export const LANDSCAPE_POSITION = [-14, 4, 14] as const;
export const LANDSCAPE_TARGET = [0, 2.5, 0] as const;
export const LANDSCAPE_PITCH_LIMIT = .35;
// Inset inside the original patch's UV island, away from the atlas's black voids.
export const SNOW_ISLAND = [.065, .410, .245, .590] as const;
export const FOUNDATION_PLACEMENT: Placement = [[LANDSCAPE_POSITION[0], -3.5, LANDSCAPE_POSITION[2]], [600, 1, 600], [0, 0, 0], -1];

export const ORIGINAL_MOUNTAINS: Placement[] = [
  [[59.53, -1, -11.84], [4, 3.14, 4], [4.1, -42.8, 5]],
  [[1, -2.21, -23], [2, 2, 2], [3.5, 30, 0]],
  [[75, 0, -90], [8, 8, 8], [3.2, -16.7, -2.6]],
  [[250, 11.33, -133], [10, 10, 10], [13.2, 20, 5]],
  [[-25.22, -1.59, -53.05], [2.5, 2.5, 2.5], [3.5, 25, 0]],
];
export const ORIGINAL_GROUND: Placement[] = [
  [[0, 0, 0], [1, 1, 1], [0, 0, 0], 2],
  [[-3.76, -.58, 12.5], [.6, .6, .6], [-5.1, 0, 0]],
  [[-17.63, -.01, 2], [1, 1, 1], [2.7, .8, 0], 3],
  [[3.12, -.75, -1.02], [1.5, .66, 1.5], [0, 0, 0]],
  [[6, .16, 15.78], [1, 1, 1], [1.1, 0, 7], 2],
  [[16.06, .34, 4], [1, 1, 1], [0, 0, 0], 2],
];

const heading = Math.atan2(LANDSCAPE_TARGET[0] - LANDSCAPE_POSITION[0], LANDSCAPE_TARGET[2] - LANDSCAPE_POSITION[2]);
const around = (degrees: number, radius: number, height: number) => {
  const angle = heading + degrees * Math.PI / 180;
  return [LANDSCAPE_POSITION[0] + Math.sin(angle) * radius, height, LANDSCAPE_POSITION[2] + Math.cos(angle) * radius];
};

/** Fill the remaining azimuths, leaving the original forward valley intact. */
export function panoramicPlacements() {
  const mountains: Placement[] = [], ground: Placement[] = [
    [[LANDSCAPE_POSITION[0], -1.6, LANDSCAPE_POSITION[2]], [1.5, .7, 1.5], [0, 37, 0]],
  ];
  for (let index = 0; index < 8; index++) {
    const angle = 75 + index * 30, variation = Math.sin(index * 2.17);
    mountains.push([around(angle, 92 + variation * 6, -1.6 + Math.cos(index * 1.7)), [6.3 + variation * .5, 5.7 + Math.cos(index * 1.3), 6.6 - variation * .4], [2, angle * .73 + 19, variation * 2]]);
    ground.push([around(angle, 23, -.9), [1.8, .65, 1.8], [0, angle + 11, 0], 1]);
    ground.push([around(angle, 50, -1.1), [3.1, .9, 3.1], [0, angle * .61, 0], 1]);
  }
  for (let index = 0; index < 7; index++) {
    const angle = 90 + index * 30, variation = Math.sin(index * 1.91);
    mountains.push([around(angle, 152 + variation * 8, -2), [10 + variation, 9.2 - variation, 10.2 - variation], [2, 137 + angle * .47, variation * 2]]);
  }
  return { mountains, ground };
}

export function applyLandscapePlacement(mesh: Object3D, [position, scale, degrees, order = 1]: Placement) {
  mesh.position.fromArray(position); mesh.scale.fromArray(scale);
  // The original front placements use the source scene's degree conversion.
  mesh.rotation.set(degrees[0] * 3.14 / 180, degrees[1] * 3.14 / 180, degrees[2] * 3.14 / 180);
  mesh.renderOrder = order; mesh.updateMatrixWorld(); mesh.matrixAutoUpdate = false;
}

/** Rotate in place; there is no orbit/translation or allocation while dragging. */
export function landscapeLookAround(camera: PerspectiveCamera) {
  const baseline = camera.quaternion.clone(), yawRotation = new Quaternion(), pitchRotation = new Quaternion();
  const up = new Vector3(0, 1, 0), right = new Vector3(1, 0, 0);
  return (yaw: number, pitch: number) => {
    yawRotation.setFromAxisAngle(up, Number.isFinite(yaw) ? yaw % (Math.PI * 2) : 0);
    pitchRotation.setFromAxisAngle(right, Number.isFinite(pitch) ? Math.max(-LANDSCAPE_PITCH_LIMIT, Math.min(LANDSCAPE_PITCH_LIMIT, pitch)) : 0);
    camera.quaternion.copy(yawRotation).multiply(baseline).multiply(pitchRotation);
    camera.updateMatrixWorld();
  };
}
