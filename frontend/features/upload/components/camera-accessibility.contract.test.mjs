import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const passportCameraSource = readFileSync(
  new URL("./smart-camera.tsx", import.meta.url),
  "utf8",
);
const visaPhotoCameraSource = readFileSync(
  new URL("./visa-selfie-camera.tsx", import.meta.url),
  "utf8",
);

test("camera surfaces expose modal names and a single announced instruction", () => {
  for (const source of [passportCameraSource, visaPhotoCameraSource]) {
    assert.match(source, /role="dialog"/);
    assert.match(source, /aria-modal="true"/);
    assert.match(source, /aria-labelledby=/);
    assert.match(source, /aria-live=/);
    assert.match(source, /aria-atomic="true"/);
  }
});

test("hidden tabs release camera streams and restart only after becoming visible", () => {
  for (const source of [passportCameraSource, visaPhotoCameraSource]) {
    assert.match(
      source,
      /document\.addEventListener\("visibilitychange", handleVisibilityChange\)/,
    );
    assert.match(source, /document\.visibilityState === "hidden"/);
    assert.match(source, /visibilityPausedRef\.current = true/);
    assert.match(source, /visibilityPausedRef\.current = false/);
  }
  assert.match(passportCameraSource, /stopCamera\(\)/);
  assert.match(visaPhotoCameraSource, /stopStream\(\)/);
});

test("passport capture is manual after all scanner checks pass", () => {
  assert.match(
    passportCameraSource,
    /All checks passed - tap the shutter button to capture/,
  );
  assert.match(passportCameraSource, /onClick=\{\(\) => void takePhoto\(\)\}/);
  assert.doesNotMatch(
    passportCameraSource,
    /passport-auto-capture|automatic capture|getPassportAutoCaptureProgress/,
  );
});

test("Visa Photo preview releases the live camera before acceptance or retake", () => {
  const capturedFileStart = visaPhotoCameraSource.indexOf("const file = new File");
  const previewStart = visaPhotoCameraSource.indexOf(
    "setCapturedPreview(URL.createObjectURL(file))",
    capturedFileStart,
  );
  const stopStream = visaPhotoCameraSource.indexOf("stopStream();", capturedFileStart);

  assert.ok(capturedFileStart >= 0);
  assert.ok(stopStream > capturedFileStart);
  assert.ok(previewStart > stopStream);
  assert.match(
    visaPhotoCameraSource,
    /const retake = \(\) => \{[\s\S]*?setCameraAttempt\(\(current\) => current \+ 1\)/,
  );
});
