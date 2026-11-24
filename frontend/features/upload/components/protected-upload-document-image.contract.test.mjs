import assert from "node:assert/strict";
import test from "node:test";
import { readUploadSource } from "./current-upload-source.contract-helper.mjs";
const source = readUploadSource("./fresh-document-preview.tsx");

test("current private draft previews fetch authenticated blobs and release resources", () => {
  assert.match(source, /queuedPrivatePreview\(\(\) => api\.document\(id, controller\.signal\)/);
  assert.match(source, /URL\.createObjectURL\(blob\)/);
  assert.match(source, /controller\.abort\(\)/);
  assert.match(source, /URL\.revokeObjectURL\(objectUrl\)/);
  assert.match(source, /blob\.size > 20 \* 1024 \* 1024/);
  assert.doesNotMatch(source, /<img[^>]+https?:\/\//);
});

test("current preview loading, error and retry are distinct accessible states", () => {
  assert.match(source, /role="status"[\s\S]*?Loading document/);
  assert.match(source, /role="alert"/);
  assert.match(source, /Retry preview/);
  assert.match(source, /setAttempt\(\(value\) => value \+ 1\)/);
  assert.match(source, /return \(\) => observer\.disconnect\(\)/);
});
