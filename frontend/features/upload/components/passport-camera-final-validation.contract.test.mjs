import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { currentUploadSources } from "./current-upload-source.contract-helper.mjs";
import { passportCameraSource as cameraSource } from "./passport-camera-source.contract-helper.mjs";
import { passportNormalizationSource as correctionSource } from "./passport-normalization-source.contract-helper.mjs";
const liveHookSource = readFileSync(
  new URL("../hooks/use-passport-frame-detection.ts", import.meta.url),
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

test("already validated camera captures enter the current private draft unchanged", () => {
  assert.match(currentUploadSources.selection, /source === "file" \? await preparePublicUploadFile[\s\S]*?: file;/);
  assert.match(currentUploadSources.selection, /state\.upload\(side, ready\)/);
  assert.match(currentUploadSources.documents, /onCapture=\{\(file\) => startUpload\(camera, file, "camera"\)\}/);
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
