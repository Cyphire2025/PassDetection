import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./visa-selfie-camera.tsx", import.meta.url),
  "utf8",
);

test("a stalled face-model inference becomes a recoverable unavailable state", () => {
  assert.match(source, /const ANALYSIS_TIMEOUT_MS = 6_000;/);
  assert.match(source, /window\.setTimeout\(\(\) => \{\s*failAnalysis\(/);
  assert.match(source, /setModelError\("Live photo checks stopped unexpectedly\."\)/);
});

test("guided fallback requires an explicit accessible acknowledgement", () => {
  assert.match(source, /htmlFor="visa-photo-fallback-confirmation"/);
  assert.match(source, /id="visa-photo-fallback-confirmation"/);
  assert.match(source, /type="checkbox"/);
  assert.match(source, /userAcknowledgedRequirements: fallbackAcknowledged/);
  assert.match(source, /takePhoto\("fallback"\)/);
});

test("the restored relaxed profile checks one face and a white or off-white wall", () => {
  assert.match(
    source,
    /const ACTIVE_VISA_CAMERA_PROFILE: VisaCameraProfile = "relaxed"/,
  );
  assert.match(source, /\bevaluateCompatibilityVisaPhotoFace\b/);
  assert.match(source, /\bevaluatePermissiveWhiteBackground\b/);
  assert.match(
    source,
    /ACTIVE_VISA_CAMERA_PROFILE === "relaxed"\s*\?\s*nextBackgroundStatus === "white"/,
  );
  assert.match(source, /Use one face and a plain white or off-white wall/);
  assert.match(source, /Checking the wall behind you/);
  assert.match(source, /Use a plain white or off-white wall/);
  assert.doesNotMatch(source, /detect(?:s|ion)?Glasses|eyewearDetector/i);
});

test("the newer strict checks remain dormant behind the profile switch", () => {
  assert.match(source, /\bevaluateVisaPhotoFacePlacement\b/);
  assert.match(source, /\bevaluateLiveVisaPhotoBackground\b/);
  assert.match(source, /clarity: evaluateVisaPhotoClarity\(/);
  assert.match(source, /\bisVisaPhotoFrameCaptureReady\b/);
  assert.match(source, /\bisVisaPhotoFaceStable\b/);
  assert.match(source, /\bupdateRollingCameraReadiness\b/);
  assert.match(source, /CAMERA_QUALITY_POLICY\.liveAnalysisIntervalMs/);
  assert.match(source, /const LIVE_FACE_DETECTION_CONFIDENCE = 0\.55;/);
  assert.match(
    source,
    /minDetectionConfidence: LIVE_FACE_DETECTION_CONFIDENCE/,
  );
});

test("human-proportioned placement guide exposes the exact inner output crop", () => {
  assert.match(source, /data-testid="visa-photo-placement-guide"/);
  assert.match(source, /aspect-\[35\/45\]/);
  assert.match(source, /data-testid="visa-photo-output-crop"/);
  assert.match(source, /aspect-\[2\/3\]/);
  assert.match(source, /preserveAspectRatio="xMidYMax meet"/);
  assert.doesNotMatch(source, /preserveAspectRatio="none"/);
  assert.match(source, /\bgetVisaOutputCrop\b/);
  assert.match(
    source,
    /CAMERA_QUALITY_POLICY\.visaOutputWidth\s*\/\s*CAMERA_QUALITY_POLICY\.visaOutputHeight/,
  );
});

test("Visa Photo capture stays manual after the guide becomes ready", () => {
  assert.match(source, /onClick=\{\(\) => void takePhoto\(\)\}/);
  assert.match(source, /Ready to capture/);
  assert.match(source, /Tap the shutter to capture/);
  assert.doesNotMatch(source, /STABLE_CAPTURE_MS|takePhotoRef|Auto-captures/);
});

test("high-quality capture stays active while strict final validation is bypassed", () => {
  assert.match(source, /\bcaptureBestCameraSource\b/);
  assert.match(source, /CAMERA_QUALITY_POLICY\.visaOutputWidth/);
  assert.match(source, /CAMERA_QUALITY_POLICY\.visaOutputHeight/);
  assert.match(source, /\bencodeVisaJpegUnderLimit\b/);
  assert.match(
    source,
    /if \(ACTIVE_VISA_CAMERA_PROFILE === "relaxed"\) \{[\s\S]*?setCapturedFile\(file\);[\s\S]*?setCapturedPreview\(URL\.createObjectURL\(file\)\);[\s\S]*?return;/,
  );
  assert.match(
    source,
    /const canUseCapturedPhoto = ACTIVE_VISA_CAMERA_PROFILE === "relaxed"/,
  );
});

test("strict exact-JPEG recheck remains available for later refinement", () => {
  assert.match(source, /detectFinalFaces\(decoded\.image\)/);
  assert.match(source, /\bevaluateFinalVisaPhoto\b/);
  assert.match(source, /\bevaluateFallbackFinalVisaPhoto\b/);
  assert.match(source, /const ANALYSIS_WIDTH = 96/);
  assert.match(source, /const ANALYSIS_HEIGHT = 144/);
});

test("borderline preview needs confirmation and hard failure never exposes Use", () => {
  assert.match(source, /id="visa-photo-borderline-confirmation"/);
  assert.match(source, /checked=\{borderlineConfirmed\}/);
  assert.match(
    source,
    /finalValidation[\s\S]*?finalValidation\.outcome !== "hard_failure"/,
  );
  assert.match(
    source,
    /finalValidation\?\.outcome === "borderline"[\s\S]*?!borderlineConfirmed/,
  );
});
