import { describe, expect, it } from "vitest";
import { pedestalDiscGeometry, STONE_EDGE_CHIP } from "./test-hologram-stone-geometry";

describe("weathered stone geometry", () => {
  it("has a subdivided uneven cap and eroded shoulder while preserving the nominal contact envelope", () => {
    const geometry = pedestalDiscGeometry();
    try {
      const position = geometry.getAttribute("position");
      let capMin = Infinity, capMax = -Infinity, sideMin = Infinity, sideMax = -Infinity, capVertices = 0;
      for (let index = 0; index < position.count; index++) {
        const radius = Math.hypot(position.getX(index), position.getZ(index)), y = position.getY(index);
        if (radius > .1 && radius < .9 && y > .4) { capVertices++; capMin = Math.min(capMin, y); capMax = Math.max(capMax, y); }
        if (Math.abs(y) < .3 && radius > .95) { sideMin = Math.min(sideMin, radius); sideMax = Math.max(sideMax, radius); }
      }
      expect(capVertices).toBeGreaterThan(1500); expect(capMax - capMin).toBeGreaterThan(.05);
      expect(capMax).toBeLessThan(.54); expect(capMin).toBeGreaterThan(.46);
      expect(sideMax - sideMin).toBeGreaterThan(STONE_EDGE_CHIP * .8);
      expect(sideMax).toBeLessThanOrEqual(1.000001); expect(sideMin).toBeGreaterThanOrEqual(1 - STONE_EDGE_CHIP - .000001);
      expect(position.count).toBeLessThan(5000);
    } finally { geometry.dispose(); }
  });
});
