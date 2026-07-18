import assert from "node:assert/strict";
import test from "node:test";
import {
  evaluateCompatibilityVisaPhotoFace,
  evaluatePermissiveWhiteBackground,
} from "./visa-selfie-compatibility.ts";

const WIDTH = 80;
const HEIGHT = 100;
const READY_FACE = {
  centerX: 0.5,
  centerY: 0.4,
  width: 0.4,
  height: 0.5,
};

test("requires exactly one detected face", () => {
  assert.equal(evaluateCompatibilityVisaPhotoFace(0, null), "no_face");
  assert.equal(
    evaluateCompatibilityVisaPhotoFace(2, READY_FACE),
    "multiple",
  );
});

test("accepts the earlier forgiving face placement without landmark checks", () => {
  assert.equal(
    evaluateCompatibilityVisaPhotoFace(1, READY_FACE),
    "ready",
  );
});

test("still guides faces that are too small, too large, or off center", () => {
  assert.equal(
    evaluateCompatibilityVisaPhotoFace(1, {
      ...READY_FACE,
      width: 0.3,
    }),
    "too_far",
  );
  assert.equal(
    evaluateCompatibilityVisaPhotoFace(1, {
      ...READY_FACE,
      height: 0.75,
    }),
    "too_close",
  );
  assert.equal(
    evaluateCompatibilityVisaPhotoFace(1, {
      ...READY_FACE,
      centerX: 0.62,
    }),
    "off_center",
  );
});

test("accepts white and naturally dim off-white walls", () => {
  const white = evaluatePermissiveWhiteBackground(
    makeFrame(() => [238, 238, 238]),
    WIDTH,
    HEIGHT,
  );
  const offWhite = evaluatePermissiveWhiteBackground(
    makeFrame(() => [178, 170, 162]),
    WIDTH,
    HEIGHT,
  );

  assert.equal(white.isLightNeutral, true);
  assert.equal(offWhite.isLightNeutral, true);
});

test("rejects genuinely dark or strongly coloured walls", () => {
  const dark = evaluatePermissiveWhiteBackground(
    makeFrame(() => [95, 95, 95]),
    WIDTH,
    HEIGHT,
  );
  const coloured = evaluatePermissiveWhiteBackground(
    makeFrame(() => [220, 180, 145]),
    WIDTH,
    HEIGHT,
  );

  assert.equal(dark.isLightNeutral, false);
  assert.equal(coloured.isLightNeutral, false);
});

test("does not turn wall texture or clutter into a capture gate", () => {
  const stripedNeutralWall = evaluatePermissiveWhiteBackground(
    makeFrame((x) => (
      Math.floor(x / 4) % 2 === 0
        ? [235, 235, 235]
        : [165, 165, 165]
    )),
    WIDTH,
    HEIGHT,
  );

  assert.equal(stripedNeutralWall.isLightNeutral, true);
});

test("fails closed for an invalid frame buffer", () => {
  const result = evaluatePermissiveWhiteBackground(
    new Uint8ClampedArray(),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isLightNeutral, false);
  assert.equal(result.sampleCount, 0);
});

function makeFrame(colorAt) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      const [red, green, blue] = colorAt(x, y);
      const index = (y * WIDTH + x) * 4;
      pixels[index] = red;
      pixels[index + 1] = green;
      pixels[index + 2] = blue;
      pixels[index + 3] = 255;
    }
  }
  return pixels;
}
