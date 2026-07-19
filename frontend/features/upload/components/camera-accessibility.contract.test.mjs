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
    /Ready to capture/,
  );
  assert.match(passportCameraSource, /onClick=\{\(\) => void takePhoto\(\)\}/);
  assert.doesNotMatch(
    passportCameraSource,
    /passport-auto-capture|automatic capture|getPassportAutoCaptureProgress/,
  );
});

test("passport scanner uses light dashboard chrome and clear manual-capture states", () => {
  assert.match(passportCameraSource, /bg-slate-50 text-slate-950/);
  assert.match(passportCameraSource, /border-slate-200 bg-white/);
  assert.match(passportCameraSource, /border-emerald-500/);
  assert.match(passportCameraSource, /Tap to capture/);
  assert.match(passportCameraSource, /Align the passport to enable capture/);
});

test("Visa Photo preview releases the live camera before acceptance or retake", () => {
  const captureStart = visaPhotoCameraSource.indexOf(
    "const source = await captureBestCameraSource",
  );
  const sourceDraw = visaPhotoCameraSource.indexOf(
    "context.drawImage(",
    captureStart,
  );
  const stopStream = visaPhotoCameraSource.indexOf(
    "stopStream();",
    sourceDraw,
  );
  const previewStart = visaPhotoCameraSource.indexOf(
    "setCapturedPreview(URL.createObjectURL(file))",
    stopStream,
  );

  assert.ok(captureStart >= 0);
  assert.ok(sourceDraw > captureStart);
  assert.ok(stopStream > sourceDraw);
  assert.ok(previewStart > stopStream);
  assert.match(
    visaPhotoCameraSource,
    /const retake = \(\) => \{[\s\S]*?setCameraAttempt\(\(current\) => current \+ 1\)/,
  );
});

test("Visa Photo capture remains manual and only green means ready", () => {
  assert.match(visaPhotoCameraSource, /Ready to capture/);
  assert.match(
    visaPhotoCameraSource,
    /onClick=\{\(\) => void takePhoto\(\)\}/,
  );
  assert.doesNotMatch(
    visaPhotoCameraSource,
    /STABLE_CAPTURE_MS|takePhotoRef|Auto-captures/,
  );
});
