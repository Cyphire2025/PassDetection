import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const cameraSource = readFileSync(
  new URL("./smart-camera.tsx", import.meta.url),
  "utf8",
);
const uploadFlowSource = readFileSync(
  new URL("./upload-flow.tsx", import.meta.url),
  "utf8",
);
const liveHookSource = readFileSync(
  new URL("../hooks/use-passport-frame-detection.ts", import.meta.url),
  "utf8",
);
const correctionSource = readFileSync(
  new URL("../services/passport-perspective-correction.ts", import.meta.url),
  "utf8",
);

test("passport uses high-quality manual capture then validates the exact outgoing JPEG", () => {
  const captureIndex = cameraSource.indexOf("captureBestCameraSource(");
  const normalizeIndex = cameraSource.indexOf(
    "normalizePassportCanvasCapture(",
    captureIndex,
  );
  const validateIndex = cameraSource.indexOf(
    "validatePassportFinalFile(",
    normalizeIndex,
  );
  const previewIndex = cameraSource.indexOf(
    "URL.createObjectURL(normalized.file)",
    validateIndex,
  );

  assert.ok(captureIndex >= 0);
  assert.ok(normalizeIndex > captureIndex);
  assert.ok(validateIndex > normalizeIndex);
  assert.ok(previewIndex > validateIndex);
  assert.match(cameraSource, /onClick=\{\(\) => void takePhoto\(\)\}/);
  assert.doesNotMatch(
    cameraSource,
    /passport-auto-capture|automatic capture|getPassportAutoCaptureProgress/,
  );
});

test("passport preview separates pass, confirmed borderline, and hard failure", () => {
  assert.match(cameraSource, /finalQuality\.outcome === "borderline"/);
  assert.match(cameraSource, /checked=\{borderlineConfirmed\}/);
  assert.match(cameraSource, /finalQuality\.confirmationPrompt/);
  assert.match(cameraSource, /finalQuality\.outcome !== "hard_failure"/);
  assert.match(cameraSource, /finalQuality\.outcome === "hard_failure"/);
});

test("camera front pages are not perspective-corrected again in mixed bundles", () => {
  assert.match(
    uploadFlowSource,
    /frontSource === "camera"\s*\?\s*file\s*:\s*\(await normalizePassportFile\(file\)\)\.file/,
  );
  assert.match(uploadFlowSource, /documentBundle\.frontSource \?\? "file"/);
});

test("only the lightweight rectangular live detector is active", () => {
  assert.match(liveHookSource, /detectRectangularPassportFrame\(/);
  assert.doesNotMatch(liveHookSource, /\bdetectPassportFrame\(/);
  assert.match(liveHookSource, /isCameraMotionStable\(/);
  assert.doesNotMatch(cameraSource, /usePassportBlurDetection\(/);
  assert.doesNotMatch(cameraSource, /usePassportGlareDetection\(/);
  assert.match(cameraSource, /Ready to capture/);
});

test("perspective correction does not invoke the dormant MRZ layout scorer", () => {
  assert.match(correctionSource, /isGenericCorrectionContentSafe\(/);
  assert.doesNotMatch(
    correctionSource,
    /\bisPassportCorrectionContentSafe\b|\bmrzScore\b|mrzRegionScore/,
  );
});
