export interface UploadRecoveryRecord {
  version: 1;
  idempotencyKey: string;
  submissionId: string | null;
}

export type UploadRecoveryTarget =
  | { kind: "submission"; submissionId: string }
  | { kind: "attempt"; idempotencyKey: string };

const MAX_IDEMPOTENCY_KEY_LENGTH = 128;
const MAX_SUBMISSION_ID_LENGTH = 128;
const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{32,128}$/;

export function createUploadRecoveryRecord(
  idempotencyKey: string,
  submissionId: string | null = null,
): UploadRecoveryRecord {
  return {
    version: 1,
    idempotencyKey,
    submissionId,
  };
}

export function parseUploadRecoveryRecord(
  serialized: string | null,
): UploadRecoveryRecord | null {
  if (!serialized) return null;

  try {
    const value: unknown = JSON.parse(serialized);
    if (!value || typeof value !== "object") return null;
    const candidate = value as Partial<UploadRecoveryRecord>;
    if (candidate.version !== 1) return null;
    if (
      typeof candidate.idempotencyKey !== "string"
      || candidate.idempotencyKey.length > MAX_IDEMPOTENCY_KEY_LENGTH
      || !IDEMPOTENCY_KEY_PATTERN.test(candidate.idempotencyKey)
    ) {
      return null;
    }
    if (
      candidate.submissionId !== null
      && (
        typeof candidate.submissionId !== "string"
        || candidate.submissionId.length < 1
        || candidate.submissionId.length > MAX_SUBMISSION_ID_LENGTH
      )
    ) {
      return null;
    }
    return {
      version: 1,
      idempotencyKey: candidate.idempotencyKey,
      submissionId: candidate.submissionId,
    };
  } catch {
    return null;
  }
}

export function serializeUploadRecoveryRecord(record: UploadRecoveryRecord) {
  return JSON.stringify(record);
}

export function uploadRecoveryTarget(
  record: UploadRecoveryRecord,
): UploadRecoveryTarget {
  if (record.submissionId) {
    return { kind: "submission", submissionId: record.submissionId };
  }
  return { kind: "attempt", idempotencyKey: record.idempotencyKey };
}

export function applyUploadReconciliation(
  record: UploadRecoveryRecord,
  submissionId: string | null,
): UploadRecoveryRecord {
  if (!submissionId) return record;
  return createUploadRecoveryRecord(record.idempotencyKey, submissionId);
}
