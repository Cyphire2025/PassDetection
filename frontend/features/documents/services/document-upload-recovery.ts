import type {
  DistributionDocumentType,
  DocumentVerificationResult,
  VerifiedDistributedDocument,
} from "@/types/document-distribution.types";
import {
  MAX_DOCUMENT_RECEIPT_CHUNK_BYTES,
  MAX_DOCUMENT_SELECTION_BYTES,
  MAX_DOCUMENT_SELECTION_FILES,
  cloneDocumentStagingManifest,
  type DocumentStagingManifest,
} from "./document-upload-batching";

const DOCUMENT_UPLOAD_RECOVERY_VERSION = 1;
const DOCUMENT_UPLOAD_RECOVERY_PREFIX = "passdetection:document-staging-manifest";
const MAX_RECEIPT_LENGTH = 512 * 1024;

export interface DocumentUploadRecoveryPlan {
  manifest: DocumentStagingManifest;
  verification: DocumentVerificationResult;
}

/** Remove opaque capability receipts before verification metadata enters React state. */
export function verificationWithoutStagingReceipts(
  verification: DocumentVerificationResult,
): DocumentVerificationResult {
  return {
    ...verification,
    files: verification.files.map((file) => ({
      ...file,
      staging_receipt: null,
    })),
  };
}

export function persistDocumentUploadRecovery(
  groupId: string,
  documentType: DistributionDocumentType,
  plan: DocumentUploadRecoveryPlan,
) {
  if (typeof window === "undefined") return false;
  try {
    if (
      plan.manifest.chunks.length > 0 &&
      plan.manifest.completedChunks === plan.manifest.chunks.length
    ) {
      window.sessionStorage.removeItem(recoveryKey(groupId, documentType));
      return true;
    }
    window.sessionStorage.setItem(
      recoveryKey(groupId, documentType),
      JSON.stringify({
        version: DOCUMENT_UPLOAD_RECOVERY_VERSION,
        groupId,
        documentType,
        manifest: plan.manifest,
        verification: verificationWithoutStagingReceipts(plan.verification),
      }),
    );
    return true;
  } catch {
    // Privacy-restricted browsers and small storage quotas must not retain File
    // handles as a substitute. The current in-memory receipt manifest remains
    // usable, while a refresh requires verification again.
    return false;
  }
}

export function readDocumentUploadRecovery(
  groupId: string,
  documentType: DistributionDocumentType,
): DocumentUploadRecoveryPlan | null {
  if (typeof window === "undefined") return null;
  const key = recoveryKey(groupId, documentType);
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!isRecoveryPlan(parsed, groupId, documentType)) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    return {
      manifest: cloneDocumentStagingManifest(parsed.manifest),
      verification: verificationWithoutStagingReceipts(parsed.verification),
    };
  } catch {
    window.sessionStorage.removeItem(key);
    return null;
  }
}

export function clearDocumentUploadRecovery(
  groupId: string,
  documentType: DistributionDocumentType,
) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(recoveryKey(groupId, documentType));
  } catch {
    // In-memory state is still cleared by the caller.
  }
}

function recoveryKey(groupId: string, documentType: DistributionDocumentType) {
  return `${DOCUMENT_UPLOAD_RECOVERY_PREFIX}:${groupId}:${documentType}`;
}

function isRecoveryPlan(
  value: unknown,
  groupId: string,
  documentType: DistributionDocumentType,
): value is {
  version: 1;
  groupId: string;
  documentType: DistributionDocumentType;
  manifest: DocumentStagingManifest;
  verification: DocumentVerificationResult;
} {
  if (!isRecord(value)) return false;
  if (
    value.version !== DOCUMENT_UPLOAD_RECOVERY_VERSION ||
    value.groupId !== groupId ||
    value.documentType !== documentType ||
    !isDocumentStagingManifest(value.manifest) ||
    !isDocumentVerification(value.verification, groupId, documentType)
  ) {
    return false;
  }
  return value.manifest.totalFiles === value.verification.accepted_count;
}

