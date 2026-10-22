import { PerspectiveCamera, Vector3 } from "three";
import { describe, expect, it } from "vitest";
import { LANDSCAPE_FOV, LANDSCAPE_POSITION, LANDSCAPE_TARGET, landscapeOrbitAround } from "./test-landscape-layout";

const setup = () => {
  const camera = new PerspectiveCamera(LANDSCAPE_FOV, 2, .1, 2000);
  camera.position.set(...LANDSCAPE_POSITION); camera.lookAt(...LANDSCAPE_TARGET); camera.updateMatrixWorld();
  return { camera, orbit: landscapeOrbitAround(camera), target: new Vector3(...LANDSCAPE_TARGET) };
};

describe("shared-world landscape orbit", () => {
  it("keeps the sculpture target fixed and camera distance constant through a full orbit", () => {
    const { camera, orbit, target } = setup(), radius = camera.position.distanceTo(target);
    const home = camera.position.clone(), orientation = camera.quaternion.clone();
    for (let degrees = 0; degrees <= 360; degrees += 15) {
      orbit(degrees * Math.PI / 180, 0);
      expect(camera.position.distanceTo(target)).toBeCloseTo(radius, 10);
      const projected = target.clone().project(camera);
      expect(projected.x).toBeCloseTo(0, 10); expect(projected.y).toBeCloseTo(0, 10);
    }
    expect(camera.position.equals(home)).toBe(true); expect(camera.quaternion.angleTo(orientation)).toBeLessThan(1e-7);
  });

  it("prevents downward orbit from crossing the ground and resets malformed inputs", () => {
    const { camera, orbit, target } = setup(), radius = camera.position.distanceTo(target);
    for (const yaw of [-20, 0, 1, 20]) for (const pitch of [-100, -.24, 0, .24, 100]) {
      orbit(yaw, pitch);
      expect(camera.position.y).toBeGreaterThanOrEqual(3 - 1e-10);
      expect(camera.position.distanceTo(target)).toBeCloseTo(radius, 10);
      expect(camera.matrixWorld.elements.every(Number.isFinite)).toBe(true);
    }
    orbit(Number.NaN, Infinity);
    expect(camera.position.toArray()).toEqual([...LANDSCAPE_POSITION]);
  });
});
