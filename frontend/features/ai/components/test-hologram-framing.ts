import { PerspectiveCamera, Vector3 } from "three";
import { CONTAINMENT, PEDESTAL } from "./test-hologram-platform";
import { LANDSCAPE_POSITION, LANDSCAPE_TARGET, PLATFORM_HORIZONTAL_SCALE, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

export type PortraitFrame = { left: number; top: number; width: number; height: number };

/** Fit the shared world to the available conversation layout, never the pedestal alone. */
export function frameHologram(camera: PerspectiveCamera, width: number, height: number, portrait: PortraitFrame) {
  const neutral = camera.clone();
  neutral.zoom = 1; neutral.position.set(...LANDSCAPE_POSITION); neutral.lookAt(...LANDSCAPE_TARGET);
  neutral.updateProjectionMatrix(); neutral.updateMatrixWorld();
  const center = new Vector3(...WORLD_SCULPTURE_POSITION), point = new Vector3();
  const bounds = { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity };
  const project = (x: number, y: number, z: number) => {
    point.set(x, y, z).multiplyScalar(WORLD_SCULPTURE_SCALE).add(center).project(neutral);
    return { x: (point.x + 1) * width / 2, y: (1 - point.y) * height / 2 };
  };
  for (const [radius, y] of [[PEDESTAL[0].radius, -1.24], [PEDESTAL[0].radius, -1.1], [CONTAINMENT.radius, CONTAINMENT.top]]) {
    for (let index = 0; index < 64; index++) {
      const angle = index / 64 * Math.PI * 2, r = radius * PLATFORM_HORIZONTAL_SCALE;
      const p = project(Math.sin(angle) * r, y, Math.cos(angle) * r);
      bounds.left = Math.min(bounds.left, p.x); bounds.right = Math.max(bounds.right, p.x);
      bounds.top = Math.min(bounds.top, p.y); bounds.bottom = Math.max(bounds.bottom, p.y);
    }
  }
  // The transparent cage can occupy the empty center of the header. The solid
  // portrait has its own clearance; the lower edge stops before the microphone.
  const left = portrait.left + 12, right = portrait.left + portrait.width - 12;
  const top = Math.max(8, portrait.top - 48), bottom = portrait.top + portrait.height - 12;
  const headTop = project(0, 1.03, 0).y, solidTop = portrait.top + 10;
  const zoom = Math.max(.1, Math.min(1, (right - left) / (bounds.right - bounds.left),
    (bottom - top) / (bounds.bottom - bounds.top), (bottom - solidTop) / (bounds.bottom - headTop)));
  camera.zoom = zoom; camera.updateProjectionMatrix();
  const scaledTop = height / 2 + (bounds.top - height / 2) * zoom;
  const scaledBottom = height / 2 + (bounds.bottom - height / 2) * zoom;
  const scaledHead = height / 2 + (headTop - height / 2) * zoom;
  const preferred = Math.min(0, bottom - scaledBottom);
  const shiftY = Math.max(top - scaledTop, solidTop - scaledHead, preferred);
  camera.projectionMatrix.elements[8] = 1 - (left + right) / width;
  camera.projectionMatrix.elements[9] = shiftY * 2 / height;
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
}
