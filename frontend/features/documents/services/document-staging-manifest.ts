import { MAX_DOCUMENT_RECEIPT_CHUNK_BYTES } from "./document-upload-model.ts";
import type {
  DocumentStagingChunk,
  DocumentStagingManifest,
  DocumentUploadSession,
} from "./document-upload-model.ts";

export function createDocumentStagingManifest(
  sourceSession: DocumentUploadSession,
  acceptedByChunk: readonly (readonly boolean[])[],
  receiptsByChunk: readonly (readonly (string | null | undefined)[])[],
): DocumentStagingManifest {
  if (
    acceptedByChunk.length !== sourceSession.chunks.length ||
    receiptsByChunk.length !== sourceSession.chunks.length ||
    sourceSession.chunkFileSizes.length !== sourceSession.chunks.length ||
    sourceSession.chunkIds.length !== sourceSession.chunks.length
  ) {
    throw new Error("The document verification response did not match the upload session");
  }

  const chunks: DocumentStagingChunk[] = [];
  for (const [chunkIndex, sourceChunkSizes] of sourceSession.chunkFileSizes.entries()) {
    const acceptedFiles = acceptedByChunk[chunkIndex];
    const sourceReceipts = receiptsByChunk[chunkIndex];
    if (
      acceptedFiles.length !== sourceChunkSizes.length ||
      sourceReceipts.length !== sourceChunkSizes.length
    ) {
      throw new Error("The document verification response did not match the upload session");
    }

    const receipts: string[] = [];
    let totalBytes = 0;
    for (const [fileIndex, accepted] of acceptedFiles.entries()) {
      if (!accepted) continue;
      const receipt = sourceReceipts[fileIndex];
      if (!receipt) {
        throw new Error(
          "A verified PDF did not receive a durable staging receipt. "
          + "Check the selection again before uploading.",
        );
      }
      receipts.push(receipt);
      totalBytes += sourceChunkSizes[fileIndex];
    }
    if (receipts.length === 0) continue;
    if (!canFinalizeDocumentReceiptChunk(receipts, receipts.length)) {
      throw new Error(
        "The verified staging manifest exceeds its bounded upload envelope. "
        + "Check a smaller PDF selection.",
      );
    }
    chunks.push({
      chunkId: sourceSession.chunkIds[chunkIndex],
      receipts,
      fileCount: receipts.length,
      totalBytes,
    });
  }

  return {
    version: 1,
    uploadId: sourceSession.uploadId,
    chunks,
    totalFiles: chunks.reduce((total, chunk) => total + chunk.fileCount, 0),
    totalBytes: chunks.reduce((total, chunk) => total + chunk.totalBytes, 0),
    completedChunks: 0,
    createdAt: new Date().toISOString(),
  };
}

export function canFinalizeDocumentReceiptChunk(
  receipts: readonly (string | null | undefined)[] | undefined,
  expectedCount: number,
): receipts is readonly string[] {
  if (
    !receipts ||
    receipts.length !== expectedCount ||
    !receipts.every((receipt): receipt is string => Boolean(receipt))
  ) {
    return false;
  }

  const encoder = new TextEncoder();
  let encodedBytes = 0;
  for (const receipt of receipts) {
    encodedBytes += encoder.encode(receipt).byteLength;
    if (encodedBytes > MAX_DOCUMENT_RECEIPT_CHUNK_BYTES) return false;
  }
  return true;
}

export function cloneDocumentStagingManifest(
  manifest: DocumentStagingManifest,
): DocumentStagingManifest {
  return {
    ...manifest,
    chunks: manifest.chunks.map((chunk) => ({
      ...chunk,
      receipts: [...chunk.receipts],
    })),
  };
}
