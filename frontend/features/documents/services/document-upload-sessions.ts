import {
  MAX_DOCUMENT_SELECTION_FILES,
  MAX_DOCUMENT_SELECTION_BYTES,
  MAX_DOCUMENT_CHUNK_FILES,
  TARGET_DOCUMENT_CHUNK_BYTES,
  MAX_DOCUMENT_VERIFICATION_CHUNK_FILES,
  TARGET_DOCUMENT_VERIFICATION_CHUNK_BYTES,
} from "./document-upload-model.ts";
import type { DocumentUploadSession } from "./document-upload-model.ts";

export function createDocumentUploadSession(
  files: File[],
  createId: () => string = () => crypto.randomUUID(),
): DocumentUploadSession {
  return createDocumentUploadSessionWithLimits(
    files,
    createId,
    MAX_DOCUMENT_CHUNK_FILES,
    TARGET_DOCUMENT_CHUNK_BYTES,
  );
}

export function createDocumentVerificationSession(
  files: File[],
  createId: () => string = () => crypto.randomUUID(),
): DocumentUploadSession {
  return createDocumentUploadSessionWithLimits(
    files,
    createId,
    MAX_DOCUMENT_VERIFICATION_CHUNK_FILES,
    TARGET_DOCUMENT_VERIFICATION_CHUNK_BYTES,
  );
}

function createDocumentUploadSessionWithLimits(
  files: File[],
  createId: () => string,
  maxChunkFiles: number,
  targetChunkBytes: number,
): DocumentUploadSession {
  if (files.length === 0) throw new Error("Upload at least one PDF");
  if (files.length > MAX_DOCUMENT_SELECTION_FILES) {
    throw new Error(`Select at most ${MAX_DOCUMENT_SELECTION_FILES} PDFs at a time`);
  }

  const chunks: File[][] = [];
  let current: File[] = [];
  let currentBytes = 0;
  let totalBytes = 0;
  for (const file of files) {
    if (file.size <= 0) throw new Error(`${file.name || "A selected PDF"} is empty`);
    const looksLikePdf =
      file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!looksLikePdf) throw new Error(`${file.name} is not a PDF`);

    const exceedsCurrentChunk =
      current.length > 0 &&
      (current.length >= maxChunkFiles ||
        currentBytes + file.size > targetChunkBytes);
    if (exceedsCurrentChunk) {
      chunks.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(file);
    currentBytes += file.size;
    totalBytes += file.size;
    if (totalBytes > MAX_DOCUMENT_SELECTION_BYTES) {
      throw new Error("The complete PDF selection exceeds the 2 GB safety limit");
    }
  }
  if (current.length > 0) chunks.push(current);

  return {
    uploadId: createId(),
    chunks,
    chunkIds: chunks.map(() => createId()),
    chunkFileSizes: chunks.map((chunk) => chunk.map((file) => file.size)),
    totalFiles: files.length,
    totalBytes,
    completedChunks: 0,
  };
}
