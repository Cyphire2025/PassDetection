import { describe, expect, it } from "vitest";
import { HologramRotation, IDLE_ROTATION_SPEED } from "./test-hologram-rotation";

describe("hologram idle rotation", () => {
  it("turns at the same rate on fast and slow displays", () => {
    const turn = (dt: number) => {
      const rotation = new HologramRotation(); let angle = 0;
      for (let i = 0; i < Math.round(10 / dt); i++) angle = rotation.advance(dt, true, false);
      return angle;
    };
    expect(turn(1 / 60)).toBeCloseTo(turn(.5), 10);
    expect(turn(.1)).toBeGreaterThan(IDLE_ROTATION_SPEED * 9);
  });

  it.each(["speech", "drag"])("freezes immediately for %s and holds between syllables", (reason) => {
    const rotation = new HologramRotation();
    const start = rotation.advance(.5, true, false);
    expect(rotation.advance(.5, true, reason === "speech", reason === "drag")).toBe(start);
    expect(rotation.advance(.5, true, false)).toBe(start);
    expect(rotation.advance(.3, true, false)).toBe(start);
    const resumed = rotation.advance(.2, true, false);
    expect(resumed).toBeGreaterThan(start);
    expect(resumed - start).toBeLessThan(IDLE_ROTATION_SPEED * .1);
  });

  it("repeated speech resets the hold, without advancing the angle", () => {
    const rotation = new HologramRotation();
    const angle = rotation.advance(.5, true, false);
    for (let i = 0; i < 20; i++) {
      expect(rotation.advance(.1, true, true)).toBe(angle);
      expect(rotation.advance(.4, true, false)).toBe(angle);
    }
  });

  it("keeps reduced motion still and does not catch up after a hidden tab", () => {
    const rotation = new HologramRotation();
    const angle = rotation.advance(.5, true, false);
    expect(rotation.advance(100, false, false)).toBe(angle);
    expect(rotation.advance(0, true, false)).toBe(angle);
    expect(rotation.advance(100, true, false) - angle).toBeLessThan(IDLE_ROTATION_SPEED * .5);
  });

  it("transfers its accumulated angle on reset and leaves time to return home", () => {
    const rotation = new HologramRotation();
    const angle = rotation.advance(.5, true, false);
    expect(rotation.reset()).toBe(angle);
    expect(rotation.advance(.5, true, false)).toBe(0);
    expect(rotation.advance(.5, true, false)).toBe(0);
    expect(rotation.advance(.3, true, false)).toBeGreaterThan(0);
  });
});
