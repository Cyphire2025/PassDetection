import { describe, expect, it } from "vitest";
import { cropRegion, DEFAULT_IMAGE_PLACEMENT } from "./image-crop";

describe("workspace image crop geometry", () => {
  it("fits a tall source to a wide banner without stretching", () => {
    expect(cropRegion(800, 1600, 4, DEFAULT_IMAGE_PLACEMENT)).toEqual({ left: 0, top: 700, width: 800, height: 200 });
  });

  it("supports choosing either edge of an oversized source", () => {
    expect(cropRegion(2400, 600, 1.6, { x: 100, y: 0, zoom: 1 })).toEqual({ left: 1440, top: 0, width: 960, height: 600 });
    expect(cropRegion(2400, 600, 1.6, { x: 0, y: 100, zoom: 1 }).left).toBe(0);
  });

  it("zooms into the selected area while keeping the crop inside the source", () => {
    const crop = cropRegion(1600, 1000, 1.6, { x: 100, y: 100, zoom: 2 });
    expect(crop).toEqual({ left: 800, top: 500, width: 800, height: 500 });
    expect(crop.left + crop.width).toBe(1600);
    expect(crop.top + crop.height).toBe(1000);
  });

  it("bounds position and magnification to the supported range", () => {
    const crop = cropRegion(1600, 1000, 1.6, { x: -20, y: 120, zoom: 0.2 });
    expect(crop).toEqual({ left: 0, top: 0, width: 1600, height: 1000 });
  });
});
