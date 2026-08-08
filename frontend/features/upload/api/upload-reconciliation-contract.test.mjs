import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { uploadFlowSource as flowSource } from "../components/upload-flow-source.contract-helper.mjs";

const apiSource = readFileSync(
  new URL("./upload.api.ts", import.meta.url),
  "utf8",
);
test("reconciliation is a key-only PUT and never rebuilds the upload form", () => {
  const start = apiSource.indexOf("reconcileUpload: async");
  const end = apiSource.indexOf("getUploadStatus: async", start);
  const method = apiSource.slice(start, end);

  assert.ok(start >= 0);
  assert.ok(end > start);
  assert.match(method, /apiClient\.put<UploadReconciliationResult>/);
  assert.match(method, /upload_idempotency_key: uploadIdempotencyKey/);
  assert.match(method, /uploadSessionHeaders\(uploadIdempotencyKey\)/);
  assert.doesNotMatch(method, /FormData|client_name|passportBackFile|File/);
});

test("reload reconciles a key-only record before returning to file selection", () => {
  const target = flowSource.indexOf("const recoveryTarget = uploadRecoveryTarget");
  const reconcile = flowSource.indexOf(
    "await uploadApi.reconcileUpload",
    target,
  );
  const restore = flowSource.indexOf(
    "await restoreSubmission(reconciledRecovery.submissionId)",
    reconcile,
  );
  const fileSelection = flowSource.indexOf('setStep("MODE_SELECT")', restore);

  assert.ok(target >= 0);
  assert.ok(reconcile > target);
  assert.ok(restore > reconcile);
  assert.ok(fileSelection > restore);
});

test("public follow-ups use the private upload credential, never the path UUID", () => {
  for (const methodName of [
    "getUploadStatus: async",
    "scanAgain: async",
    "getUploadDocument: async",
    "discardUpload: async",
    "submitClientReview: async",
  ]) {
    const start = apiSource.indexOf(methodName);
    const end = apiSource.indexOf("\n  },", start);
    const method = apiSource.slice(start, end);

    assert.ok(start >= 0, methodName);
    assert.match(
      method,
      /uploadSessionHeaders\(uploadSessionId\)/,
      methodName,
    );
    assert.doesNotMatch(
      method,
      /uploadSessionHeaders\(submissionId\)/,
      methodName,
    );
  }

  assert.match(
    flowSource,
    /getUploadStatus\(\s*token,\s*submissionId,\s*recovery\.idempotencyKey/,
  );
  assert.match(
    flowSource,
    /uploadSessionId: singleUploadIdempotencyKey/,
  );
  assert.match(
    flowSource,
    /uploadSessionId: member\.uploadIdempotencyKey/,
  );
  assert.doesNotMatch(
    flowSource,
    /src=\{API_ENDPOINTS\.passports\.upload(Document)?Image/,
  );
  const keyFactory = flowSource.slice(
    flowSource.indexOf("function createIdempotencyKey()"),
  );
  assert.match(keyFactory, /crypto\.getRandomValues/);
  assert.doesNotMatch(keyFactory, /Math\.random/);
});
