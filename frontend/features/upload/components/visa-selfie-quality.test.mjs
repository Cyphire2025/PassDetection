import assert from "node:assert/strict";
import test from "node:test";
import {
  buildVisaPhotoCameraConstraints,
  evaluateVisaPhotoFaceCount,
  evaluateVisaPhotoClarity,
  evaluateVisaPhotoEyewear,
  evaluateVisaPhotoFacePlacement,
  evaluateWhiteBackground,
  hasStableVisaPhotoReadiness,
  isInsidePersonGuide,
  isVisaPhotoFallbackCaptureAllowed,
  isVisaPhotoFrameCaptureReady,
  isVisaSelfieFaceLargeEnough,
  requestVisaPhotoCamera,
  stabilizeVisaPhotoEyewearStatus,
  updateKnownVisaPhotoEyewearViolation,
  visaPhotoEyewearGuidance,
} from "./visa-selfie-quality.ts";

const WIDTH = 72;
const HEIGHT = 92;
const PHOTO_WIDTH = 112;
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

test("does not report eyewear for an unobstructed face", () => {
  const result = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame(),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.status, "clear");
});

test("detects thin transparent frames", () => {
  const result = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame({ eyewear: "thin" }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.status, "detected");
  assert.equal(
    isVisaPhotoFrameCaptureReady("white", "good", result.status),
    false,
  );
  assert.equal(
    visaPhotoEyewearGuidance(result.status),
    "Please remove your glasses before taking the Visa Photo",
  );
});

