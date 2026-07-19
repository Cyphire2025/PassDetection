import assert from "node:assert/strict";
import test from "node:test";
import {
  analyzePassportFinalPixels,
} from "./passport-final-quality.ts";

const WIDTH = 320;
const HEIGHT = 220;

test("clear physical passport front and back images pass final validation", () => {
  const front = analyzePassportFinalPixels(
    makePassport("front"),
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );
  const back = analyzePassportFinalPixels(
    makePassport("back"),
    WIDTH,
    HEIGHT,
    "back",
    1440,
    990,
  );

  assert.equal(front.outcome, "pass", JSON.stringify(front));
  assert.equal(back.outcome, "pass", JSON.stringify(back));
  assert.ok(front.metrics.mainDetails.detailDensity > 0);
  assert.ok(front.metrics.lowerTextBand.detailDensity > 0);
  assert.ok(front.metrics.portrait.contrast > 0);
});

test("a slightly imperfect open-book fold is not hard rejected", () => {
  const pixels = makePassport("front");
  drawRect(pixels, 155, 8, 159, 211, [116, 110, 104]);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.notEqual(result.outcome, "hard_failure", JSON.stringify(result));
});

test("blurred passport text cannot pass because the surroundings are sharp", () => {
  const pixels = makePassport("front");
  drawRect(pixels, 108, 18, 309, 153, [188, 184, 174]);
  drawRect(pixels, 12, 146, 309, 211, [188, 184, 174]);
  drawRect(pixels, 0, 0, 319, 3, [18, 18, 18]);
  drawRect(pixels, 0, 216, 319, 219, [18, 18, 18]);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.outcome, "hard_failure", JSON.stringify(result));
  assert.equal(result.reason, "text_unreadable");
});

test("a passport occupying too little of the final image is rejected", () => {
  const pixels = solidFrame([64, 66, 70]);
  drawRect(pixels, 74, 53, 246, 167, [218, 212, 198]);
  drawRect(pixels, 74, 53, 246, 55, [28, 28, 28]);
  drawRect(pixels, 74, 165, 246, 167, [28, 28, 28]);
  drawRect(pixels, 74, 53, 76, 167, [28, 28, 28]);
  drawRect(pixels, 244, 53, 246, 167, [28, 28, 28]);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.outcome, "hard_failure", JSON.stringify(result));
  assert.equal(result.reason, "passport_too_small");
});

test("a clearly missing major document area requires a retake", () => {
  const pixels = makePassport("front");
  drawRect(pixels, 8, 145, 311, 219, [190, 186, 176]);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.outcome, "hard_failure", JSON.stringify(result));
  assert.equal(result.reason, "document_area_missing");
});

test("a missing passport portrait area cannot pass on sharp text alone", () => {
  const pixels = makePassport("front");
  drawRect(pixels, 8, 8, 121, 153, [218, 212, 198]);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.outcome, "hard_failure", JSON.stringify(result));
  assert.equal(result.reason, "document_area_missing");
  assert.match(result.message, /portrait/i);
});

test("obvious phone bezel and UI controls are hard failures", () => {
  const pixels = makePassport("front");
  drawRect(pixels, 0, 0, 319, 17, [12, 12, 14]);
  drawRect(pixels, 0, 202, 319, 219, [12, 12, 14]);
  drawRect(pixels, 0, 0, 14, 219, [12, 12, 14]);
  drawRect(pixels, 305, 0, 319, 219, [12, 12, 14]);
  for (let x = 28; x < 120; x += 18) {
    drawRect(pixels, x, 5, x + 8, 11, [242, 242, 242]);
  }
  drawRect(pixels, 135, 208, 185, 213, [238, 238, 238]);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.outcome, "hard_failure", JSON.stringify(result));
  assert.equal(result.reason, "obvious_screen_recapture");
});

test("a structured mid-grey gallery toolbar is an obvious screen failure", () => {
  const pixels = makePassport("front");
  drawRect(pixels, 0, 0, 319, 20, [105, 108, 112]);
  for (let x = 20; x < 285; x += 34) {
    drawRect(pixels, x, 5, x + 12, 15, [232, 234, 236]);
  }

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.outcome, "hard_failure", JSON.stringify(result));
  assert.equal(result.reason, "obvious_screen_recapture");
});

test("one weak screen-like border is borderline rather than a hard failure", () => {
  const pixels = makePassport("front");
  drawRect(pixels, 0, 18, 12, 201, [18, 18, 20]);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.outcome, "borderline", JSON.stringify(result));
  assert.equal(result.reason, "weak_screen_suspicion");
  assert.match(result.confirmationPrompt, /passport number/i);
});

