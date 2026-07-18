import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./protected-upload-document-image.tsx", import.meta.url),
  "utf8",
);

test("protected previews use credentialed blob requests and release resources", () => {
  assert.match(
    source,
    /uploadApi\.getUploadDocument\(\s*token,\s*submissionId,\s*documentType,\s*uploadSessionId,/,
  );
  assert.match(source, /URL\.createObjectURL\(blob\)/);
  assert.match(source, /controller\.abort\(\)/);
  assert.match(source, /URL\.revokeObjectURL\(activeObjectUrl\)/);
  assert.doesNotMatch(source, /<img[^>]+https?:\/\//);
});

test("protected preview loading and failures have distinct accessible states", () => {
  assert.match(source, /role="status"[\s\S]*?Loading secure preview/);
  assert.match(source, /role="alert"[\s\S]*?Secure preview is unavailable/);
  assert.match(source, />\s*Retry preview\s*<\/button>/);
  assert.match(
    source,
    /onClick=\{\(\) => setRetryVersion\(\(version\) => version \+ 1\)\}/,
  );
});
