import assert from "node:assert/strict";
import test from "node:test";
import {
  buildVisaPhotoCameraConstraints,
  encodeVisaJpegUnderLimit,
  evaluateFallbackFinalVisaPhoto,
  evaluateFinalVisaPhoto,
  evaluateLiveVisaPhotoBackground,
  evaluateVisaPhotoFaceCount,
  evaluateVisaPhotoClarity,
  evaluateVisaPhotoFacePlacement,
  evaluateWhiteBackground,
  isInsidePersonGuide,
  isVisaPhotoFallbackCaptureAllowed,
  isVisaPhotoFrameCaptureReady,
  isVisaPhotoFaceStable,
  isVisaSelfieFaceLargeEnough,
  requestVisaPhotoCamera,
} from "./visa-selfie-quality.ts";

const WIDTH = 72;
const HEIGHT = 92;
const PHOTO_WIDTH = 96;
const PHOTO_HEIGHT = 144;
const FACE = {
  centerX: 0.5,
  centerY: 0.4,
  width: 0.4,
  height: 0.5,
  leftEye: { x: 0.42, y: 0.35 },
  rightEye: { x: 0.58, y: 0.35 },
};

test("accepts an evenly lit neutral white wall", () => {
  const pixels = makeFrame((x) => {
    const shade = 218 + Math.round((x / WIDTH) * 20);
    return [shade, shade - 2, shade - 4];
  });

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.isWhite, true);
});

test("accepts a neutral wall photographed dimmer than its real white tone", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [165, 165, 165]), WIDTH, HEIGHT);
  assert.equal(result.isWhite, true);
});

test("rejects a genuinely dark neutral background", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [118, 118, 118]), WIDTH, HEIGHT);
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

test("accepts a white wall under uneven warm indoor lighting", () => {
  const pixels = makeFrame((x, y) => {
    const horizontalLight = 152 + Math.round((x / (WIDTH - 1)) * 52);
    const verticalLight = Math.round((y / (HEIGHT - 1)) * 12);
    const shade = horizontalLight + verticalLight;
    return [shade + 10, shade + 5, shade];
  });

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.zoneMeanSpread > 35, true);
  assert.equal(result.isWhite, true);
});

test("ignores realistic hair and shoulder spill outside the ideal silhouette", () => {
  const pixels = makeFrame((x, y) => {
    const normalizedX = (x + 0.5) / WIDTH;
    const normalizedY = (y + 0.5) / HEIGHT;
    const hairSpill = normalizedY < 0.34 && normalizedX > 0.07 && normalizedX < 0.88;
    const shoulderSpill = normalizedY > 0.64
      && Math.abs(normalizedX - 0.5) < 0.48;
    if (hairSpill) return [24, 22, 21];
    if (shoulderSpill) return [54, 76, 49];
    const shade = 190 + Math.round(normalizedX * 28);
    return [shade + 3, shade + 2, shade];
  });

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.isWhite, true);
});

test("rejects a warm colored wall", () => {
  const result = evaluateWhiteBackground(makeFrame(() => [242, 210, 176]), WIDTH, HEIGHT);
  assert.equal(result.isWhite, false);
  assert.equal(result.isLightNeutral, false);
  assert.equal(result.failureReason, "not_light_neutral");
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
  assert.equal(result.isPlain, false);
  assert.equal(result.failureReason, "not_plain");
});

