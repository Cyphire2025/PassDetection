import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  analyzeRectangularPassportFramePixels,
} from "./passport-rectangular-frame-detector.ts";

const WIDTH = 320;
const HEIGHT = 200;

test("accepts a complete guide-aligned page with four coherent boundaries", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame(),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, true, JSON.stringify(result));
  assert.equal(result.status, "ready");
  assert.equal(result.visibleEdges, 4);
  assert.equal(result.strongEdges, 4);
  assert.ok(result.documentAreaRatio >= 0.6, JSON.stringify(result));
  assert.ok(result.detailRowCoverage >= 2 / 3, JSON.stringify(result));
  assert.equal(result.motionSignature.length, 96);
});

test("accepts low-contrast page boundaries without passport content checks", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({ background: 74, page: 90 }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, true, JSON.stringify(result));
  assert.equal(result.status, "ready");
  assert.equal(result.visibleEdges, 4);
});

test("accepts three strong edges plus a plausible weak open-book edge", () => {
  const pixels = makeDocumentFrame();
  weakenOutsideOfEdge(pixels, "top", 179);
  const result = analyzeRectangularPassportFramePixels(
    pixels,
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, true, JSON.stringify(result));
  assert.equal(result.visibleEdges, 4);
  assert.equal(result.strongEdges, 3);
});

test("accepts a complete page with modest within-limit rotation", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({
      left: 31,
      right: 289,
      top: 19,
      bottom: 181,
      rotationDegrees: 5,
    }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, true, JSON.stringify(result));
  assert.equal(result.status, "ready");
  assert.ok(result.skewDegrees >= 3, JSON.stringify(result));
  assert.ok(result.skewDegrees <= 8, JSON.stringify(result));
});

test("accepts a complete page with mild perspective shear", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({ horizontalShear: 0.06 }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, true, JSON.stringify(result));
  assert.equal(result.status, "ready");
  assert.equal(result.visibleEdges, 4);
  assert.ok(result.documentAreaRatio >= 0.6, JSON.stringify(result));
});

test("rejects a keyboard-like grid when no document is present", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeKeyboardFrame(),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.notEqual(result.status, "ready");
  assert.ok(result.strongEdges < 3, JSON.stringify(result));
});

test("rejects a uniform frame when no document is present", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeSolidFrame(56),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.equal(result.status, "no_document");
  assert.equal(result.visibleEdges, 0);
});

test("rejects a complete blank rectangle without distributed page detail", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({ details: "none" }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.visibleEdges, 4, JSON.stringify(result));
  assert.equal(result.strongEdges, 4, JSON.stringify(result));
  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.equal(result.status, "not_passport_page");
  assert.equal(result.detailTileRatio, 0);
});

test("rejects a blank booklet page with detail confined to a bottom strip", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({ details: "bottom_strip" }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.visibleEdges, 4, JSON.stringify(result));
  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.equal(result.status, "not_passport_page");
  assert.ok(result.detailRowCoverage < 2 / 3, JSON.stringify(result));
});

test("rejects a partial page even when three boundaries are strong", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({ left: -72, right: 250 }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.notEqual(result.status, "ready");
});

test("rejects a complete page shifted materially outside the guide", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({
      left: -7,
      right: 259,
      top: 17,
      bottom: 183,
    }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.equal(result.status, "incomplete_document");
});

test("rejects a materially rotated page", () => {
  const result = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({
      left: 39,
      right: 281,
      top: 28,
      bottom: 172,
      rotationDegrees: 14,
    }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.equal(result.status, "excessive_skew");
  assert.ok(result.skewDegrees > 8, JSON.stringify(result));
});

test("live analysis rejects only extreme exposure after geometry passes", () => {
  const dark = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({ background: 3, page: 18 }),
    WIDTH,
    HEIGHT,
  );
  const normal = analyzeRectangularPassportFramePixels(
    makeDocumentFrame({ background: 48, page: 64 }),
    WIDTH,
    HEIGHT,
  );

  assert.equal(dark.lightingStatus, "too_dark");
  assert.equal(normal.isDetected, true);
  assert.equal(normal.lightingStatus, "good");
});

