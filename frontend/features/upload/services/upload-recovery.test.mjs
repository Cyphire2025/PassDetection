import assert from "node:assert/strict";
import test from "node:test";
import {
  applyUploadReconciliation,
  createUploadRecoveryRecord,
  parseUploadRecoveryRecord,
  serializeUploadRecoveryRecord,
  uploadRecoveryTarget,
} from "./upload-recovery.ts";

const VALID_UPLOAD_KEY = "upload-attempt-1234567890abcdef1234567890";

test("round-trips only the upload idempotency key and durable submission id", () => {
  const record = createUploadRecoveryRecord(
    VALID_UPLOAD_KEY,
    "submission-456",
  );

  assert.deepEqual(
    parseUploadRecoveryRecord(serializeUploadRecoveryRecord(record)),
    record,
  );
  assert.deepEqual(Object.keys(record).sort(), [
    "idempotencyKey",
    "submissionId",
    "version",
  ]);
});

test("supports an upload attempt before the backend submission is known", () => {
  assert.deepEqual(
    createUploadRecoveryRecord(VALID_UPLOAD_KEY),
    {
      version: 1,
      idempotencyKey: VALID_UPLOAD_KEY,
      submissionId: null,
    },
  );
});

test("server commit plus lost response reloads by key before asking for files", () => {
  const afterLostResponse = parseUploadRecoveryRecord(
    serializeUploadRecoveryRecord(
      createUploadRecoveryRecord(VALID_UPLOAD_KEY),
    ),
  );
  assert.ok(afterLostResponse);
  assert.deepEqual(uploadRecoveryTarget(afterLostResponse), {
    kind: "attempt",
    idempotencyKey: VALID_UPLOAD_KEY,
  });

  const reconciled = applyUploadReconciliation(
    afterLostResponse,
    "durable-submission-456",
  );
  assert.deepEqual(uploadRecoveryTarget(reconciled), {
    kind: "submission",
    submissionId: "durable-submission-456",
  });
});

test("unknown-key and retry reconciliation preserve the exact opaque key", () => {
  const record = createUploadRecoveryRecord(VALID_UPLOAD_KEY);
  const unknown = applyUploadReconciliation(record, null);
  const retried = applyUploadReconciliation(unknown, null);

  assert.equal(unknown, record);
  assert.equal(retried, record);
  assert.deepEqual(uploadRecoveryTarget(retried), {
    kind: "attempt",
    idempotencyKey: VALID_UPLOAD_KEY,
  });
});

test("duplicate reconciliation responses remain stable and contain no PII or images", () => {
  const record = createUploadRecoveryRecord(VALID_UPLOAD_KEY);
  const first = applyUploadReconciliation(record, "durable-submission-456");
  const duplicate = applyUploadReconciliation(
    first,
    "durable-submission-456",
  );

  assert.deepEqual(duplicate, first);
  assert.deepEqual(Object.keys(duplicate).sort(), [
    "idempotencyKey",
    "submissionId",
    "version",
  ]);
  for (const forbidden of [
    "clientName",
    "passportNumber",
    "image",
    "file",
    "extractedFields",
  ]) {
    assert.equal(forbidden in duplicate, false);
  }
});

test("rejects corrupt, obsolete, and oversized recovery state", () => {
  for (const value of [
    null,
    "",
    "not-json",
    "{}",
    JSON.stringify({ version: 2, idempotencyKey: VALID_UPLOAD_KEY, submissionId: null }),
    JSON.stringify({ version: 1, idempotencyKey: "short", submissionId: null }),
    JSON.stringify({ version: 1, idempotencyKey: "unsafe key value", submissionId: null }),
    JSON.stringify({ version: 1, idempotencyKey: "x".repeat(129), submissionId: null }),
    JSON.stringify({ version: 1, idempotencyKey: VALID_UPLOAD_KEY }),
    JSON.stringify({ version: 1, idempotencyKey: VALID_UPLOAD_KEY, submissionId: 42 }),
  ]) {
    assert.equal(parseUploadRecoveryRecord(value), null);
  }
});
