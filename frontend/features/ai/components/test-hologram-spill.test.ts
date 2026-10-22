import { describe, expect, it } from "vitest";
import { PEDESTAL_BAND } from "./test-hologram-platform";
import { createHologramSpill } from "./test-hologram-spill";
import { LANDSCAPE_GROUND_ANCHOR, LANDSCAPE_GROUND_FOOTPRINT, PORTRAIT_HEAD_OFFSET_Y, WORLD_SCULPTURE_POSITION, WORLD_SCULPTURE_SCALE } from "./test-landscape-layout";

describe("terrain hologram illumination", () => {
  it("anchors its emitters to the real pedestal band and head, independent of the camera", () => {
    const { uniforms } = createHologramSpill();
    expect(uniforms.hologramBase.value.toArray()).toEqual([
      WORLD_SCULPTURE_POSITION[0], WORLD_SCULPTURE_POSITION[1] + PEDESTAL_BAND.y * WORLD_SCULPTURE_SCALE, WORLD_SCULPTURE_POSITION[2],
    ]);
    expect(uniforms.hologramFace.value.y).toBe(WORLD_SCULPTURE_POSITION[1] + PORTRAIT_HEAD_OFFSET_Y * WORLD_SCULPTURE_SCALE);
    expect(uniforms.hologramBase.value.y).toBeGreaterThan(LANDSCAPE_GROUND_ANCHOR[1]);
    expect(uniforms.hologramRingRadius.value).toBeGreaterThan(LANDSCAPE_GROUND_FOOTPRINT * .35);
    expect(uniforms.hologramRingRadius.value).toBeLessThan(LANDSCAPE_GROUND_FOOTPRINT / 2);
  });

  it("fully removes hidden illumination and limits speech variation to sixteen percent", () => {
    const spill = createHologramSpill();
    expect(spill.uniforms.hologramGlow.value).toBe(0);
    spill.update(1, 0); expect(spill.uniforms.hologramGlow.value).toBe(1);
    spill.update(1, .5); expect(spill.uniforms.hologramGlow.value).toBeCloseTo(1.08);
    spill.update(.5, 1); expect(spill.uniforms.hologramGlow.value).toBeCloseTo(.58);
    spill.update(0, 1); expect(spill.uniforms.hologramGlow.value).toBe(0);
    for (const opacity of [-Infinity, -1, 0, .5, 1, 5, Infinity, Number.NaN]) {
      for (const speech of [-Infinity, -1, 0, .5, 1, 5, Infinity, Number.NaN]) {
        spill.update(opacity, speech);
        expect(spill.uniforms.hologramGlow.value).toBeGreaterThanOrEqual(0);
        expect(spill.uniforms.hologramGlow.value).toBeLessThanOrEqual(1.16);
        if (!Number.isFinite(opacity)) expect(spill.uniforms.hologramGlow.value).toBe(0);
      }
    }
  });

  it("updates shared light references without allocating replacement vectors or uniforms", () => {
    const spill = createHologramSpill(), borrowed = { ...spill.uniforms };
    const base = borrowed.hologramBase.value, face = borrowed.hologramFace.value;
    for (let frame = 0; frame < 100; frame++) spill.update(frame / 100, frame % 2);
    expect(borrowed.hologramGlow.value).toBeCloseTo(.99 * 1.16);
    expect(borrowed.hologramBase.value).toBe(base); expect(borrowed.hologramFace.value).toBe(face);
    expect(borrowed.hologramGlow).toBe(spill.uniforms.hologramGlow);
  });
});
