import assert from "node:assert/strict";
import test from "node:test";

import {
  croppedPassportFileName,
  passportCropOutputSize,
  passportCropPixelBounds,
  rotatedPassportImageSize,
} from "./passport-manual-crop-math.ts";

test("rotation swaps passport image axes only for quarter turns", () => {
  assert.deepEqual(rotatedPassportImageSize(4000, 3000, 0), {
    width: 4000,
    height: 3000,
  });
  assert.deepEqual(rotatedPassportImageSize(4000, 3000, 90), {
    width: 3000,
    height: 4000,
  });
  assert.deepEqual(rotatedPassportImageSize(4000, 3000, 270), {
    width: 3000,
    height: 4000,
  });
});

test("normalized crop geometry becomes clamped integer source pixels", () => {
  assert.deepEqual(
    passportCropPixelBounds(
      {
        x: 0.1,
        y: 0.2,
        width: 0.7,
        height: 0.6,
        rotation_degrees: 0,
      },
      { width: 1000, height: 500 },
    ),
    {
      left: 100,
      top: 100,
      width: 700,
      height: 300,
    },
  );
});

test("large crops are downscaled without changing their aspect ratio", () => {
  assert.deepEqual(
    passportCropOutputSize({ width: 4800, height: 3200 }),
    { width: 2400, height: 1600 },
  );
  assert.deepEqual(
    passportCropOutputSize({ width: 1200, height: 800 }),
    { width: 1200, height: 800 },
  );
});

test("cropped passport output receives a safe JPEG filename", () => {
  assert.equal(
    croppedPassportFileName("passport.front.HEIC"),
    "passport.front-cropped.jpg",
  );
  assert.equal(croppedPassportFileName(".jpg"), "passport-cropped.jpg");
});
