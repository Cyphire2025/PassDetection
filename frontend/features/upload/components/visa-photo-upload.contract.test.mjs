import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./visa-photo-upload.tsx", import.meta.url),
  "utf8",
);

test("file selection prepares a preview without photo quality checks", () => {
  assert.match(source, /preparePublicUploadFile\(file/);
  assert.match(source, /setPreparedFile\(previewFile\)/);
  assert.match(source, /preparedFile && \(/);
  assert.match(source, /onCapture\(preparedFile\)/);
  assert.doesNotMatch(source, /verifyUploadedVisaPhoto|prewarmUploadedVisaPhotoDetector|visa-photo-upload-validation/);
});

test("the picker shows only the requested plain studio-photo instruction", () => {
  const translations = readFileSync(new URL("../config/instruction-translations.ts", import.meta.url), "utf8");
  assert.match(source, /UPLOAD_INSTRUCTIONS\[language\]\.visaWarning/);
  assert.match(translations, /visaWarning: "Upload only a studio-taken photo with a plain white background\."/);
  assert.doesNotMatch(source, /<strong[\s>]/);
  assert.doesNotMatch(source, /underline/);
  assert.doesNotMatch(source, /another phone or screen|printed or passport-size photograph/);
});

test("preview preparation is announced without claiming photo verification", () => {
  assert.match(source, /role="status"/);
  assert.match(source, /Preparing photo preview/);
  assert.match(source, /Preview your uploaded photo or PDF/);
  assert.doesNotMatch(source, /face, framing, lighting, sharpness/);
  assert.doesNotMatch(source, /checks passed|Verifying Visa Photo|quality_model_unavailable/);
  assert.doesNotMatch(source, /invoker\(|Out of bounds memory access/);
});

test("object URLs are replaced and revoked across retry and unmount", () => {
  assert.match(source, /URL\.revokeObjectURL\(previewUrlRef\.current\)/);
  assert.match(source, /URL\.createObjectURL\(file\)/);
  assert.match(source, /preparationRunRef\.current \+= 1/);
});