test("rejects subtle wallpaper stripes while allowing smooth light falloff", () => {
  const pixels = makeFrame((x) => Math.floor(x / 5) % 2 === 0
    ? [232, 230, 226]
    : [209, 207, 203]);

  const result = evaluateWhiteBackground(pixels, WIDTH, HEIGHT);
  assert.equal(result.averageLuminance > 200, true);
  assert.equal(result.isWhite, false);
  assert.equal(result.isLightNeutral, true);
  assert.equal(result.isPlain, false);
  assert.equal(result.failureReason, "not_plain");
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

test("accepts an off-white wall with mild natural texture around a detected person", () => {
  const pixels = makeVisaPhotoFrame({
    backgroundAt: (x, y) => {
      const texture = ((x * 7 + y * 11) % 9) - 4;
      return [214 + texture, 210 + texture, 204 + texture];
    },
  });

  const result = evaluateWhiteBackground(
    pixels,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.isWhite, true);
});

test("live guidance tolerates a small edge socket on an otherwise plain wall", () => {
  const pixels = makeVisaPhotoFrame();
  drawRect(pixels, 0, 36, 10, 65, [198, 198, 194]);
  drawRect(pixels, 1, 42, 5, 57, [68, 68, 66]);
  drawRect(pixels, 7, 45, 10, 53, [44, 44, 42]);

  const result = evaluateLiveVisaPhotoBackground(
    pixels,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );

  assert.equal(result.status, "white", JSON.stringify(result.metrics));
});

test("live guidance still rejects widespread screen-like structure", () => {
  const pixels = makeVisaPhotoFrame({
    backgroundAt: (x, y) => (
      (Math.floor(x / 4) + Math.floor(y / 4)) % 2 === 0
        ? [242, 240, 236]
        : [168, 166, 162]
    ),
  });

  const result = evaluateLiveVisaPhotoBackground(
    pixels,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );

  assert.equal(result.status, "not_plain", JSON.stringify(result.metrics));
});

test("live guidance still rejects a dark wall", () => {
  const result = evaluateLiveVisaPhotoBackground(
    makeVisaPhotoFrame({
      backgroundAt: () => [108, 108, 106],
    }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );

  assert.equal(result.status, "not_white", JSON.stringify(result.metrics));
});

test("allows one mildly failing background tile but rejects two", () => {
  const oneMildTile = makeVisaPhotoFrame({
    backgroundAt: (x, y) => (
      x < PHOTO_WIDTH * 0.25 && y < PHOTO_HEIGHT * 0.25
        ? [205, 173, 154]
        : [224, 222, 218]
    ),
  });
  const twoMildTiles = makeVisaPhotoFrame({
    backgroundAt: (x, y) => (
      y < PHOTO_HEIGHT * 0.25
        && (
          x < PHOTO_WIDTH * 0.25
          || x >= PHOTO_WIDTH * 0.75
        )
        ? [205, 173, 154]
        : [224, 222, 218]
    ),
  });

  const one = evaluateWhiteBackground(
    oneMildTile,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  const two = evaluateWhiteBackground(
    twoMildTiles,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );

  assert.equal(one.failingLightNeutralZoneCount, 1, JSON.stringify(one));
  assert.equal(one.isWhite, true, JSON.stringify(one));
  assert.ok(two.failingLightNeutralZoneCount >= 2, JSON.stringify(two));
  assert.equal(two.isWhite, false, JSON.stringify(two));
});

test("rejects white drawers with panel lines and handles", () => {
  const pixels = makeVisaPhotoFrame();
  drawHorizontalLine(pixels, 24, [132, 132, 132], 2);
  drawHorizontalLine(pixels, 58, [132, 132, 132], 2);
  drawHorizontalLine(pixels, 94, [132, 132, 132], 2);
  drawRect(pixels, 7, 38, 23, 43, [72, 72, 72]);
  drawRect(pixels, 89, 72, 105, 77, [72, 72, 72]);

  const result = evaluateWhiteBackground(
    pixels,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.isLightNeutral, true);
  assert.equal(result.isPlain, false);
  assert.equal(result.failureReason, "not_plain");
});

test("rejects white cupboard seams and paired handles", () => {
  const pixels = makeVisaPhotoFrame();
  drawVerticalLine(pixels, 18, [124, 124, 124], 2);
  drawVerticalLine(pixels, 92, [124, 124, 124], 2);
  drawVerticalLine(pixels, 4, [172, 172, 172], 2);
  drawRect(pixels, 15, 52, 20, 77, [78, 78, 78]);
  drawRect(pixels, 90, 52, 95, 77, [78, 78, 78]);

  const result = evaluateWhiteBackground(
    pixels,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.isWhite, false);
  assert.equal(result.isPlain, false);
});

test("rejects shelves on an otherwise neutral wall", () => {
  const pixels = makeVisaPhotoFrame();
  drawHorizontalLine(pixels, 30, [88, 88, 88], 4);
  drawHorizontalLine(pixels, 82, [88, 88, 88], 4);
  drawRect(pixels, 2, 25, 27, 29, [118, 118, 118]);
  drawRect(pixels, 84, 77, 110, 81, [118, 118, 118]);

  const result = evaluateWhiteBackground(
    pixels,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.isWhite, false);
  assert.equal(result.failureReason, "not_plain");
});

test("rejects a patterned wall around a detected person", () => {
  const pixels = makeVisaPhotoFrame({
    backgroundAt: (x, y) => (Math.floor(x / 7) + Math.floor(y / 7)) % 2 === 0
      ? [232, 230, 226]
      : [192, 190, 186],
  });

  const result = evaluateWhiteBackground(
    pixels,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.isLightNeutral, true);
  assert.equal(result.isPlain, false);
});

test("accepts a centred, correctly sized face with level eyes", () => {
  assert.equal(evaluateVisaPhotoFacePlacement(FACE), "ready");
  assert.equal(
    evaluateVisaPhotoFacePlacement({
      ...FACE,
      leftEye: FACE.rightEye,
      rightEye: FACE.leftEye,
    }),
    "ready",
  );
});

test("rejects faces that are too small, too large, or off-centre", () => {
  assert.equal(
    evaluateVisaPhotoFacePlacement({ ...FACE, width: 0.25, height: 0.34 }),
    "too_far",
  );
  assert.equal(
    evaluateVisaPhotoFacePlacement({ ...FACE, width: 0.74, height: 0.76 }),
    "too_close",
  );
  assert.equal(
    evaluateVisaPhotoFacePlacement({ ...FACE, centerX: 0.65 }),
    "off_center",
  );
});

test("rejects a severe eye-line tilt", () => {
  assert.equal(
    evaluateVisaPhotoFacePlacement({
      ...FACE,
      leftEye: { x: 0.42, y: 0.32 },
      rightEye: { x: 0.58, y: 0.39 },
    }),
    "head_tilt",
  );
});

test("requires exactly one detected face", () => {
  assert.equal(evaluateVisaPhotoFaceCount(0), "no_face");
  assert.equal(evaluateVisaPhotoFaceCount(1), "one_face");
  assert.equal(evaluateVisaPhotoFaceCount(2), "multiple");
});

test("accepts a well-lit face with deterministic detail", () => {
  const result = evaluateVisaPhotoClarity(
    makeVisaPhotoFrame(),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.status, "good");
});

test("rejects underexposed and overexposed face regions", () => {
  const dark = evaluateVisaPhotoClarity(
    makeVisaPhotoFrame({ faceColor: [26, 24, 22], featureColor: [12, 11, 10] }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  const bright = evaluateVisaPhotoClarity(
    makeVisaPhotoFrame({
      faceColor: [252, 251, 249],
      featureColor: [249, 248, 246],
    }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(dark.status, "too_dark");
  assert.equal(bright.status, "too_bright");
});

test("rejects a flat, blurry face region", () => {
  const result = evaluateVisaPhotoClarity(
    makeVisaPhotoFrame({
      faceColor: [176, 140, 116],
      omitFaceDetail: true,
    }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.status, "blurry", JSON.stringify(result));
});

test("capture readiness uses current background and face clarity signals", () => {
  assert.equal(isVisaPhotoFrameCaptureReady("white", "good"), true);
  assert.equal(isVisaPhotoFrameCaptureReady("not_white", "good"), false);
  assert.equal(isVisaPhotoFrameCaptureReady("white", "blurry"), false);
});

test("face stability tolerates small detector noise but rejects movement", () => {
  assert.equal(isVisaPhotoFaceStable(null, FACE), false);
  assert.equal(isVisaPhotoFaceStable(FACE, {
    ...FACE,
    centerX: 0.52,
    centerY: 0.38,
    width: 0.43,
    height: 0.47,
  }), true);
  assert.equal(isVisaPhotoFaceStable(FACE, {
    ...FACE,
    centerX: 0.62,
  }), false);
});

test("final validation passes a clear face against a plain light-neutral wall", () => {
  const pixels = makeVisaPhotoFrame();
  const result = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: FACE,
    pixels,
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });

  assert.equal(result.outcome, "pass", JSON.stringify(result));
});

test("final validation hard-rejects severe face blur and obvious wall patterns", () => {
  const blurred = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: FACE,
    pixels: makeVisaPhotoFrame({
      faceColor: [176, 140, 116],
      omitFaceDetail: true,
    }),
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });
  const patterned = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: FACE,
    pixels: makeVisaPhotoFrame({
      backgroundAt: (x, y) => (
        (Math.floor(x / 4) + Math.floor(y / 4)) % 2 === 0
          ? [242, 240, 236]
          : [168, 166, 162]
      ),
    }),
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });

  assert.equal(blurred.outcome, "hard_failure", JSON.stringify(blurred));
  assert.match(blurred.message, /blurred/i);
  assert.equal(patterned.outcome, "hard_failure", JSON.stringify(patterned));
  assert.match(patterned.message, /background/i);
});

test("final validation keeps a small peripheral socket reviewable", () => {
  const pixels = makeVisaPhotoFrame();
  drawRect(pixels, 0, 36, 10, 65, [198, 198, 194]);
  drawRect(pixels, 1, 42, 5, 57, [68, 68, 66]);
  drawRect(pixels, 7, 45, 10, 53, [44, 44, 42]);

  const result = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: FACE,
    pixels,
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });

  assert.notEqual(result.outcome, "hard_failure", JSON.stringify(result));
});

test("final validation hard-rejects missing and multiple faces", () => {
  const pixels = makeVisaPhotoFrame();
  for (const faceCount of [0, 2]) {
    const result = evaluateFinalVisaPhoto({
      faceCount,
      face: null,
      pixels,
      width: PHOTO_WIDTH,
      height: PHOTO_HEIGHT,
    });
    assert.equal(result.outcome, "hard_failure", JSON.stringify(result));
  }
});

test("final placement keeps near-threshold movement borderline and definite clipping hard", () => {
  const pixels = makeVisaPhotoFrame();
  const nearThreshold = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: {
      ...FACE,
      width: 0.29,
      height: 0.36,
    },
    pixels,
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });
  const topClipped = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: {
      ...FACE,
      centerY: 0.26,
      height: 0.5,
    },
    pixels,
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });

  assert.equal(nearThreshold.outcome, "borderline", JSON.stringify(nearThreshold));
  assert.equal(topClipped.outcome, "hard_failure", JSON.stringify(topClipped));
  assert.match(topClipped.message, /cut off/i);
});

