import { describe, expect, it } from "vitest";
import { conversationMotion, HologramInteraction, POINTER_TRAIL_LENGTH } from "./test-hologram-interaction";

describe("anchored portrait interaction", () => {
  it("gives a gentle stroke a visible response, increases it with speed and does not emit on entry or hover", () => {
    const slow = new HologramInteraction(), fast = new HologramInteraction();
    for (const input of [slow, fast]) { input.update(0, 0, true, 0); expect(input.energies.every((e) => e.y === 0)).toBe(true); }
    slow.update(.01, 0, true, .1); fast.update(.3, 0, true, .1);
    expect(slow.energies[0].y).toBeGreaterThan(.38);
    expect(fast.energies[0].y).toBeGreaterThan(slow.energies[0].y);
    expect(fast.energies[0].y).toBeLessThanOrEqual(1);
    slow.update(.01, 0, true, .2); expect(slow.energies.filter((e) => e.y > 0)).toHaveLength(1);
    slow.update(1, 1, false, .3); slow.update(-1, -1, true, .4);
    expect(slow.energies.filter((e) => e.y > 0)).toHaveLength(1);
  });

  it("bounds memory and clears old strokes across suspension, invalid input and reduced motion", () => {
    const input = new HologramInteraction();
    for (let i = 0; i < 1000; i++) input.update(Math.sin(i), Math.cos(i), true, i / 60);
    expect(input.strokes).toHaveLength(POINTER_TRAIL_LENGTH);
    input.update(Infinity, NaN, true, 17); input.update(.5, .5, true, 18);
    expect(input.energies.every((e) => e.toArray().every(Number.isFinite))).toBe(true);
    input.reset(); expect(input.energies.every((e) => e.y === 0)).toBe(true);
  });

  it("holds rotation throughout voice activity and reduces ambient movement without stopping it", () => {
    expect(conversationMotion(false, false, 0, false)).toEqual({ holdRotation: false, ambient: 1, response: 0 });
    expect(conversationMotion(true, false, 0, false)).toEqual({ holdRotation: true, ambient: .28, response: 0 });
    expect(conversationMotion(false, true, 0, false)).toEqual({ holdRotation: true, ambient: .28, response: 1 });
    expect(conversationMotion(false, false, .1, false).holdRotation).toBe(true);
    expect(conversationMotion(false, false, 0, true).response).toBe(1);
  });
});
