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

test("validates the exact re-encoded JPEG with the active final quality rules", () => {
  assert.match(source, /const exactPhoto = await decodeVisaPhoto\(blob\)/);
  assert.match(source, /detectVisaPhotoFaces\(exactPhoto\.image\)/);
  assert.match(source, /evaluateFinalVisaPhoto\(\{/);
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

test("legacy MediaPipe work is serialized and never closed during an active call", () => {
  assert.match(source, /let validationTail: Promise<void> = Promise\.resolve\(\)/);
  assert.match(source, /validationTail\.then\(/);
  assert.match(source, /const safeToClose =/);
  assert.match(source, /settlesWithin\(/);
  assert.match(source, /if \(safeToClose\)/);
  assert.match(source, /Uploaded Visa Photo detector did not settle safely/);
});

test("uploaded-photo failures use replacement guidance rather than camera instructions", () => {
  assert.match(source, /Choose a clear original studio photo/);
  assert.match(source, /Choose a studio photo containing only the applicant/);
  assert.match(source, /plain white background/);
  assert.doesNotMatch(
    source.slice(
      source.indexOf("export function uploadedVisaPhotoFailureMessage"),
      source.indexOf("export function visaPhotoUploadRejectionReason"),
    ),
    /retake/i,
  );
});
