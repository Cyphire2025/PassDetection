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

test("known eyewear keeps fallback locked and gives a retry instruction", () => {
  assert.match(
    source,
    /setEyewearStatus\(\s*knownEyewearViolationRef\.current \? "detected" : "checking"/,
  );
  assert.match(
    source,
    /Guided fallback stays locked until stable clear checks pass\./,
  );
  assert.match(source, /\{!knownEyewearViolation && \(/);
});
