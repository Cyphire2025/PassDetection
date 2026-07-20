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
  assert.match(source, /setModelError\(VISA_CAMERA_SAFE_RETRY_MESSAGE\)/);
  assert.match(
    source,
    /setInitializationAttempt\(\(current\) => current \+ 1\)/,
  );
});

test("guided fallback requires an explicit accessible acknowledgement", () => {
  assert.match(source, /htmlFor="visa-photo-fallback-confirmation"/);
  assert.match(source, /id="visa-photo-fallback-confirmation"/);
  assert.match(source, /type="checkbox"/);
  assert.match(source, /userAcknowledgedRequirements: fallbackAcknowledged/);
  assert.match(source, /takePhoto\("fallback"\)/);
});

test("the advanced strict Visa profile is active", () => {
  assert.match(
    source,
    /const ACTIVE_VISA_CAMERA_PROFILE: VisaCameraProfile = "strict"/,
  );
  assert.match(source, /\bevaluateVisaPhotoFacePlacement\b/);
  assert.match(source, /\bevaluateLiveVisaPhotoBackground\b/);
  assert.match(source, /clarity: evaluateVisaPhotoClarity\(/);
  assert.match(source, /\bisVisaPhotoFrameCaptureReady\b/);
  assert.match(source, /\bisVisaPhotoFaceStable\b/);
  assert.match(source, /\bupdateVisaReadinessHysteresis\b/);
  assert.match(source, /CAMERA_QUALITY_POLICY\.liveAnalysisIntervalMs/);
  assert.match(source, /const LIVE_FACE_DETECTION_CONFIDENCE = 0\.55;/);
  assert.match(
    source,
    /minDetectionConfidence: LIVE_FACE_DETECTION_CONFIDENCE/,
  );
  assert.doesNotMatch(source, /detect(?:s|ion)?Glasses|eyewearDetector/i);
});

test("the relaxed face and white-wall checks remain dormant behind the switch", () => {
  assert.match(source, /\bevaluateCompatibilityVisaPhotoFace\b/);
  assert.match(source, /\bevaluatePermissiveWhiteBackground\b/);
  assert.match(
    source,
    /ACTIVE_VISA_CAMERA_PROFILE === "relaxed"\s*\?\s*nextBackgroundStatus === "white"/,
  );
  assert.match(source, /Use one face and a plain white or off-white wall/);
  assert.match(source, /Checking the wall behind you/);
});

test("human guide is lifted above the bottom and crop side rails stay invisible", () => {
  assert.match(source, /data-testid="visa-photo-placement-guide"/);
  assert.match(source, /aspect-\[35\/45\]/);
  assert.match(source, /data-testid="visa-photo-output-crop"/);
  assert.match(source, /ref=\{guideRef\}/);
  assert.match(source, /aspect-\[2\/3\]/);
  assert.match(source, /bottom-\[15%\] h-\[88%\]/);
  assert.doesNotMatch(source, /\bborder-x\b/);
  assert.doesNotMatch(source, /\bborder-dashed\b/);
  assert.match(source, /preserveAspectRatio="xMidYMax meet"/);
  assert.match(source, /strokeDasharray="4 3"/);
  assert.doesNotMatch(source, /preserveAspectRatio="none"/);
  assert.match(source, /\bgetVisaOutputCrop\b/);
  assert.match(
    source,
    /CAMERA_QUALITY_POLICY\.visaOutputWidth\s*\/\s*CAMERA_QUALITY_POLICY\.visaOutputHeight/,
  );
});

test("saved Visa Photo includes a two-percent safety margin around the guide crop", () => {
  assert.match(source, /const VISA_CAPTURE_MARGIN_RATIO = 0\.02;/);
  assert.match(source, /const videoCrop = getVisaCaptureCrop\(video, guide\);/);
  assert.match(
    source,
    /const requestedScale = 1 \+ VISA_CAPTURE_MARGIN_RATIO \* 2;/,
  );
});

test("Visa Photo capture stays manual after the guide becomes ready", () => {
  assert.match(source, /onClick=\{\(\) => void takePhoto\(\)\}/);
  assert.match(source, /Ready to capture/);
  assert.match(source, /Tap the shutter to capture/);
  assert.doesNotMatch(source, /STABLE_CAPTURE_MS|takePhotoRef|Auto-captures/);
});

test("high-quality capture stays active and the relaxed bypass remains available", () => {
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

test("the active strict profile retains the exact-JPEG recheck", () => {
  assert.match(source, /detectFinalFaces\(decoded\.image\)/);
  assert.match(source, /\bevaluateFinalVisaPhoto\b/);
  assert.match(source, /\bevaluateFallbackFinalVisaPhoto\b/);
  assert.match(source, /const ANALYSIS_WIDTH = 96/);
  assert.match(source, /const ANALYSIS_HEIGHT = 144/);
});

test("capture drains live inference before touching or stopping the video", () => {
  assert.match(
    source,
    /stopAnalysis\(\);\s*if \(mode === "validated"\) \{\s*await waitForLiveAnalysis\(\);\s*\}\s*const videoCrop = getVisaCaptureCrop/,
  );
  assert.match(
    source,
    /const detections = await detectFinalFaces\(decoded\.image\);[\s\S]*?stopStream\(\);/,
  );
  assert.doesNotMatch(
    source,
    /stopStream\(\);\s*setIsCameraReady\(false\);\s*const \{ blob \}/,
  );
});

test("all live and final MediaPipe sends use one serialized queue", () => {
  assert.match(
    source,
    /inferenceQueue\.run\(\(\) => detector\.send\(\{ image \}\)\)/,
  );
  assert.match(
    source,
    /inferenceQueue\.run\(\(\) => detector\.send\(\{ image: video \}\)\)/,
  );
  assert.match(
    source,
    /const inferenceQueue = detectorInferenceQueueRef\.current;[\s\S]*?await inferenceQueue\.drain\(\);/,
  );
  assert.match(
    source,
    /const detectionsPromise = new Promise<Detection\[]>[\s\S]*?const detections = await detectionsPromise;[\s\S]*?await finalSend;[\s\S]*?await inferenceQueue\.drain\(\);\s*return detections;/,
  );
});

test("low-level detector failures restart checks with a safe client message", () => {
  assert.match(source, /new VisaDetectorInferenceError\(error\)/);
  assert.match(
    source,
    /detectorError\?\.message[\s\S]*?setInitializationAttempt\(\(current\) => current \+ 1\)/,
  );
  assert.doesNotMatch(
    source,
    /setProcessingError\(error instanceof Error \? error\.message/,
  );
});

test("camera tracks have a bounded drain path that faults a stalled detector", () => {
  assert.match(source, /const CAMERA_STOP_DRAIN_TIMEOUT_MS = 1_500;/);
  assert.match(
    source,
    /const drained = await waitForVisaInferenceDrain\([\s\S]*?CAMERA_STOP_DRAIN_TIMEOUT_MS,[\s\S]*?\);/,
  );
  assert.match(
    source,
    /if \(!drained && detectorGeneration === detectorGenerationRef\.current\)[\s\S]*?detectorRef\.current = null;[\s\S]*?stopStream\(\);/,
  );
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
