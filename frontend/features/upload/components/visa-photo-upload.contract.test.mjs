import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./visa-photo-upload.tsx", import.meta.url),
  "utf8",
);

test("file selection runs the shared strict verifier before a Visa Photo can be used", () => {
  assert.match(source, /verifyUploadedVisaPhoto\(file\)/);
  assert.match(source, /result\.validation\.outcome !== "pass"/);
  assert.match(source, /setVerifiedFile\(result\.file\)/);
  assert.match(source, /verifiedFile && \(/);
  assert.match(source, /onCapture\(verifiedFile\)/);
});

test("the picker clearly prohibits photos of screens and printed photographs", () => {
  assert.match(source, /studio-taken photo with a plain white background/);
  assert.match(source, /another phone or screen/);
  assert.match(source, /printed or passport-size photograph/);
  assert.match(source, /strictly prohibited/);
  assert.match(source, /may delay your application/);
});

test("checking is announced and raw detector failures are not displayed", () => {
  assert.match(source, /role="status"/);
  assert.match(source, /Verifying Visa Photo/);
  assert.match(source, /face, framing, lighting, sharpness, and background/);
  assert.match(source, /quality_model_unavailable/);
  assert.doesNotMatch(source, /invoker\(|Out of bounds memory access/);
});

test("object URLs are replaced and revoked across retry and unmount", () => {
  assert.match(source, /URL\.revokeObjectURL\(previewUrlRef\.current\)/);
  assert.match(source, /URL\.createObjectURL\(file\)/);
  assert.match(source, /validationRunRef\.current \+= 1/);
});
