import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./visa-photo-upload-validation.ts", import.meta.url),
  "utf8",
);

test("normalizes every accepted upload to the existing exact 2:3 output", () => {
  assert.match(
    source,
    /const targetRatio = CAMERA_QUALITY_POLICY\.visaOutputWidth\s*\/ CAMERA_QUALITY_POLICY\.visaOutputHeight/,
  );
  assert.match(source, /centeredVisaPhotoCrop\(/);
  assert.match(source, /CAMERA_QUALITY_POLICY\.visaOutputWidth/);
  assert.match(source, /CAMERA_QUALITY_POLICY\.visaOutputHeight/);
  assert.match(source, /encodeVisaJpegUnderLimit\(/);
  assert.match(source, /CAMERA_QUALITY_POLICY\.maxVisaOutputBytes/);
});

test("validates only the background of the exact re-encoded JPEG", () => {
  assert.match(source, /const exactPhoto = await decodeVisaPhoto\(blob\)/);
  assert.match(source, /evaluateWhiteBackground\(/);
  assert.match(source, /evaluateUploadedVisaPhotoBackground\(background\)/);
  assert.match(source, /if \(!background\.isLightNeutral\)/);
  assert.doesNotMatch(source, /detectVisaPhotoFaces|evaluateFinalVisaPhoto/);
  assert.doesNotMatch(source, /faceCount|facePlacement|clarity/);
  assert.match(source, /const ANALYSIS_WIDTH = 96/);
  assert.match(source, /const ANALYSIS_HEIGHT = 144/);
  assert.match(source, /return \{[\s\S]*?validation,[\s\S]*?\};/);
});

test("source validation mirrors production limits and rejects weak inputs early", () => {
  assert.match(source, /VISA_PHOTO_UPLOAD_MAX_BYTES = 10 \* 1024 \* 1024/);
  assert.match(source, /VISA_PHOTO_UPLOAD_MAX_PIXELS = 24_000_000/);
  assert.match(source, /const MIN_SOURCE_WIDTH = 300/);
  assert.match(source, /const MIN_SOURCE_HEIGHT = 400/);
  assert.match(source, /if \(width > height\)/);
});

test("the upload path does not initialize the live-camera MediaPipe runtime", () => {
  assert.doesNotMatch(source, /@mediapipe\/face_detection/);
  assert.doesNotMatch(source, /FaceDetection|detector\.send|detector\.initialize/);
});

test("uploaded-photo failures mention only the white-background requirement", () => {
  assert.match(source, /background is not white or off-white/);
  assert.match(source, /plain white background/);
  assert.doesNotMatch(source, /face is too small|More than one face|face is not centred/i);
  assert.doesNotMatch(
    source.slice(
      source.indexOf("export function uploadedVisaPhotoFailureMessage"),
      source.indexOf("export function visaPhotoUploadRejectionReason"),
    ),
    /retake/i,
  );
});
