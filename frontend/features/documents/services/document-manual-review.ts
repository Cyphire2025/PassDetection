import type { DocumentVerificationResult, VerifiedDistributedDocument } from "@/types/document-distribution.types";
import {
  canFinalizeDocumentReceiptChunk,
  isPassengerMatchedVerificationFile,
  type DocumentFilenameReplacement,
  type DocumentStagingManifest,
} from "./document-upload-batching";
import { verificationWithoutStagingReceipts, type DocumentUploadRecoveryPlan } from "./document-upload-recovery";

/** File handles and review tokens belong only to the current page. */
export interface DocumentManualReviewCandidate {
  fileIndex: number;
  file: File;
  approvalToken: string;
  uploadId: string;
  chunkId: string;
  filenameReplacement?: DocumentFilenameReplacement;
}

export function emptyDocumentManifest(): DocumentStagingManifest {
  return { version: 1, uploadId: crypto.randomUUID(), chunks: [], totalFiles: 0, totalBytes: 0, completedChunks: 0, createdAt: new Date().toISOString() };
}

export function replaceVerificationFiles(
  verification: DocumentVerificationResult,
  replacements: ReadonlyMap<number, VerifiedDistributedDocument>,
): DocumentVerificationResult {
  const files = verification.files.map((file, index) => replacements.get(index) ?? file);
  const acceptedCount = files.filter((file) => file.accepted).length;
  return verificationWithoutStagingReceipts({ ...verification, files, accepted_count: acceptedCount, rejected_count: files.length - acceptedCount });
}

export function appendApprovedDocument(
  plan: DocumentUploadRecoveryPlan,
  candidate: DocumentManualReviewCandidate,
  result: VerifiedDistributedDocument,
): DocumentUploadRecoveryPlan {
  if (plan.manifest.finalizationStarted || !result.manual_type_approved || !isPassengerMatchedVerificationFile(result)
    || !canFinalizeDocumentReceiptChunk([result.staging_receipt], 1)) {
    throw new Error("The selected PDF did not receive a matched, approved upload receipt. Check it again.");
  }
  const count = plan.manifest.totalFiles + 1;
  return {
    manifest: {
      ...plan.manifest,
      chunks: [...plan.manifest.chunks, {
        chunkId: candidate.chunkId,
        receipts: [result.staging_receipt!],
        fileCount: 1,
        totalBytes: candidate.file.size,
        filenameReplacements: candidate.filenameReplacement ? [candidate.filenameReplacement] : [],
      }],
      totalFiles: count,
      totalBytes: plan.manifest.totalBytes + candidate.file.size,
    },
    verification: verificationWithoutStagingReceipts({
      ...plan.verification,
      files: [...plan.verification.files, { ...result, manual_source_index: candidate.fileIndex }],
      total_count: count,
      accepted_count: count,
      rejected_count: 0,
    }),
  };
}

export function applyCompletedManualUploads(
  verification: DocumentVerificationResult,
  plan: DocumentUploadRecoveryPlan,
): DocumentVerificationResult {
  const replacements = new Map<number, VerifiedDistributedDocument>();
  // Manual approvals use one PDF per chunk. Only acknowledged chunks leave the
  // rejected list; ambiguous requests retain their resumable receipt.
  for (const file of plan.verification.files.slice(0, plan.manifest.completedChunks)) {
    const index = file.manual_source_index;
    if (index === undefined || !verification.files[index]
      || verification.files[index].filename !== file.filename) continue;
    replacements.set(index, { ...file, manual_uploaded: true, uploaded: true, manual_review_available: false });
  }
  return replaceVerificationFiles(verification, replacements);
}
