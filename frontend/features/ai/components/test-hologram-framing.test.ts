import { Matrix4, PerspectiveCamera, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { frameHologram, type PortraitFrame } from "./test-hologram-framing";
import { CONTAINMENT, PEDESTAL } from "./test-hologram-platform";
import { LANDSCAPE_FOV, LANDSCAPE_POSITION, LANDSCAPE_TARGET, PLATFORM_HORIZONTAL_SCALE, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

const camera = (width: number, height: number) => {
  const result = new PerspectiveCamera(LANDSCAPE_FOV, width / height, .1, 2000);
  result.position.set(...LANDSCAPE_POSITION); result.lookAt(...LANDSCAPE_TARGET);
  result.updateMatrixWorld(); return result;
};

function projectedScene(view: PerspectiveCamera, width: number, height: number) {
  const point = new Vector3(), center = new Vector3(...WORLD_SCULPTURE_POSITION);
  const project = (x: number, y: number, z: number) => {
    point.set(x, y, z).multiplyScalar(WORLD_SCULPTURE_SCALE).add(center).project(view);
    return { x: (point.x + 1) * width / 2, y: (1 - point.y) * height / 2 };
  };
  const points = [];
  // Independently sample the actual cage and platform perimeter more densely
  // than the fitting helper, including inter-sample extrema.
  for (const [radius, y] of [
    [PEDESTAL[0].radius, PEDESTAL[0].y - PEDESTAL[0].height / 2],
    [PEDESTAL[0].radius, PEDESTAL[1].y + PEDESTAL[1].height / 2],
    [CONTAINMENT.radius, CONTAINMENT.top],
  ]) {
    for (let index = 0; index < 720; index++) {
      const angle = index / 720 * Math.PI * 2, r = radius * PLATFORM_HORIZONTAL_SCALE;
      points.push(project(Math.sin(angle) * r, y, Math.cos(angle) * r));
    }
  }
  return { left: Math.min(...points.map((p) => p.x)), right: Math.max(...points.map((p) => p.x)),
    top: Math.min(...points.map((p) => p.y)), bottom: Math.max(...points.map((p) => p.y)), headTop: project(0, 1.03, 0).y };
}

describe("shared world responsive framing", () => {
  it.each([
    [1681, 936, { left: 25, top: 71.8, width: 1631, height: 650.2 }],
    [390, 844, { left: 5, top: 202, width: 380, height: 287 }],
    [390, 650, { left: 5, top: 143, width: 380, height: 221 }],
    [844, 390, { left: 22, top: 62, width: 800, height: 145 }],
    [1681, 936, { left: 25, top: 71.8, width: 1120, height: 650.2 }],
    [390, 844, { left: 5, top: 65, width: 380, height: 170 }],
  ] satisfies Array<[number, number, PortraitFrame]>)("keeps sculpture clear of controls at %i×%i within %j", (width, height, portrait) => {
    const view = camera(width, height), originalPosition = view.position.clone(), originalQuaternion = view.quaternion.clone();
    frameHologram(view, width, height, portrait);
    const box = projectedScene(view, width, height), allowance = .25;
    expect(box.left).toBeGreaterThanOrEqual(portrait.left + 12 - allowance);
    expect(box.right).toBeLessThanOrEqual(portrait.left + portrait.width - 12 + allowance);
    expect(box.top).toBeGreaterThanOrEqual(Math.max(8, portrait.top - 48) - allowance);
    expect(box.bottom).toBeLessThanOrEqual(portrait.top + portrait.height - 12 + allowance);
    expect(box.headTop).toBeGreaterThanOrEqual(portrait.top + 10 - allowance);
    expect(view.zoom).toBeGreaterThan(0); expect(view.zoom).toBeLessThanOrEqual(1);
    expect(view.position.toArray()).toEqual(originalPosition.toArray()); expect(view.quaternion.toArray()).toEqual(originalQuaternion.toArray());
  });

  it("is idempotent after resize and conversation-panel transitions", () => {
    const width = 1681, height = 936, portrait = { left: 25, top: 71.8, width: 1631, height: 650.2 };
    const view = camera(width, height);
    frameHologram(view, width, height, portrait);
    const original = view.projectionMatrix.clone();
    for (let repeat = 0; repeat < 4; repeat++) {
      view.aspect = 390 / 844; view.updateProjectionMatrix();
      frameHologram(view, 390, 844, { left: 5, top: 65, width: 380, height: 170 });
      view.aspect = width / height; view.updateProjectionMatrix();
      frameHologram(view, width, height, { ...portrait, width: 1120 });
      frameHologram(view, width, height, portrait);
      expect(view.projectionMatrix.elements).toEqual(original.elements);
      const identity = new Matrix4().multiplyMatrices(view.projectionMatrix, view.projectionMatrixInverse).elements;
      identity.forEach((value, index) => expect(value).toBeCloseTo(index % 5 === 0 ? 1 : 0, 12));
    }
  });
});
