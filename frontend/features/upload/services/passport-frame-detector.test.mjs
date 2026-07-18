import assert from "node:assert/strict";
import test from "node:test";
import {
  analyzePassportContentPixels,
  analyzePassportFramePixels,
  isPassportCorrectionContentSafe,
  PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD,
} from "./passport-frame-detector.ts";
import {
  evaluatePassportBlurPixels,
  evaluatePassportGlarePixels,
  evaluatePassportLightingPixels,
} from "./passport-scanner-quality.ts";

const WIDTH = 320;
const HEIGHT = 200;
const PAGE = {
  left: 52,
  right: 268,
  top: 27,
  bottom: 173,
};

test("accepts an upright passport information page only after layout signals agree", () => {
  const result = analyzePassportFramePixels(
    makePassportFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );

  assert.equal(result.status, "ready", JSON.stringify(result));
  assert.equal(result.isDetected, true);
  assert.equal(result.visibleEdges, 4);
  assert.ok(result.mrzScore >= 0.52);
  assert.ok(result.portraitScore >= 0.3);
  assert.ok(result.textBlockScore >= 0.3);
});

test("accepts an international layout with the portrait on the right", () => {
  const result = analyzePassportFramePixels(
    makePassportFrame({ portraitSide: "right" }),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.status, "ready", JSON.stringify(result));
});

test("accepts a complete page under modest perspective shear", () => {
  const sheared = shearFrame(makePassportFrame(), 14);
  const result = analyzePassportFramePixels(
    sheared,
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.status, "ready", JSON.stringify(result));
});

test("accepts a guide-aligned passport when the open-booklet edge is indistinct", () => {
  const result = analyzePassportFramePixels(
    makeGuideAlignedPassportFrame({ visibleTopEdge: false }),
    WIDTH,
    HEIGHT,
    "front",
  );

  assert.equal(result.status, "ready", JSON.stringify(result));
  assert.equal(result.isDetected, true);
  assert.ok(result.documentAreaRatio >= 0.65, JSON.stringify(result));
  assert.ok(result.mrzScore >= 0.72, JSON.stringify(result));
  assert.ok(result.layoutScore >= 0.66, JSON.stringify(result));
});

test("accepts a near-frame passport when low-contrast page edges blend into the booklet", () => {
  const result = analyzePassportFramePixels(
    makeGuideAlignedPassportFrame({ lowContrastEdges: true }),
    WIDTH,
    HEIGHT,
    "front",
  );

  assert.equal(result.status, "ready", JSON.stringify(result));
  assert.equal(result.isDetected, true);
  assert.ok(result.documentAreaRatio >= 0.65, JSON.stringify(result));
  assert.ok(result.confidence >= 0.69, JSON.stringify(result));
});

test("rejects a passport information page rotated 180 degrees", () => {
  const upsideDown = makePassportFrame();
  rotateRegion180(upsideDown, PAGE);
  const result = analyzePassportFramePixels(
    upsideDown,
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.status, "upside_down", JSON.stringify(result));
  assert.equal(result.isDetected, false);
});

test("rejects a sideways passport page", () => {
  const result = analyzePassportFramePixels(
    makeSidewaysPassportFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.status, "sideways", JSON.stringify(result));
  assert.equal(result.isDetected, false);
});

test("rejects a page with a cropped corner or missing boundary", () => {
  const result = analyzePassportFramePixels(
    makePartialPassportFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.isDetected, false);
  assert.ok(
    result.status === "incomplete_document"
      || result.status === "no_document",
    JSON.stringify(result),
  );
});