test("model fallback still hard-fails exact-pixel defects and otherwise stays borderline", () => {
  const usable = evaluateFallbackFinalVisaPhoto({
    pixels: makeVisaPhotoFrame(),
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });
  const blurred = evaluateFallbackFinalVisaPhoto({
    pixels: makeVisaPhotoFrame({
      faceColor: [176, 140, 116],
      omitFaceDetail: true,
    }),
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });

  assert.equal(usable.outcome, "borderline", JSON.stringify(usable));
  assert.equal(usable.faceCount, "no_face");
  assert.equal(blurred.outcome, "hard_failure", JSON.stringify(blurred));
});

test("final validation keeps a weak background-texture signal borderline", () => {
  const result = evaluateFinalVisaPhoto({
    faceCount: 1,
    face: FACE,
    pixels: makeVisaPhotoFrame({
      backgroundAt: (x) => Math.floor(x / 8) % 2 === 0
        ? [224, 222, 218]
        : [207, 205, 201],
    }),
    width: PHOTO_WIDTH,
    height: PHOTO_HEIGHT,
  });

  assert.equal(result.outcome, "borderline", JSON.stringify(result));
});

test("JPEG selection rejects the exact two-MiB boundary and uses actual Blob sizes", async () => {
  const byteLimit = 2 * 1024 * 1024;
  const calls = [];
  const result = await encodeVisaJpegUnderLimit(async (quality) => {
    calls.push(quality);
    return {
      size: quality === 0.94 ? byteLimit : byteLimit - 1,
    };
  }, byteLimit);

  assert.deepEqual(calls, [0.94, 0.9]);
  assert.equal(result.quality, 0.9);
  assert.equal(result.blob.size, byteLimit - 1);
});

