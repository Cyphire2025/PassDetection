import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { currentUploadSources } from "../components/current-upload-source.contract-helper.mjs";
const apiSource = readFileSync(new URL("./upload.api.ts", import.meta.url), "utf8");

test("retained reconciliation API is a key-only PUT and never rebuilds the upload form", () => {
  const start = apiSource.indexOf("reconcileUpload: async"), end = apiSource.indexOf("getUploadStatus: async", start);
  const method = apiSource.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.match(method, /apiClient\.put<UploadReconciliationResult>/);
  assert.match(method, /upload_idempotency_key: uploadIdempotencyKey/);
  assert.match(method, /uploadSessionHeaders\(uploadIdempotencyKey\)/);
  assert.doesNotMatch(method, /FormData|client_name|passportBackFile|File/);
});

test("retained public follow-up APIs use the private credential rather than a submission UUID", () => {
  for (const methodName of ["getUploadStatus: async", "scanAgain: async", "getUploadDocument: async", "discardUpload: async", "submitClientReview: async"]) {
    const start = apiSource.indexOf(methodName), end = apiSource.indexOf("\n  },", start);
    assert.ok(start >= 0, methodName);
    assert.match(apiSource.slice(start, end), /uploadSessionHeaders\(uploadSessionId\)/, methodName);
    assert.doesNotMatch(apiSource.slice(start, end), /uploadSessionHeaders\(submissionId\)/, methodName);
  }
});

test("current private draft requests bind the member session and preserve revision/idempotency", () => {
  assert.match(currentUploadSources.api, /"X-Upload-Session-ID": sessionId/);
  assert.match(currentUploadSources.api, /expected_revision: revision, idempotency_key: key/);
  assert.match(currentUploadSources.api, /draftUploadBody\(file, revision, key, expectedAssetId\)/);
  assert.match(currentUploadSources.draft, /member\.submissionKey/);
});
