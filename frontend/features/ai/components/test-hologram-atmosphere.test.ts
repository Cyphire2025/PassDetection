import { describe, expect, it } from "vitest";
import { atmosphereView, sculptureEnergy } from "./test-hologram-atmosphere";

describe("landscape atmosphere", () => {
  it("starts at the original composition and sanitizes invalid input", () => {
    expect(atmosphereView(0, 0, 0, true)).toEqual({ yaw: 0, pitch: 0 });
    expect(atmosphereView(Number.NaN, Infinity, -Infinity, true)).toEqual({ yaw: 0, pitch: 0 });
    expect(atmosphereView(Infinity, 0, 0, true)).toEqual({ yaw: 0, pitch: 0 });
  });

  it("keeps extreme pointer positions and long-running clocks inside the visual motion budget", () => {
    for (const time of [-86400, 0, .5, 12, 100, 86400, Number.MAX_VALUE]) {
      for (const x of [-1e20, -1, 0, 1, 1e20]) {
        for (const y of [-1e20, -1, 0, 1, 1e20]) {
          const view = atmosphereView(time, x, y, true);
          expect(Number.isFinite(view.yaw) && Number.isFinite(view.pitch)).toBe(true);
          expect(Math.abs(view.yaw)).toBeLessThanOrEqual(.022 + Number.EPSILON);
          expect(Math.abs(view.pitch)).toBeLessThanOrEqual(.0115 + Number.EPSILON);
        }
      }
    }
  });

  it("responds in opposite directions while preserving a smooth, subtle idle drift", () => {
    const neutral = atmosphereView(3, 0, 0, true);
    const left = atmosphereView(3, -1, 0, true), right = atmosphereView(3, 1, 0, true);
    const up = atmosphereView(3, 0, 1, true), down = atmosphereView(3, 0, -1, true);
    expect(left.yaw).toBeGreaterThan(neutral.yaw);
    expect(right.yaw).toBeLessThan(neutral.yaw);
    expect(up.pitch).toBeGreaterThan(neutral.pitch);
    expect(down.pitch).toBeLessThan(neutral.pitch);
    expect(left.pitch).toBe(neutral.pitch);
    expect(up.yaw).toBe(neutral.yaw);
    expect(Math.hypot(neutral.yaw, neutral.pitch)).toBeGreaterThan(0);
    const next = atmosphereView(3.001, 0, 0, true);
    expect(Math.hypot(next.yaw - neutral.yaw, next.pitch - neutral.pitch)).toBeLessThan(.00001);
  });

  it("removes both idle and pointer motion when animations are disabled", () => {
    for (const input of [0, 1, -1, 1000, Number.NaN, Infinity]) {
      expect(atmosphereView(input, input, -input, false)).toEqual({ yaw: 0, pitch: 0 });
    }
  });
});

describe("sculpture energy", () => {
  it("uses the stronger listening or playback signal without adding them together", () => {
    expect(sculptureEnergy(.7, .4, true)).toBe(.7);
    expect(sculptureEnergy(.2, .8, true)).toBe(.8);
    expect(sculptureEnergy(.6, .6, true)).toBe(.6);
    expect(sculptureEnergy(0, 0, true)).toBe(0);
  });

  it("rejects non-finite samples and keeps valid signals in the physical energy range", () => {
    expect(sculptureEnergy(Number.NaN, .45, true)).toBe(.45);
    expect(sculptureEnergy(.35, Infinity, true)).toBe(.35);
    expect(sculptureEnergy(-1, -Infinity, true)).toBe(0);
    expect(sculptureEnergy(10, .2, true)).toBe(1);
    expect(sculptureEnergy(.2, 10, true)).toBe(1);
  });

  it("stays still in reduced motion regardless of either audio signal", () => {
    expect(sculptureEnergy(1, 1, false)).toBe(0);
    expect(sculptureEnergy(Infinity, Number.NaN, false)).toBe(0);
  });
});
