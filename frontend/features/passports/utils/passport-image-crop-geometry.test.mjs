import assert from "node:assert/strict";
import test from "node:test";

import {
  MIN_CROP_SIZE,
  normalizeCrop,
  resizeCrop,
  rotateCropClockwise,
} from "./passport-image-crop-geometry.ts";

const crop = {
  x: 0.2,
  y: 0.25,
  width: 0.5,
  height: 0.4,
  rotation_degrees: 0,
};

test("moving a crop clamps it inside all image boundaries", () => {
  assert.deepEqual(resizeCrop(crop, "move", -2, 2), {
    ...crop,
    x: 0,
    y: 0.6,
  });
});

test("each resize corner respects image boundaries and minimum size", () => {
  for (const mode of ["nw", "ne", "sw", "se"]) {
    const result = resizeCrop(crop, mode, mode.endsWith("w") ? 5 : -5, mode.startsWith("n") ? 5 : -5);
    assert.ok(result.x >= 0);
    assert.ok(result.y >= 0);
    assert.ok(result.x + result.width <= 1);
    assert.ok(result.y + result.height <= 1);
    assert.ok(result.width >= MIN_CROP_SIZE);
    assert.ok(result.height >= MIN_CROP_SIZE);
  }
});

test("clockwise rotation preserves the selected physical rectangle", () => {
  assert.deepEqual(rotateCropClockwise(crop), {
    x: 0.35,
    y: 0.2,
    width: 0.4,
    height: 0.5,
    rotation_degrees: 90,
  });
  let rotated = crop;
  for (let index = 0; index < 4; index += 1) rotated = rotateCropClockwise(rotated);
  assert.deepEqual(rotated, crop);
});

test("normalization repairs malformed or out-of-bounds server geometry", () => {
  const normalized = normalizeCrop({
    x: -0.5,
    y: 0.95,
    width: 0.01,
    height: 2,
    rotation_degrees: 270,
  });
  assert.equal(normalized.x, 0);
  assert.equal(normalized.y, 0);
  assert.equal(normalized.width, MIN_CROP_SIZE);
  assert.equal(normalized.height, 1);
});