test("allows the guided fallback only for an available camera and unavailable model after acknowledgement", () => {
  const fallbackState = {
    cameraReady: true,
    modelUnavailable: true,
    userAcknowledgedRequirements: true,
  };
  assert.equal(isVisaPhotoFallbackCaptureAllowed(fallbackState), true);
  assert.equal(
    isVisaPhotoFallbackCaptureAllowed({
      ...fallbackState,
      cameraReady: false,
    }),
    false,
  );
  assert.equal(
    isVisaPhotoFallbackCaptureAllowed({
      ...fallbackState,
      modelUnavailable: false,
    }),
    false,
  );
  assert.equal(
    isVisaPhotoFallbackCaptureAllowed({
      ...fallbackState,
      userAcknowledgedRequirements: false,
    }),
    false,
  );
});

test("prefers the rear camera without requiring it", () => {
  const constraints = buildVisaPhotoCameraConstraints(true);
  assert.deepEqual(constraints, {
    video: {
      facingMode: { ideal: "environment" },
      width: { ideal: 1920 },
      height: { ideal: 1440 },
    },
    audio: false,
  });
});

test("retries without facingMode when a browser rejects the rear preference", async () => {
  const calls = [];
  const expectedStream = { id: "fallback-camera" };
  const result = await requestVisaPhotoCamera(async (constraints) => {
    calls.push(constraints);
    if (calls.length === 1) {
      const error = new Error("Unsupported camera constraint");
      error.name = "OverconstrainedError";
      throw error;
    }
    return expectedStream;
  });

  assert.equal(result, expectedStream);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].video.facingMode, { ideal: "environment" });
  assert.equal("facingMode" in calls[1].video, false);
});

