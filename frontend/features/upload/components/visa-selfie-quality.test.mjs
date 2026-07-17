import assert from "node:assert/strict";
import test from "node:test";
import {
  evaluateWhiteBackground,
  isInsidePersonGuide,
  isVisaSelfieFaceLargeEnough,
} from "./visa-selfie-quality.ts";

const WIDTH = 72;
const HEIGHT = 92;

test("accepts an evenly lit neutral white wall", () => {
  const pixels = makeFrame((x) => {
    const shade = 218 + Math.round((x / WIDTH) * 20);
    return [shade, shade - 2, shade - 4];
  });

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.isWhite, true);
});

test("rejects a gray wall", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [165, 165, 165]), WIDTH, HEIGHT);
  assert.equal(result.isWhite, false);
});

test("accepts a neutral off-white office wall", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [195, 195, 195]), WIDTH, HEIGHT);
  assert.equal(result.isWhite, true);
});

test("accepts a dimly lit neutral off-white wall", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [182, 180, 178]), WIDTH, HEIGHT);
  assert.equal(result.averageLuminance < 185, true);
  assert.equal(result.isWhite, true);
});

test("accepts a white wall with a moderate soft side shadow", () => {
  const pixels = makeFrame((x) => {
    const shade = 165 + Math.round((x / (WIDTH - 1)) * 55);
    return [shade + 2, shade + 1, shade];
  });

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.zoneMeanSpread > 40, true);
  assert.equal(result.isWhite, true);
});

test("rejects a warm colored wall", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [242, 210, 176]), WIDTH, HEIGHT);
  assert.equal(result.isWhite, false);
});

test("accepts a subtle warm off-white wall", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [225, 210, 200]), WIDTH, HEIGHT);
  assert.equal(result.isWhite, true);
});

test("accepts an uneven office wall with one faint horizontal seam", () => {
  const pixels = makeFrame((x, y) => {
    if (y === 14 || y === 15) return [176, 176, 174];
    const shade = 198 + Math.round((x / WIDTH) * 22) + Math.round((y / HEIGHT) * 5);
    return [shade + 4, shade + 1, shade];
  });

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.isWhite, true);
});

test("rejects a light checker pattern that passes brightness alone", () => {
  const pixels = makeFrame((x, y) => ((Math.floor(x / 6) + Math.floor(y / 6)) % 2 === 0)
    ? [242, 242, 242]
    : [188, 188, 188]);

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.averageLuminance > 190, true);
  assert.equal(result.isWhite, false);
});

test("rejects localized dark clutter on an otherwise white wall", () => {
  const pixels = makeFrame((x, y) => x < 17 && y > 30 && y < 70
    ? [80, 86, 92]
    : [235, 235, 235]);

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.isWhite, false);
});

test("retains the guide-relative face minimum after shrinking the guide", () => {
  assert.equal(isVisaSelfieFaceLargeEnough(0.31, 0.38), true);
});

test("still rejects a face below either guide-relative size minimum", () => {
  assert.equal(isVisaSelfieFaceLargeEnough(0.309, 0.38), false);
  assert.equal(isVisaSelfieFaceLargeEnough(0.31, 0.379), false);
});

function makeFrame(colorAt) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      const [red, green, blue] = isInsidePersonGuide((x + 0.5) / WIDTH, (y + 0.5) / HEIGHT)
        ? [30, 30, 30]
        : colorAt(x, y);
      const index = (y * WIDTH + x) * 4;
      pixels[index] = red;
      pixels[index + 1] = green;
      pixels[index + 2] = blue;
      pixels[index + 3] = 255;
    }
  }
  return pixels;
}
