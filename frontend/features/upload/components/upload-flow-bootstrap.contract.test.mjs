import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../services/upload-flow-bootstrap.ts", import.meta.url),
  "utf8",
);

test("bootstrap binds the stored opaque key before any recovery lookup", () => {
  const readRecovery = source.indexOf("readUploadRecoveryRecord(token)");
  const bindKey = source.indexOf(
    "actions.setSingleUploadIdempotencyKey(recovery.idempotencyKey)",
    readRecovery,
  );
  const restoreStatus = source.indexOf("await uploadApi.getUploadStatus", bindKey);

  assert.ok(readRecovery >= 0);
  assert.ok(bindKey > readRecovery);
  assert.ok(restoreStatus > bindKey);
  assert.match(
    source,
    /getUploadStatus\(\s*token,\s*submissionId,\s*recovery\.idempotencyKey/,
  );
});

test("response-loss reconciliation precedes file selection and preserves the key", () => {
  const target = source.indexOf("const recoveryTarget = uploadRecoveryTarget");
  const reconcile = source.indexOf("await uploadApi.reconcileUpload", target);
  const apply = source.indexOf("applyUploadReconciliation(", reconcile);
  const persist = source.indexOf(
    "writeUploadRecoveryRecord(token, reconciledRecovery)",
    apply,
  );
  const restore = source.indexOf(
    "await restoreSubmission(reconciledRecovery.submissionId)",
    persist,
  );
  const fileSelection = source.indexOf('actions.setStep("MODE_SELECT")', restore);

  assert.ok(target >= 0);
  assert.ok(reconcile > target);
  assert.ok(apply > reconcile);
  assert.ok(persist > apply);
  assert.ok(restore > persist);
  assert.ok(fileSelection > restore);
});

test("durable submissions restore before short-lived qualifier choices", () => {
  const durableRestore = source.indexOf("if (recovery.submissionId)");
  const qualifierRestore = source.indexOf(
    "const storedToken = readQualifierSelectionToken(token)",
    durableRestore,
  );
  const durableBlock = source.slice(durableRestore, qualifierRestore);

  assert.ok(durableRestore >= 0);
  assert.ok(qualifierRestore > durableRestore);
  assert.match(durableBlock, /actions\.setFlowMode\("single"\)/);
  assert.match(durableBlock, /await restoreSubmission\(recovery\.submissionId\)/);
});

test("missing durable data rotates the key while transient failures stay fail-closed", () => {
  assert.match(source, /if \(isMissingSavedSubmissionError\(restoreError\)\)/);
  assert.match(
    source,
    /const replacement = createUploadRecoveryRecord\(createIdempotencyKey\(\)\)/,
  );
  assert.match(
    source,
    /a new upload has not been started\.[\s\S]*?actions\.setStep\("RECOVERY_ERROR"\)/,
  );
  assert.match(source, /if \(isPermanentQualifierRestoreError\(restoreError\)\)/);
  assert.match(
    source,
    /it has not been discarded\.[\s\S]*?actions\.setStep\("RECOVERY_ERROR"\)/,
  );
});

test("every awaited recovery branch checks cancellation before state transitions", () => {
  assert.match(
    source,
    /await uploadApi\.getUploadStatus[\s\S]*?if \(isCancelled\(\)\) return;/,
  );
  assert.match(
    source,
    /await uploadApi\.reconcileUpload[\s\S]*?if \(isCancelled\(\)\) return;/,
  );
  assert.match(
    source,
    /await uploadLinksApi\.getQualifierSelection[\s\S]*?if \(isCancelled\(\)\) return;/,
  );
});