test("does not retry after camera permission is denied", async () => {
  let calls = 0;
  const error = new Error("Camera blocked");
  error.name = "NotAllowedError";

  await assert.rejects(
    requestVisaPhotoCamera(async () => {
      calls += 1;
      throw error;
    }),
    error,
  );
  assert.equal(calls, 1);
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

function makeVisaPhotoFrame({
  backgroundAt = () => [222, 219, 214],
  faceColor = [184, 140, 112],
  featureColor = [54, 42, 36],
  omitFaceDetail = false,
} = {}) {
  const pixels = new Uint8ClampedArray(PHOTO_WIDTH * PHOTO_HEIGHT * 4);
  for (let y = 0; y < PHOTO_HEIGHT; y += 1) {
    for (let x = 0; x < PHOTO_WIDTH; x += 1) {
      const [red, green, blue] = backgroundAt(x, y);
      setPixel(pixels, x, y, [red, green, blue]);
    }
  }

  const centerX = Math.round(FACE.centerX * PHOTO_WIDTH);
  const centerY = Math.round(FACE.centerY * PHOTO_HEIGHT);
  const radiusX = Math.round(FACE.width * PHOTO_WIDTH * 0.46);
  const radiusY = Math.round(FACE.height * PHOTO_HEIGHT * 0.47);
  for (let y = centerY - radiusY; y <= centerY + radiusY; y += 1) {
    for (let x = centerX - radiusX; x <= centerX + radiusX; x += 1) {
      const inFace = ((x - centerX) / radiusX) ** 2
        + ((y - centerY) / radiusY) ** 2 <= 1;
      if (!inFace) continue;
      const contour = omitFaceDetail ? 0 : Math.round(((x + y) % 5) - 2);
      setPixel(pixels, x, y, faceColor.map((value) => value + contour));
    }
  }

  if (!omitFaceDetail) {
    const leftEye = normalizedPixel(FACE.leftEye);
    const rightEye = normalizedPixel(FACE.rightEye);
    drawRect(
      pixels,
      leftEye.x - 2,
      leftEye.y - 1,
      leftEye.x + 2,
      leftEye.y + 1,
      featureColor,
    );
    drawRect(
      pixels,
      rightEye.x - 2,
      rightEye.y - 1,
      rightEye.x + 2,
      rightEye.y + 1,
      featureColor,
    );
    drawHorizontalLine(
      pixels,
      leftEye.y - 5,
      featureColor,
      1,
      leftEye.x - 4,
      leftEye.x + 4,
    );
    drawHorizontalLine(
      pixels,
      rightEye.y - 5,
      featureColor,
      1,
      rightEye.x - 4,
      rightEye.x + 4,
    );
    drawVerticalLine(
      pixels,
      centerX,
      featureColor,
      1,
      centerY - 1,
      centerY + 12,
    );
    drawHorizontalLine(
      pixels,
      centerY + 19,
      featureColor,
      1,
      centerX - 7,
      centerX + 7,
    );
  }

  return pixels;
}

function drawHorizontalLine(
  pixels,
  y,
  color,
  thickness = 1,
  startX = 0,
  endX = PHOTO_WIDTH - 1,
) {
  drawRect(
    pixels,
    startX,
    y,
    endX,
    y + thickness - 1,
    color,
  );
}

function drawVerticalLine(
  pixels,
  x,
  color,
  thickness = 1,
  startY = 0,
  endY = PHOTO_HEIGHT - 1,
) {
  drawRect(
    pixels,
    x,
    startY,
    x + thickness - 1,
    endY,
    color,
  );
}

function drawRect(pixels, startX, startY, endX, endY, color) {
  const left = Math.max(0, Math.round(Math.min(startX, endX)));
  const right = Math.min(PHOTO_WIDTH - 1, Math.round(Math.max(startX, endX)));
  const top = Math.max(0, Math.round(Math.min(startY, endY)));
  const bottom = Math.min(PHOTO_HEIGHT - 1, Math.round(Math.max(startY, endY)));
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      setPixel(pixels, x, y, color);
    }
  }
}

function setPixel(pixels, x, y, color) {
  if (x < 0 || x >= PHOTO_WIDTH || y < 0 || y >= PHOTO_HEIGHT) return;
  const index = (y * PHOTO_WIDTH + x) * 4;
  pixels[index] = color[0];
  pixels[index + 1] = color[1];
  pixels[index + 2] = color[2];
  pixels[index + 3] = 255;
}

function normalizedPixel(point) {
  return {
    x: Math.round(point.x * PHOTO_WIDTH),
    y: Math.round(point.y * PHOTO_HEIGHT),
  };
}
