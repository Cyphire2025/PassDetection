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

test("the live camera uses only the compatibility face and wall checks for readiness", () => {
  assert.doesNotMatch(source, /eyewear/i);
  assert.doesNotMatch(source, /glasses/i);
  assert.match(source, /\bevaluateCompatibilityVisaPhotoFace\b/);
  assert.match(source, /\bevaluatePermissiveWhiteBackground\b/);
  assert.match(source, /currentFrameReady = nextBackgroundStatus === "white";/);
  assert.match(source, /clarity: evaluateVisaPhotoClarity\(/);
  assert.doesNotMatch(source, /\bisVisaPhotoFrameCaptureReady\b/);
  assert.doesNotMatch(source, /\bevaluateWhiteBackground\b/);
});
