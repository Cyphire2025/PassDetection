import { describe, expect, it } from "vitest";
import { HologramTransitions } from "./test-hologram-transitions";
import { HologramRotation } from "./test-hologram-rotation";

const home = () => ({ yaw: -.38, pitch: -.07, zoom: 1, landscapeYaw: 0, landscapePitch: 0 });

describe("hologram visible-time transitions", () => {
  it.each([20, 600, 1200, 4000])("finishes the entrance on the first frame past 1.2 seconds at %d ms cadence", (cadence) => {
    const transition = new HologramTransitions(home());
    transition.enter(); transition.resume(100);
    for (let at = cadence; at < 1200; at += cadence) transition.advance(at + 100, true);
    transition.advance(100 + Math.ceil(1200 / cadence) * cadence, true);
    expect(transition.opacity).toBe(1);
  });

  it("preserves the entrance and reset easing at the same visible timestamps", () => {
    const target = { ...home(), yaw: 1.2, pitch: .3, zoom: 1.18, landscapeYaw: 2, landscapePitch: -.2 };
    const transition = new HologramTransitions(target);
    transition.enter(); transition.resume(0); transition.reset(home(), 0);
    transition.advance(400, true);
    expect(transition.opacity).toBeCloseTo(19 / 27, 12);
    expect(target.yaw).toBeCloseTo(home().yaw + (1.2 - home().yaw) / 16, 12);
    expect(transition.resetting).toBe(true);
    transition.advance(800, true);
    expect(target).toEqual(home()); expect(transition.resetting).toBe(false);
    transition.advance(1200, true); expect(transition.opacity).toBe(1);
  });

  it("pauses both transitions while the renderer is suspended without hidden-time catch-up", () => {
    const target = { ...home(), yaw: 2, landscapeYaw: 1 };
    const transition = new HologramTransitions(target);
    transition.enter(); transition.resume(0); transition.reset(home(), 0);
    transition.advance(400, true);
    const paused = { ...target }, opacity = transition.opacity;
    transition.suspend(); transition.advance(60400, true);
    expect(target).toEqual(paused); expect(transition.opacity).toBe(opacity);
    transition.resume(60400); transition.advance(60400, true);
    expect(target).toEqual(paused); expect(transition.opacity).toBe(opacity);
    transition.advance(60800, true);
    expect(target).toEqual(home()); expect(transition.resetting).toBe(false);
    transition.advance(61200, true); expect(transition.opacity).toBe(1);
  });

  it("finishes active transitions immediately when reduced motion is requested", () => {
    const target = { ...home(), yaw: 3, zoom: .8 };
    const transition = new HologramTransitions(target);
    transition.enter(); transition.resume(0); transition.reset(home(), 0);
    transition.advance(200, true); transition.advance(250, false);
    expect(target).toEqual(home()); expect(transition.opacity).toBe(1);
    expect(transition.resetting).toBe(false);
  });

  it("does not overwrite a new manual gesture after cancelling a reset", () => {
    const target = { ...home(), yaw: 2 };
    const transition = new HologramTransitions(target);
    transition.resume(0); transition.reset(home(), 0); transition.advance(300, true);
    transition.cancelReset(); target.yaw += .18;
    const manual = { ...target };
    transition.advance(5000, true);
    expect(target).toEqual(manual); expect(transition.resetting).toBe(false);
  });

  it("starts Home at the input event rather than backdating it to the previous slow frame", () => {
    const target = { ...home(), yaw: 2 };
    const transition = new HologramTransitions(target);
    transition.resume(0); transition.advance(100, true);
    transition.reset(home(), 900); transition.advance(900, true);
    expect(target.yaw).toBe(2); expect(transition.resetting).toBe(true);
    transition.advance(1700, true); expect(target).toEqual(home());
  });

  it("keeps rotation held until the eased visible pose converges on slow frames", () => {
    const target = { ...home(), yaw: 2.4, pitch: .5, zoom: 1.18, landscapeYaw: 1 };
    const view = { ...target }, rotation = new HologramRotation();
    const transition = new HologramTransitions(target);
    transition.resume(0); transition.reset(home(), 0);
    let returning = true, arrivedAt = 0;
    for (let at = 600; at <= 6000; at += 600) {
      transition.advance(at, true);
      for (const key of Object.keys(home()) as Array<keyof typeof target>) view[key] += (target[key] - view[key]) * (1 - Math.exp(-.25 * 9));
      const manipulating = returning;
      if (returning && !transition.resetting && Object.keys(home()).reduce((sum, key) => sum + Math.abs(view[key as keyof typeof view] - target[key as keyof typeof target]), 0) < .001) {
        returning = false; arrivedAt = at;
      }
      expect(rotation.advance(.6, true, false, manipulating)).toBe(0);
      if (!returning) break;
    }
    expect(arrivedAt).toBeGreaterThan(800); expect(arrivedAt).toBeLessThanOrEqual(3000);
    expect(Math.abs(view.yaw - home().yaw)).toBeLessThan(.001);
    // Actual input or audible output still suppresses rotation after Home.
    expect(rotation.advance(.6, true, true)).toBe(0);
    expect(rotation.advance(.5, true, false)).toBe(0);
    expect(rotation.advance(.5, true, false)).toBeGreaterThan(0);
  });
});