function isDocumentStagingManifest(value: unknown): value is DocumentStagingManifest {
  if (!isRecord(value) || value.version !== 1) return false;
  if (
    !isBoundedString(value.uploadId, 200) ||
    !Array.isArray(value.chunks) ||
    value.chunks.length > MAX_DOCUMENT_SELECTION_FILES ||
    !isSafeIntegerBetween(value.totalFiles, 0, MAX_DOCUMENT_SELECTION_FILES) ||
    !isSafeIntegerBetween(value.totalBytes, 0, MAX_DOCUMENT_SELECTION_BYTES) ||
    !isSafeIntegerBetween(value.completedChunks, 0, value.chunks.length) ||
    typeof value.createdAt !== "string" ||
    !Number.isFinite(Date.parse(value.createdAt))
  ) {
    return false;
  }

  let totalFiles = 0;
  let totalBytes = 0;
  for (const [index, chunk] of value.chunks.entries()) {
    if (!isRecord(chunk)) return false;
    if (
      !isBoundedString(chunk.chunkId, 200) ||
      !isSafeIntegerBetween(chunk.fileCount, 1, MAX_DOCUMENT_SELECTION_FILES) ||
      !isSafeIntegerBetween(chunk.totalBytes, 1, MAX_DOCUMENT_SELECTION_BYTES) ||
      !Array.isArray(chunk.receipts)
    ) {
      return false;
    }
    if (index < value.completedChunks) {
      if (chunk.receipts.length !== 0) return false;
    } else if (
      chunk.receipts.length !== chunk.fileCount ||
      !isBoundedReceiptBatch(chunk.receipts)
    ) {
      return false;
    }
    totalFiles += chunk.fileCount;
    totalBytes += chunk.totalBytes;
  }
  return totalFiles === value.totalFiles && totalBytes === value.totalBytes;
}

function isBoundedReceiptBatch(receipts: unknown[]) {
  const encoder = new TextEncoder();
  let encodedBytes = 0;
  for (const receipt of receipts) {
    if (!isBoundedString(receipt, MAX_RECEIPT_LENGTH)) return false;
    encodedBytes += encoder.encode(receipt).byteLength;
    if (encodedBytes > MAX_DOCUMENT_RECEIPT_CHUNK_BYTES) return false;
  }
  return true;
}

function isDocumentVerification(
  value: unknown,
  groupId: string,
  documentType: DistributionDocumentType,
): value is DocumentVerificationResult {
  if (!isRecord(value)) return false;
  if (
    value.group_id !== groupId ||
    value.document_type !== documentType ||
    !isSafeIntegerBetween(value.total_count, 0, MAX_DOCUMENT_SELECTION_FILES) ||
    !isSafeIntegerBetween(value.accepted_count, 0, value.total_count) ||
    !isSafeIntegerBetween(value.rejected_count, 0, value.total_count) ||
    value.accepted_count + value.rejected_count !== value.total_count ||
    !Array.isArray(value.files) ||
    value.files.length !== value.total_count ||
    !value.files.every(isVerifiedDocument)
  ) {
    return false;
  }
  return value.files.filter((file) => file.accepted).length === value.accepted_count;
}

function isVerifiedDocument(value: unknown): value is VerifiedDistributedDocument {
  if (!isRecord(value)) return false;
  return (
    isBoundedString(value.filename, 2_000) &&
    isBoundedString(value.detected_type, 200) &&
    typeof value.accepted === "boolean" &&
    isBoundedString(value.reason, 4_000) &&
    isNullableBoundedString(value.matched_passenger_id, 200) &&
    isNullableBoundedString(value.matched_passenger_name, 2_000) &&
    isBoundedStringArray(value.matched_passenger_ids, 1_500, 200) &&
    isBoundedStringArray(value.matched_passenger_names, 1_500, 2_000) &&
    typeof value.match_confidence === "number" &&
    Number.isFinite(value.match_confidence) &&
    isNullableBoundedString(value.match_status, 200) &&
    isNullableBoundedString(value.match_reason, 4_000) &&
    value.staging_receipt === null
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSafeIntegerBetween(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number {
  return Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum;
}

function isBoundedString(value: unknown, maximumLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximumLength;
}

function isNullableBoundedString(value: unknown, maximumLength: number) {
  return value === null || isBoundedString(value, maximumLength);
}

function isBoundedStringArray(value: unknown, maximumItems: number, maximumLength: number) {
  return Array.isArray(value)
    && value.length <= maximumItems
    && value.every((item) => isBoundedString(item, maximumLength));
}