test("a small harmless reflection passes while severe glare over details fails", () => {
  const harmless = makePassport("front");
  drawRect(harmless, 274, 34, 287, 51, [250, 250, 248]);
  const harmlessResult = analyzePassportFinalPixels(
    harmless,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  const severe = makePassport("front");
  drawRect(severe, 126, 42, 250, 127, [252, 252, 250]);
  const severeResult = analyzePassportFinalPixels(
    severe,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(harmlessResult.outcome, "pass", JSON.stringify(harmlessResult));
  assert.equal(severeResult.outcome, "hard_failure", JSON.stringify(severeResult));
  assert.equal(severeResult.reason, "severe_glare");
});

test("lower useful resolution is confirmable and extreme exposure is rejected", () => {
  const lowerResolution = analyzePassportFinalPixels(
    makePassport("front"),
    WIDTH,
    HEIGHT,
    "front",
    700,
    481,
  );
  const veryLowButDetailed = analyzePassportFinalPixels(
    makePassport("front"),
    WIDTH,
    HEIGHT,
    "front",
    480,
    330,
  );
  const dark = analyzePassportFinalPixels(
    solidFrame([8, 8, 8]),
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(lowerResolution.outcome, "borderline");
  assert.equal(lowerResolution.reason, "lower_resolution");
  assert.equal(veryLowButDetailed.outcome, "borderline");
  assert.equal(veryLowButDetailed.reason, "lower_resolution");
  assert.equal(dark.outcome, "hard_failure");
  assert.equal(dark.reason, "extreme_exposure");
});

test("three confident outer edges cannot let a possibly clipped page pass", () => {
  const pixels = solidFrame([150, 145, 136]);
  drawRect(pixels, 0, 18, 275, 201, [218, 212, 198]);
  drawRect(pixels, 0, 18, 275, 20, [55, 54, 52]);
  drawRect(pixels, 0, 199, 275, 201, [55, 54, 52]);
  drawRect(pixels, 273, 18, 275, 201, [55, 54, 52]);
  drawTextBlock(pixels, 114, 34, 262, 137, 8);
  drawTextBlock(pixels, 14, 154, 262, 194, 3);

  const result = analyzePassportFinalPixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
    1440,
    990,
  );

  assert.equal(result.metrics.strongBoundaryCount, 3, JSON.stringify(result));
  assert.equal(result.metrics.missingBoundaryLikely, true, JSON.stringify(result));
  assert.equal(result.outcome, "borderline", JSON.stringify(result));
  assert.equal(result.reason, "document_area_missing");
});

function makePassport(side) {
  const pixels = solidFrame([222, 216, 202]);
  for (let y = 8; y < HEIGHT - 8; y += 1) {
    for (let x = 8; x < WIDTH - 8; x += 1) {
      const variation = ((x * 7 + y * 11) % 13) - 6;
      setPixel(pixels, x, y, [
        218 + variation,
        212 + variation,
        198 + variation,
      ]);
    }
  }

  if (side === "front") {
    drawPortrait(pixels, 14, 24, 102, 142);
    drawTextBlock(pixels, 116, 28, 304, 137, 8);
    drawTextBlock(pixels, 14, 158, 306, 207, 3);
  } else {
    drawTextBlock(pixels, 34, 34, 286, 139, 8);
    drawTextBlock(pixels, 28, 142, 292, 198, 4);
    drawBarcode(pixels, 68, 92, 252, 135);
  }
  return pixels;
}

function drawPortrait(pixels, left, top, right, bottom) {
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const checker = (Math.floor(x / 3) + Math.floor(y / 3)) % 2;
      setPixel(
        pixels,
        x,
        y,
        checker ? [74, 80, 86] : [176, 146, 126],
      );
    }
  }
}

function drawTextBlock(pixels, left, top, right, bottom, rows) {
  const spacing = Math.max(7, Math.floor((bottom - top) / rows));
  for (let row = 0; row < rows; row += 1) {
    const y = top + row * spacing;
    let x = left;
    let glyph = 0;
    while (x < right - 4) {
      const width = 2 + (glyph % 3);
      drawRect(
        pixels,
        x,
        y,
        Math.min(right, x + width),
        y + 4 + (glyph % 2),
        [42, 43, 46],
      );
      x += width + 2 + (glyph % 2);
      glyph += 1;
    }
  }
}

function drawBarcode(pixels, left, top, right, bottom) {
  for (let x = left; x <= right; x += 4) {
    drawRect(pixels, x, top, x + (x % 3 === 0 ? 2 : 1), bottom, [35, 35, 35]);
  }
}

function solidFrame(color) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      setPixel(pixels, x, y, color);
    }
  }
  return pixels;
}

function drawRect(pixels, startX, startY, endX, endY, color) {
  for (let y = Math.max(0, startY); y <= Math.min(HEIGHT - 1, endY); y += 1) {
    for (let x = Math.max(0, startX); x <= Math.min(WIDTH - 1, endX); x += 1) {
      setPixel(pixels, x, y, color);
    }
  }
}

function setPixel(pixels, x, y, color) {
  const offset = (y * WIDTH + x) * 4;
  pixels[offset] = color[0];
  pixels[offset + 1] = color[1];
  pixels[offset + 2] = color[2];
  pixels[offset + 3] = 255;
}