test("rejects a passport cover and blank page", () => {
  const cover = analyzePassportFramePixels(
    makePassportCoverFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  const blank = analyzePassportFramePixels(
    makeBlankDocumentFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(cover.isDetected, false, JSON.stringify(cover));
  assert.equal(blank.isDetected, false, JSON.stringify(blank));
});

test("rejects Aadhaar, PAN, driving licence and credit-card style layouts", () => {
  for (const documentType of ["aadhaar", "pan", "driving", "credit_card"]) {
    const result = analyzePassportFramePixels(
      makeIdentityCardFrame(documentType),
      WIDTH,
      HEIGHT,
      "front",
    );
    assert.equal(
      result.isDetected,
      false,
      `${documentType}: ${JSON.stringify(result)}`,
    );
    assert.ok(
      result.status === "missing_mrz"
        || result.status === "not_passport_page",
      `${documentType}: ${JSON.stringify(result)}`,
    );
  }
});

test("rejects generic paper and visa-page style content", () => {
  const paper = analyzePassportFramePixels(
    makeGenericPaperFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  const visa = analyzePassportFramePixels(
    makeVisaPageFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(paper.isDetected, false, JSON.stringify(paper));
  assert.equal(visa.isDetected, false, JSON.stringify(visa));
});

test("rejects a phone screen even when passport-like content is displayed", () => {
  const result = analyzePassportFramePixels(
    makePhoneFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.isDetected, false);
  assert.ok(
    result.status === "screen_or_book"
      || result.status === "too_small"
      || result.status === "not_passport_page",
    JSON.stringify(result),
  );
});

test("rejects a book spread or multiple documents separated by a strong seam", () => {
  const book = analyzePassportFramePixels(
    makePassportFrame({ centerSeam: true }),
    WIDTH,
    HEIGHT,
    "front",
  );
  const multiple = analyzePassportFramePixels(
    makeMultipleDocumentFrame(),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(book.status, "multiple_documents", JSON.stringify(book));
  assert.equal(multiple.isDetected, false, JSON.stringify(multiple));
});

test("rejects a page without the lower MRZ structure", () => {
  const result = analyzePassportFramePixels(
    makePassportFrame({ includeMrz: false }),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.status, "missing_mrz", JSON.stringify(result));
});

test("rejects edge-connected fingers that cover the MRZ across representative skin tones", () => {
  let explicitObstructionSignals = 0;
  for (const color of [
    [229, 177, 143],
    [166, 112, 78],
    [82, 51, 35],
  ]) {
    const pixels = makePassportFrame();
    drawRect(
      pixels,
      PAGE.left + 38,
      PAGE.top + 101,
      PAGE.left + 72,
      PAGE.bottom - 3,
      color,
    );
    const result = analyzePassportFramePixels(
      pixels,
      WIDTH,
      HEIGHT,
      "front",
    );
    assert.equal(result.isDetected, false, JSON.stringify({ color, result }));
    if (
      result.criticalZoneObstructionScore
        >= PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD
    ) {
      explicitObstructionSignals += 1;
    } else {
      // If the finger hides enough of a physical edge that no safe page quad
      // exists, the stricter existing four-corner gate rejects it first.
      assert.equal(
        result.status,
        "incomplete_document",
        JSON.stringify({ color, result }),
      );
    }
  }
  assert.ok(explicitObstructionSignals >= 1);
});

test("rejects an edge-connected finger over the portrait and printed details", () => {
  const pixels = makePassportFrame();
  drawRect(
    pixels,
    PAGE.left + 3,
    PAGE.top + 30,
    PAGE.left + 34,
    PAGE.top + 99,
    [178, 122, 86],
  );
  const result = analyzePassportFramePixels(
    pixels,
    WIDTH,
    HEIGHT,
    "front",
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.ok(
    result.criticalZoneObstructionScore
      >= PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD,
    JSON.stringify(result),
  );
});

test("rejects a finger covering printed details on the passport back page", () => {
  const pixels = makePassportBackFrame();
  drawRect(
    pixels,
    PAGE.right - 32,
    PAGE.top + 34,
    PAGE.right - 3,
    PAGE.top + 102,
    [151, 96, 68],
  );
  const result = analyzePassportFramePixels(
    pixels,
    WIDTH,
    HEIGHT,
    "back",
  );

  assert.equal(result.isDetected, false, JSON.stringify(result));
  assert.ok(
    result.status === "incomplete_document"
      || result.criticalZoneObstructionScore
        >= PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD,
    JSON.stringify(result),
  );
});

test("does not reject a tiny edge grip or a uniformly warm passport substrate", () => {
  const tinyGrip = makePassportFrame();
  drawRect(
    tinyGrip,
    PAGE.left,
    PAGE.bottom - 10,
    PAGE.left + 9,
    PAGE.bottom,
    [174, 116, 82],
  );
  const gripResult = analyzePassportFramePixels(
    tinyGrip,
    WIDTH,
    HEIGHT,
    "front",
  );
  const warmPageResult = analyzePassportFramePixels(
    makePassportFrame({ pageColor: [226, 195, 166] }),
    WIDTH,
    HEIGHT,
    "front",
  );

  assert.equal(gripResult.status, "ready", JSON.stringify(gripResult));
  assert.ok(
    gripResult.criticalZoneObstructionScore
      < PASSPORT_CRITICAL_ZONE_OBSTRUCTION_THRESHOLD,
  );
  assert.equal(
    warmPageResult.status,
    "ready",
    JSON.stringify(warmPageResult),
  );
});

test("accepts a structured passport back page without applying front-page MRZ rules", () => {
  const result = analyzePassportFramePixels(
    makePassportBackFrame(),
    WIDTH,
    HEIGHT,
    "back",
  );
  assert.equal(result.status, "ready", JSON.stringify(result));
});

test("keeps a clear passport page valid against a dark surrounding surface", () => {
  const result = analyzePassportFramePixels(
    makePassportFrame({ background: [12, 14, 18] }),
    WIDTH,
    HEIGHT,
    "front",
  );
  assert.equal(result.status, "ready", JSON.stringify(result));
});

test("separate quality checks reject blur, glare and poor exposure", () => {
  const sharp = makePassportFrame();
  const blurred = boxBlur(sharp, WIDTH, HEIGHT, 5);
  const glare = makePassportFrame();
  drawRect(glare, 118, 58, 190, 112, [252, 252, 252]);
  const dark = scaleLuminance(makePassportFrame(), 0.3);

  assert.equal(
    evaluatePassportBlurPixels(sharp, WIDTH, HEIGHT).isSharp,
    true,
  );
  assert.equal(
    evaluatePassportBlurPixels(blurred, WIDTH, HEIGHT).isSharp,
    false,
  );
  assert.equal(
    evaluatePassportGlarePixels(glare, WIDTH, HEIGHT).hasGlare,
    true,
  );
  assert.equal(
    evaluatePassportLightingPixels(dark, WIDTH, HEIGHT).status,
    "too_dark",
  );
});

test("correction safety accepts passport structure and rejects a damaged crop", () => {
  const fullFrame = makePassportFrame();
  const croppedPage = cropPixels(fullFrame, WIDTH, PAGE);
  const damaged = cropPixels(
    makePassportFrame({ includeMrz: false }),
    WIDTH,
    PAGE,
  );
  const obstructedFrame = makePassportFrame();
  drawRect(
    obstructedFrame,
    PAGE.left + 3,
    PAGE.top + 30,
    PAGE.left + 34,
    PAGE.top + 99,
    [178, 122, 86],
  );
  const obstructed = cropPixels(obstructedFrame, WIDTH, PAGE);
  const pageWidth = PAGE.right - PAGE.left + 1;
  const pageHeight = PAGE.bottom - PAGE.top + 1;

  assert.equal(
    isPassportCorrectionContentSafe(
      croppedPage,
      pageWidth,
      pageHeight,
      "front",
    ),
    true,
  );
  assert.equal(
    isPassportCorrectionContentSafe(
      damaged,
      pageWidth,
      pageHeight,
      "front",
    ),
    false,
  );
  assert.equal(
    isPassportCorrectionContentSafe(
      obstructed,
      pageWidth,
      pageHeight,
      "front",
    ),
    false,
  );
});

test("content analysis does not rely on the word passport", () => {
  const fullFrame = makePassportFrame();
  const croppedPage = cropPixels(fullFrame, WIDTH, PAGE);
  const result = analyzePassportContentPixels(
    croppedPage,
    PAGE.right - PAGE.left + 1,
    PAGE.bottom - PAGE.top + 1,
    "front",
  );
  assert.ok(result.layoutScore >= 0.54, JSON.stringify(result));
});

function makePassportFrame({
  portraitSide = "left",
  includeMrz = true,
  centerSeam = false,
  background = [34, 38, 44],
  pageColor = [222, 218, 208],
} = {}) {
  const pixels = makeSolidFrame(background);
  drawDocumentBoundary(pixels, PAGE, pageColor);
  drawPassportContent(pixels, PAGE, {
    portraitSide,
    includeMrz,
  });
  if (centerSeam) {
    drawRect(
      pixels,
      Math.round((PAGE.left + PAGE.right) / 2) - 2,
      PAGE.top + 4,
      Math.round((PAGE.left + PAGE.right) / 2) + 2,
      PAGE.bottom - 4,
      [38, 38, 38],
    );
  }
  return pixels;
}

function makeGuideAlignedPassportFrame({
  visibleTopEdge = true,
  lowContrastEdges = false,
} = {}) {
  const background = lowContrastEdges
    ? [210, 207, 200]
    : [38, 42, 48];
  const pageColor = [226, 222, 212];
  const edgeColor = lowContrastEdges
    ? [205, 202, 196]
    : [28, 28, 28];
  const page = {
    left: 22,
    right: 298,
    top: 16,
    bottom: 190,
  };
  const pixels = makeSolidFrame(background);
  drawRect(
    pixels,
    page.left,
    page.top,
    page.right,
    page.bottom,
    pageColor,
  );
  drawRect(
    pixels,
    page.left,
    page.bottom - 2,
    page.right,
    page.bottom,
    edgeColor,
  );
  drawRect(
    pixels,
    page.left,
    page.top,
    page.left + 2,
    page.bottom,
    edgeColor,
  );
  drawRect(
    pixels,
    page.right - 2,
    page.top,
    page.right,
    page.bottom,
    edgeColor,
  );
  if (visibleTopEdge) {
    drawRect(
      pixels,
      page.left,
      page.top,
      page.right,
      page.top + 2,
      edgeColor,
    );
  }
  drawPassportContent(pixels, page, {
    portraitSide: "left",
    includeMrz: true,
  });
  return pixels;
}

function makePassportBackFrame() {
  const pixels = makeSolidFrame([30, 34, 40]);
  drawDocumentBoundary(pixels, PAGE, [224, 220, 210]);
  for (let row = 0; row < 9; row += 1) {
    drawGlyphLine(
      pixels,
      PAGE.left + 18,
      PAGE.right - 20 - (row % 3) * 18,
      PAGE.top + 18 + row * 11,
      4,
      [54, 54, 54],
    );
  }
  drawBarcode(
    pixels,
    PAGE.right - 82,
    PAGE.top + 16,
    PAGE.right - 20,
    PAGE.top + 42,
  );
  return pixels;
}

function makePassportCoverFrame() {
  const pixels = makeSolidFrame([32, 36, 42]);
  drawDocumentBoundary(pixels, PAGE, [36, 62, 74]);
  drawRect(pixels, 151, 76, 169, 118, [188, 156, 72]);
  drawRect(pixels, 136, 90, 184, 101, [188, 156, 72]);
  return pixels;
}

function makeBlankDocumentFrame() {
  const pixels = makeSolidFrame([35, 38, 42]);
  drawDocumentBoundary(pixels, PAGE, [225, 222, 214]);
  return pixels;
}

function makeIdentityCardFrame(documentType) {
  const pixels = makeSolidFrame([40, 42, 46]);
  drawDocumentBoundary(pixels, PAGE, [226, 222, 212]);
  drawPortraitTexture(pixels, 66, 48, 118, 122);
  for (let row = 0; row < 5; row += 1) {
    drawGlyphLine(
      pixels,
      136,
      246 - (row % 2) * 20,
      54 + row * 13,
      4,
      [48, 48, 48],
    );
  }
  if (documentType === "aadhaar") {
    drawRect(pixels, 58, 32, 262, 39, [212, 92, 62]);
  } else if (documentType === "pan") {
    drawRect(pixels, 58, 32, 262, 41, [56, 92, 136]);
  } else if (documentType === "driving") {
    drawRect(pixels, 58, 142, 250, 151, [104, 126, 72]);
  } else {
    drawRect(pixels, 74, 132, 136, 151, [182, 154, 92]);
  }
  return pixels;
}

function makeGenericPaperFrame() {
  const pixels = makeSolidFrame([30, 34, 40]);
  drawDocumentBoundary(pixels, PAGE, [226, 224, 218]);
  for (let row = 0; row < 8; row += 1) {
    drawWordLine(
      pixels,
      PAGE.left + 18,
      PAGE.right - 18 - (row % 4) * 22,
      PAGE.top + 16 + row * 12,
      3,
      [58, 58, 58],
    );
  }
  return pixels;
}

function makeVisaPageFrame() {
  const pixels = makeGenericPaperFrame();
  drawRect(pixels, 80, 64, 130, 112, [122, 78, 96]);
  drawRect(pixels, 178, 52, 242, 105, [78, 112, 142]);
  drawRect(pixels, 94, 128, 226, 138, [168, 86, 72]);
  return pixels;
}

function makePhoneFrame() {
  const pixels = makeSolidFrame([28, 30, 34]);
  drawDocumentBoundary(pixels, PAGE, [28, 28, 30]);
  const screen = {
    left: PAGE.left + 13,
    right: PAGE.right - 13,
    top: PAGE.top + 12,
    bottom: PAGE.bottom - 12,
  };
  drawDocumentBoundary(pixels, screen, [220, 218, 210]);
  drawPassportContent(pixels, screen, {
    portraitSide: "left",
    includeMrz: true,
  });
  return pixels;
}

function makeMultipleDocumentFrame() {
  const pixels = makeSolidFrame([28, 31, 36]);
  const leftPage = { left: 22, right: 153, top: 44, bottom: 157 };
  const rightPage = { left: 167, right: 298, top: 44, bottom: 157 };
  drawDocumentBoundary(pixels, leftPage, [222, 220, 214]);
  drawDocumentBoundary(pixels, rightPage, [222, 220, 214]);
  for (const page of [leftPage, rightPage]) {
    for (let row = 0; row < 6; row += 1) {
      drawGlyphLine(
        pixels,
        page.left + 10,
        page.right - 10,
        page.top + 16 + row * 14,
        4,
        [52, 52, 52],
      );
    }
  }
  return pixels;
}

function makeSidewaysPassportFrame() {
  const pixels = makeSolidFrame([30, 34, 40]);
  const page = { left: 96, right: 224, top: 10, bottom: 190 };
  drawDocumentBoundary(pixels, page, [224, 220, 212]);
  for (let row = 0; row < 9; row += 1) {
    drawGlyphLine(
      pixels,
      page.left + 12,
      page.right - 12,
      page.top + 16 + row * 16,
      4,
      [52, 52, 52],
    );
  }
  return pixels;
}

function makePartialPassportFrame() {
  const pixels = makeSolidFrame([30, 34, 40]);
  const partial = { left: -12, right: 246, top: 20, bottom: 180 };
  drawDocumentBoundary(pixels, partial, [224, 220, 212]);
  drawPassportContent(pixels, partial, {
    portraitSide: "left",
    includeMrz: true,
  });
  return pixels;
}

function drawPassportContent(pixels, page, { portraitSide, includeMrz }) {
  const pageWidth = page.right - page.left;
  const pageHeight = page.bottom - page.top;
  const portraitLeft = portraitSide === "left"
    ? page.left + Math.round(pageWidth * 0.06)
    : page.left + Math.round(pageWidth * 0.68);
  const portraitRight = portraitSide === "left"
    ? page.left + Math.round(pageWidth * 0.34)
    : page.left + Math.round(pageWidth * 0.96);
  drawPortraitTexture(
    pixels,
    portraitLeft,
    page.top + Math.round(pageHeight * 0.12),
    portraitRight,
    page.top + Math.round(pageHeight * 0.65),
  );

  const textLeft = portraitSide === "left"
    ? page.left + Math.round(pageWidth * 0.42)
    : page.left + Math.round(pageWidth * 0.05);
  const textRight = portraitSide === "left"
    ? page.left + Math.round(pageWidth * 0.95)
    : page.left + Math.round(pageWidth * 0.58);
  for (let row = 0; row < 6; row += 1) {
    drawGlyphLine(
      pixels,
      textLeft,
      textRight - (row % 3) * 14,
      page.top + Math.round(pageHeight * (0.13 + row * 0.085)),
      Math.max(3, Math.round(pageHeight * 0.035)),
      [48, 48, 48],
    );
  }

  if (includeMrz) {
    drawGlyphLine(
      pixels,
      page.left + Math.round(pageWidth * 0.045),
      page.right - Math.round(pageWidth * 0.045),
      page.top + Math.round(pageHeight * 0.73),
      Math.max(5, Math.round(pageHeight * 0.055)),
      [38, 38, 38],
    );
    drawGlyphLine(
      pixels,
      page.left + Math.round(pageWidth * 0.045),
      page.right - Math.round(pageWidth * 0.045),
      page.top + Math.round(pageHeight * 0.84),
      Math.max(5, Math.round(pageHeight * 0.055)),
      [38, 38, 38],
    );
  }
}

function drawDocumentBoundary(pixels, page, fill) {
  drawRect(pixels, page.left, page.top, page.right, page.bottom, fill);
  drawRect(pixels, page.left, page.top, page.right, page.top + 2, [24, 24, 24]);
  drawRect(pixels, page.left, page.bottom - 2, page.right, page.bottom, [24, 24, 24]);
  drawRect(pixels, page.left, page.top, page.left + 2, page.bottom, [24, 24, 24]);
  drawRect(pixels, page.right - 2, page.top, page.right, page.bottom, [24, 24, 24]);
}

function drawPortraitTexture(pixels, left, top, right, bottom) {
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const checker = (Math.floor(x / 3) + Math.floor(y / 3)) % 2 === 0;
      setPixel(pixels, x, y, checker ? [62, 66, 72] : [178, 164, 148]);
    }
  }
  drawRect(
    pixels,
    Math.round((left + right) / 2) - 6,
    top + 10,
    Math.round((left + right) / 2) + 6,
    bottom - 12,
    [126, 102, 88],
  );
}

function drawGlyphLine(pixels, left, right, top, height, color) {
  let cursor = left;
  let glyph = 0;
  while (cursor <= right - 2) {
    const glyphWidth = 2 + (glyph % 2);
    drawRect(
      pixels,
      cursor,
      top + (glyph % 3 === 0 ? 1 : 0),
      Math.min(right, cursor + glyphWidth),
      top + height - (glyph % 4 === 0 ? 1 : 0),
      color,
    );
    cursor += glyphWidth + 2;
    glyph += 1;
  }
}

function drawWordLine(pixels, left, right, top, height, color) {
  let cursor = left;
  let word = 0;
  while (cursor < right - 10) {
    const wordWidth = 13 + (word % 4) * 4;
    drawGlyphLine(
      pixels,
      cursor,
      Math.min(right, cursor + wordWidth),
      top,
      height,
      color,
    );
    cursor += wordWidth + 8 + (word % 3) * 3;
    word += 1;
  }
}

function drawBarcode(pixels, left, top, right, bottom) {
  for (let x = left; x <= right; x += 3) {
    drawRect(pixels, x, top, x + (x % 2), bottom, [38, 38, 38]);
  }
}

function shearFrame(source, maximumShift) {
  const destination = makeSolidFrame([34, 38, 44]);
  for (let y = 0; y < HEIGHT; y += 1) {
    const shift = Math.round(((y / (HEIGHT - 1)) - 0.5) * maximumShift);
    for (let x = 0; x < WIDTH; x += 1) {
      const sourceX = x - shift;
      if (sourceX < 0 || sourceX >= WIDTH) continue;
      copyPixel(source, sourceX, y, destination, x, y);
    }
  }
  return destination;
}

function rotateRegion180(pixels, region) {
  const copy = new Uint8ClampedArray(pixels);
  for (let y = region.top; y <= region.bottom; y += 1) {
    for (let x = region.left; x <= region.right; x += 1) {
      copyPixel(
        copy,
        region.right - (x - region.left),
        region.bottom - (y - region.top),
        pixels,
        x,
        y,
      );
    }
  }
}

function boxBlur(source, width, height, radius) {
  const output = new Uint8ClampedArray(source.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const sums = [0, 0, 0];
      let samples = 0;
      for (let offsetY = -radius; offsetY <= radius; offsetY += 1) {
        for (let offsetX = -radius; offsetX <= radius; offsetX += 1) {
          const sampleX = Math.max(0, Math.min(width - 1, x + offsetX));
          const sampleY = Math.max(0, Math.min(height - 1, y + offsetY));
          const offset = (sampleY * width + sampleX) * 4;
          sums[0] += source[offset];
          sums[1] += source[offset + 1];
          sums[2] += source[offset + 2];
          samples += 1;
        }
      }
      setPixel(output, x, y, sums.map((value) => Math.round(value / samples)));
    }
  }
  return output;
}

function scaleLuminance(source, factor) {
  const output = new Uint8ClampedArray(source.length);
  for (let offset = 0; offset < source.length; offset += 4) {
    output[offset] = Math.round(source[offset] * factor);
    output[offset + 1] = Math.round(source[offset + 1] * factor);
    output[offset + 2] = Math.round(source[offset + 2] * factor);
    output[offset + 3] = 255;
  }
  return output;
}

function cropPixels(source, sourceWidth, region) {
  const width = region.right - region.left + 1;
  const height = region.bottom - region.top + 1;
  const output = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      copyPixel(
        source,
        region.left + x,
        region.top + y,
        output,
        x,
        y,
        sourceWidth,
        width,
      );
    }
  }
  return output;
}

function makeSolidFrame(color) {
  const pixels = new Uint8ClampedArray(WIDTH * HEIGHT * 4);
  for (let y = 0; y < HEIGHT; y += 1) {
    for (let x = 0; x < WIDTH; x += 1) {
      setPixel(pixels, x, y, color);
    }
  }
  return pixels;
}

function drawRect(pixels, startX, startY, endX, endY, color) {
  const left = Math.max(0, Math.round(Math.min(startX, endX)));
  const right = Math.min(WIDTH - 1, Math.round(Math.max(startX, endX)));
  const top = Math.max(0, Math.round(Math.min(startY, endY)));
  const bottom = Math.min(HEIGHT - 1, Math.round(Math.max(startY, endY)));
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      setPixel(pixels, x, y, color);
    }
  }
}

function setPixel(pixels, x, y, color, width = WIDTH) {
  if (x < 0 || x >= width || y < 0) return;
  const offset = (y * width + x) * 4;
  if (offset < 0 || offset + 3 >= pixels.length) return;
  pixels[offset] = color[0];
  pixels[offset + 1] = color[1];
  pixels[offset + 2] = color[2];
  pixels[offset + 3] = 255;
}

function copyPixel(
  source,
  sourceX,
  sourceY,
  destination,
  destinationX,
  destinationY,
  sourceWidth = WIDTH,
  destinationWidth = WIDTH,
) {
  const sourceOffset = (sourceY * sourceWidth + sourceX) * 4;
  const destinationOffset = (
    destinationY * destinationWidth + destinationX
  ) * 4;
  destination[destinationOffset] = source[sourceOffset];
  destination[destinationOffset + 1] = source[sourceOffset + 1];
  destination[destinationOffset + 2] = source[sourceOffset + 2];
  destination[destinationOffset + 3] = source[sourceOffset + 3];
}