test("passport hook keeps geometry-only rolling detection and manual capture", () => {
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

function makeDocumentFrame({
  background = 48,
  page = 188,
  left = 27,
  right = 293,
  top = 17,
  bottom = 183,
  rotationDegrees = 0,
  horizontalShear = 0,
  details = "distributed",
} = {}) {
  const pixels = makeSolidFrame(background);
  const centerX = (left + right) / 2;
  const centerY = (top + bottom) / 2;
  const halfWidth = (right - left) / 2;
  const halfHeight = (bottom - top) / 2;
  const radians = rotationDegrees * Math.PI / 180;
  const cosine = Math.cos(radians);
  const sine = Math.sin(radians);

  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      const deltaX = x - centerX;
      const deltaY = y - centerY;
      const rotatedX = deltaX * cosine + deltaY * sine;
      const localY = -deltaX * sine + deltaY * cosine;
      const localX = rotatedX - horizontalShear * localY;
      if (
        Math.abs(localX) <= halfWidth
        && Math.abs(localY) <= halfHeight
      ) {
        const u = (localX + halfWidth) / Math.max(1, halfWidth * 2);
        const v = (localY + halfHeight) / Math.max(1, halfHeight * 2);
        const hasDetail = details === "distributed"
          ? isDistributedSyntheticDetail(u, v)
          : details === "bottom_strip"
            ? isBottomStripSyntheticDetail(u, v)
            : false;
        setPixel(
          pixels,
          x,
          y,
          hasDetail ? Math.max(0, page - 32) : page,
        );
      }
    }
  }
  return pixels;
}

function isDistributedSyntheticDetail(u, v) {
  if (u <= 0.09 || u >= 0.91 || v <= 0.11 || v >= 0.89) {
    return false;
  }
  const horizontalRule = (
    Math.floor(v * 36) % 4 === 0
    && u >= 0.12
    && u <= 0.88
  );
  const portraitTexture = (
    u >= 0.11
    && u <= 0.32
    && v >= 0.16
    && v <= 0.62
    && (Math.floor(u * 34) + Math.floor(v * 31)) % 4 <= 1
  );
  return horizontalRule || portraitTexture;
}

function isBottomStripSyntheticDetail(u, v) {
  return (
    u >= 0.09
    && u <= 0.91
    && v >= 0.76
    && v <= 0.9
    && Math.floor(v * 42) % 4 === 0
  );
}

function makeKeyboardFrame() {
  const pixels = makeSolidFrame(38);
  for (let row = 0; row < 5; row += 1) {
    for (let column = 0; column < 8; column += 1) {
      fillRectangle(
        pixels,
        10 + column * 39,
        22 + row * 33,
        31,
        22,
        98,
      );
    }
  }
  fillRectangle(pixels, 58, 170, 204, 20, 72);
  return pixels;
}

function weakenOutsideOfEdge(pixels, side, outsideValue) {
  if (side !== "top") throw new Error("Unsupported test edge");
  for (let y = 0; y < 17; y += 1) {
    for (let x = 27; x <= 293; x += 1) {
      setPixel(pixels, x, y, outsideValue);
    }
  }
}

function makeSolidFrame(value) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let offset = 0; offset < pixels.length; offset += 4) {
    pixels[offset] = value;
    pixels[offset + 1] = value;
    pixels[offset + 2] = value;
    pixels[offset + 3] = 255;
  }
  return pixels;
}

function fillRectangle(pixels, left, top, width, height, value) {
  for (let y = Math.max(0, top); y < Math.min(HEIGHT, top + height); y += 1) {
    for (let x = Math.max(0, left); x < Math.min(WIDTH, left + width); x += 1) {
      setPixel(pixels, x, y, value);
    }
  }
}

function setPixel(pixels, x, y, value) {
  const offset = (y * WIDTH + x) * 4;
  pixels[offset] = value;
  pixels[offset + 1] = value;
  pixels[offset + 2] = value;
  pixels[offset + 3] = 255;
}