test("detects thick frames and sunglasses", () => {
  const thickFrames = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame({ eyewear: "thick" }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  const sunglasses = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame({ eyewear: "sunglasses" }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(thickFrames.status, "detected");
  assert.equal(sunglasses.status, "detected");
});

test("detects frames despite bright lens glare", () => {
  const result = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame({ eyewear: "glare" }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.status, "detected");
});

test("blocks one-sided partial or side-angle frame evidence as uncertain", () => {
  const result = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame({ eyewear: "partial" }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.equal(result.status, "uncertain");
  assert.equal(
    isVisaPhotoFrameCaptureReady("white", "good", result.status),
    false,
  );
  assert.equal(
    visaPhotoEyewearGuidance(result.status),
    "Face the camera directly and keep both eyes clearly visible while we check for glasses",
  );
});

test("blocks missing eye landmarks with controlled uncertain guidance", () => {
  const faceWithoutEyes = {
    centerX: FACE.centerX,
    centerY: FACE.centerY,
    width: FACE.width,
    height: FACE.height,
  };
  const result = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame(),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    faceWithoutEyes,
  );
  assert.equal(result.status, "uncertain");
  assert.equal(
    isVisaPhotoFrameCaptureReady("white", "good", result.status),
    false,
  );
  assert.equal(
    visaPhotoEyewearGuidance(result.status),
    "Face the camera directly and keep both eyes clearly visible while we check for glasses",
  );
});

test("low-light facial evidence is not misreported as definite eyewear", () => {
  const result = evaluateVisaPhotoEyewear(
    makeVisaPhotoFrame({
      faceColor: [48, 45, 42],
      featureColor: [31, 29, 27],
    }),
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    FACE,
  );
  assert.notEqual(result.status, "detected");
});

test("requires consecutive readiness samples before capture", () => {
  assert.equal(hasStableVisaPhotoReadiness([true, true, true], 4), false);
  assert.equal(hasStableVisaPhotoReadiness([true, true, false, true], 4), false);
  assert.equal(hasStableVisaPhotoReadiness([false, true, true, true, true], 4), true);
});

test("unlocks capture only after stable clear eye evidence", () => {
  const eyewearSamples = [];
  const readinessSamples = [];
  const statuses = [];

  for (let index = 0; index < 6; index += 1) {
    const status = stabilizeVisaPhotoEyewearStatus("clear", eyewearSamples);
    statuses.push(status);
    readinessSamples.push(
      isVisaPhotoFrameCaptureReady("white", "good", status),
    );
  }

  assert.deepEqual(statuses, [
    "uncertain",
    "uncertain",
    "clear",
    "clear",
    "clear",
    "clear",
  ]);
  assert.deepEqual(readinessSamples, [false, false, true, true, true, true]);
  assert.equal(hasStableVisaPhotoReadiness(readinessSamples.slice(0, 5), 4), false);
  assert.equal(hasStableVisaPhotoReadiness(readinessSamples, 4), true);
  assert.equal(visaPhotoEyewearGuidance(statuses.at(-1)), null);
});

test("keeps definite eyewear blocking through brief detector dropouts", () => {
  const samples = [];
  assert.equal(
    stabilizeVisaPhotoEyewearStatus("detected", samples),
    "detected",
  );
  for (let index = 0; index < 4; index += 1) {
    assert.equal(
      stabilizeVisaPhotoEyewearStatus("clear", samples),
      "detected",
    );
  }
  assert.equal(stabilizeVisaPhotoEyewearStatus("clear", samples), "clear");
});

test("keeps a known eyewear violation latched through uncertain or unavailable checks", () => {
  let knownViolation = updateKnownVisaPhotoEyewearViolation(false, "detected");
  assert.equal(knownViolation, true);

  knownViolation = updateKnownVisaPhotoEyewearViolation(
    knownViolation,
    "uncertain",
  );
  assert.equal(knownViolation, true);

  knownViolation = updateKnownVisaPhotoEyewearViolation(
    knownViolation,
    "checking",
  );
  assert.equal(knownViolation, true);

  knownViolation = updateKnownVisaPhotoEyewearViolation(
    knownViolation,
    "clear",
  );
  assert.equal(knownViolation, false);
});

test("allows the guided fallback only for an available camera and unavailable model after acknowledgement", () => {
  const fallbackState = {
    cameraReady: true,
    modelUnavailable: true,
    userAcknowledgedRequirements: true,
    knownEyewearViolation: false,
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

test("never allows the guided fallback to override a known eyewear violation", () => {
  assert.equal(
    isVisaPhotoFallbackCaptureAllowed({
      cameraReady: true,
      modelUnavailable: true,
      userAcknowledgedRequirements: true,
      knownEyewearViolation: true,
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
  eyewear = "none",
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

  drawEyewear(pixels, eyewear);
  return pixels;
}

function drawEyewear(pixels, eyewear) {
  if (eyewear === "none") return;
  const leftEye = normalizedPixel(FACE.leftEye);
  const rightEye = normalizedPixel(FACE.rightEye);
  const frameColor = [35, 35, 35];
  const thickness = eyewear === "thin" || eyewear === "partial" ? 1 : 2;
  drawFrame(pixels, leftEye.x, leftEye.y, 8, 6, frameColor, thickness);
  if (eyewear !== "partial") {
    drawFrame(pixels, rightEye.x, rightEye.y, 8, 6, frameColor, thickness);
    drawHorizontalLine(
      pixels,
      Math.round((leftEye.y + rightEye.y) / 2),
      frameColor,
      thickness,
      leftEye.x + 8,
      rightEye.x - 8,
    );
  }
  if (eyewear === "sunglasses") {
    drawRect(pixels, leftEye.x - 6, leftEye.y - 4, leftEye.x + 6, leftEye.y + 4, [34, 39, 43]);
    drawRect(pixels, rightEye.x - 6, rightEye.y - 4, rightEye.x + 6, rightEye.y + 4, [34, 39, 43]);
  }
  if (eyewear === "glare") {
    drawRect(pixels, leftEye.x - 3, leftEye.y - 3, leftEye.x - 1, leftEye.y + 3, [250, 250, 248]);
    drawRect(pixels, rightEye.x + 1, rightEye.y - 3, rightEye.x + 3, rightEye.y + 3, [250, 250, 248]);
  }
}

function drawFrame(pixels, centerX, centerY, halfWidth, halfHeight, color, thickness) {
  for (let offset = 0; offset < thickness; offset += 1) {
    drawHorizontalLine(
      pixels,
      centerY - halfHeight + offset,
      color,
      1,
      centerX - halfWidth,
      centerX + halfWidth,
    );
    drawHorizontalLine(
      pixels,
      centerY + halfHeight - offset,
      color,
      1,
      centerX - halfWidth,
      centerX + halfWidth,
    );
    drawVerticalLine(
      pixels,
      centerX - halfWidth + offset,
      color,
      1,
      centerY - halfHeight,
      centerY + halfHeight,
    );
    drawVerticalLine(
      pixels,
      centerX + halfWidth - offset,
      color,
      1,
      centerY - halfHeight,
      centerY + halfHeight,
    );
  }
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
