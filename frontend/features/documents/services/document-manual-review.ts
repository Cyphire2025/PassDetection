import type {
  DocumentVerificationResult,
  VerifiedDistributedDocument,
} from "@/types/document-distribution.types";
import {
  canFinalizeDocumentReceiptChunk,
  isPassengerMatchedVerificationFile,
  type DocumentStagingManifest,
} from "./document-upload-batching";
import { verificationWithoutStagingReceipts } from "./document-upload-recovery";

/** These File handles and approval tokens belong only to the current page. */
export interface DocumentManualReviewCandidate {
  fileIndex: number;
  file: File;
  approvalToken: string;
  uploadId: string;
  chunkId: string;
}

export function applyManualDocumentVerification(
  candidate: DocumentManualReviewCandidate,
  result: VerifiedDistributedDocument,
  verification: DocumentVerificationResult,
  manifest: DocumentStagingManifest,
) {
  if (
    manifest.finalizationStarted || manifest.completedChunks > 0
    || manifest.uploadId !== candidate.uploadId
    || verification.files[candidate.fileIndex]?.accepted !== false
  ) {
    throw new Error("This upload has changed. Check the PDF again before approving its type.");
  }
  const accepted = isPassengerMatchedVerificationFile(result);
  if (!result.manual_type_approved) {
    throw new Error("The document type approval was not confirmed. Review and try again.");
  }
  if (accepted && !canFinalizeDocumentReceiptChunk([result.staging_receipt], 1)) {
    throw new Error("The approved PDF did not receive a secure staging receipt. Check the PDF again.");
  }
  const files = verification.files.map((file, index) => index === candidate.fileIndex
    ? {
      ...result,
      accepted,
      manual_review_available: false,
      reason: accepted ? result.reason : result.match_reason || result.reason || "No confirmed passenger match found",
    }
    : file);
  const acceptedCount = files.filter((file) => file.accepted).length;
  return {
    verification: verificationWithoutStagingReceipts({
      ...verification,
      accepted_count: acceptedCount,
      rejected_count: files.length - acceptedCount,
      files,
    }),
    stagingManifest: accepted && result.staging_receipt
      ? {
        ...manifest,
        chunks: [...manifest.chunks, {
          chunkId: candidate.chunkId,
          receipts: [result.staging_receipt],
          fileCount: 1,
          totalBytes: candidate.file.size,
        }],
        totalFiles: manifest.totalFiles + 1,
        totalBytes: manifest.totalBytes + candidate.file.size,
      }
      : manifest,
  };
}
