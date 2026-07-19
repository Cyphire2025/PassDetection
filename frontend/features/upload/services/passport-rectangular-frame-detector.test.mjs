import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  analyzeRectangularPassportFramePixels,
} from "./passport-rectangular-frame-detector.ts";

const WIDTH = 320;
const HEIGHT = 200;

test("accepts a guide-aligned page from three visible rectangle edges", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeFrame(["left", "right", "bottom"]),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, true, JSON.stringify(result));
  assert.equal(result.status, "ready");
  assert.equal(result.visibleEdges, 3);
  assert.equal(result.motionSignature.length, 96);
});

test("accepts low-contrast guide-aligned page edges without passport layout checks", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeFrame(["left", "right", "top", "bottom"], 22),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, true, JSON.stringify(result));
  assert.equal(result.status, "ready");
  assert.equal(result.visibleEdges, 4);
});

test("keeps a partial two-edge page in an incomplete state", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeFrame(["left", "bottom"]),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.equal(result.status, "incomplete_document");
  assert.equal(result.visibleEdges, 2);
});

test("does not detect a rectangle in a uniform frame", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeFrame([]),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.equal(result.status, "no_document");
  assert.equal(result.visibleEdges, 0);
});

test("live analysis rejects only extreme exposure and keeps low contrast usable", () => {
  const dark = analyzeRectangularPassportFramePixels(
    makeFrame(["left", "right", "bottom"], 22, 8),
    WIDTH,
    HEIGHT,
  );
  const normal = analyzeRectangularPassportFramePixels(
    makeFrame(["left", "right", "bottom"], 22, 48),
    WIDTH,
    HEIGHT,
  );

  assert.equal(dark.isDetected, true);
  assert.equal(dark.lightingStatus, "too_dark");
  assert.equal(normal.lightingStatus, "good");
});

test("passport hook uses the permissive rolling detector while capture stays manual", () => {
  const hookSource = readFileSync(
    new URL("../hooks/use-passport-frame-detection.ts", import.meta.url),
    "utf8",
  );
  const cameraSource = readFileSync(
    new URL("../components/smart-camera.tsx", import.meta.url),
    "utf8",
  );

  assert.match(hookSource, /detectRectangularPassportFrame\(/);
  assert.doesNotMatch(hookSource, /\bdetectPassportFrame\(/);
  assert.match(hookSource, /CAMERA_QUALITY_POLICY\.liveAnalysisIntervalMs/);
  assert.match(hookSource, /updateRollingCameraReadiness\(/);
  assert.match(cameraSource, /onClick=\{\(\) => void takePhoto\(\)\}/);
  assert.doesNotMatch(
    cameraSource,
    /passport-auto-capture|automatic capture|getPassportAutoCaptureProgress/,
  );
});

function makeFrame(edges, contrast = 140, background = 48) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let offset = 0; offset < pixels.length; offset += 4) {
    pixels[offset] = background;
    pixels[offset + 1] = background;
    pixels[offset + 2] = background;
    pixels[offset + 3] = 255;
  }

  const edgeValue = background + contrast;
  const left = 27;
  const right = 293;
  const top = 17;
  const bottom = 183;
  if (edges.includes("left")) drawVerticalLine(pixels, left, edgeValue);
  if (edges.includes("right")) drawVerticalLine(pixels, right, edgeValue);
  if (edges.includes("top")) drawHorizontalLine(pixels, top, edgeValue);
  if (edges.includes("bottom")) drawHorizontalLine(pixels, bottom, edgeValue);
  return pixels;
}

function drawVerticalLine(pixels, x, value) {
  for (let y = 8; y < HEIGHT - 8; y += 1) {
    setPixel(pixels, x, y, value);
    setPixel(pixels, x + 1, y, value);
  }
}

function drawHorizontalLine(pixels, y, value) {
  for (let x = 8; x < WIDTH - 8; x += 1) {
    setPixel(pixels, x, y, value);
    setPixel(pixels, x, y + 1, value);
  }
}

function setPixel(pixels, x, y, value) {
  const offset = (y * WIDTH + x) * 4;
  pixels[offset] = value;
  pixels[offset + 1] = value;
  pixels[offset + 2] = value;
  pixels[offset + 3] = 255;
}
