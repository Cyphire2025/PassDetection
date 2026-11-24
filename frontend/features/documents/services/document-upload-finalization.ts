import type {
  DocumentUploadProgress,
  RunChunkedUploadOptions,
  RunStagedUploadOptions,
} from "./document-upload-model.ts";
import { canFinalizeDocumentReceiptChunk, cloneDocumentStagingManifest } from "./document-staging-manifest.ts";
import { retryTransientDocumentChunk } from "./document-upload-retry.ts";

export async function runChunkedDocumentUpload<T>({
  session,
  uploadChunk,
  onProgress,
}: RunChunkedUploadOptions<T>): Promise<T> {
  let completedBytes = session.chunks
    .slice(0, session.completedChunks)
    .flat()
    .reduce((total, file) => total + Math.max(file.size, 1), 0);
  let completedFiles = session.chunks
    .slice(0, session.completedChunks)
    .reduce((total, chunk) => total + chunk.length, 0);
  let latestResult: T | undefined;
  const progressDenominator = Math.max(session.totalBytes, session.totalFiles);
  let lastProgress: DocumentUploadProgress | null = null;

  const emitProgress = (next: DocumentUploadProgress) => {
    const monotonic = {
      ...next,
      percent: Math.max(lastProgress?.percent ?? 0, next.percent),
    };
    if (
      lastProgress?.percent === monotonic.percent &&
      lastProgress.phase === monotonic.phase &&
      lastProgress.completedFiles === monotonic.completedFiles &&
      lastProgress.chunkNumber === monotonic.chunkNumber
    ) {
      return;
    }
    lastProgress = monotonic;
    onProgress?.(monotonic);
  };

  for (
    let chunkIndex = session.completedChunks;
    chunkIndex < session.chunks.length;
    chunkIndex += 1
  ) {
    const chunk = session.chunks[chunkIndex];
    const chunkBytes = chunk.reduce((total, file) => total + Math.max(file.size, 1), 0);
    const report = (loaded: number, total: number | undefined) => {
      const uploadTotal = Math.max(total ?? chunkBytes, 1);
      const uploadedFraction = Math.min(Math.max(loaded / uploadTotal, 0), 1);
      // Completion of the HTTP body is not completion of PDF processing. Keep
      // 20% of each chunk's weight reserved until the server commits it.
      const weightedBytes = completedBytes + chunkBytes * uploadedFraction * 0.8;
      emitProgress({
        percent: Math.min(99, Math.floor((weightedBytes / progressDenominator) * 100)),
        phase: uploadedFraction >= 1 ? "processing" : "uploading",
        completedFiles,
        totalFiles: session.totalFiles,
        chunkNumber: chunkIndex + 1,
        chunkCount: session.chunks.length,
      });
    };

    latestResult = await retryTransientDocumentChunk(() =>
      uploadChunk(chunk, chunkIndex, report),
    );
    completedBytes += chunkBytes;
    completedFiles += chunk.length;
    session.completedChunks = chunkIndex + 1;
    emitProgress({
      percent: Math.min(100, Math.floor((completedBytes / progressDenominator) * 100)),
      phase: completedFiles === session.totalFiles ? "completed" : "uploading",
      completedFiles,
      totalFiles: session.totalFiles,
      chunkNumber: chunkIndex + 1,
      chunkCount: session.chunks.length,
    });
  }

  if (latestResult === undefined) throw new Error("Upload at least one PDF");
  return latestResult;
}

/** Finalize receipt-only chunks and release each acknowledged token set. */
export async function runStagedDocumentUpload<T>({
  manifest,
  uploadChunk,
  onProgress,
  onManifestChange,
  signal,
}: RunStagedUploadOptions<T>): Promise<T> {
  if (manifest.totalFiles <= 0 || manifest.chunks.length === 0) {
    throw new Error("Upload at least one verified PDF");
  }
  if (
    manifest.completedChunks < 0 ||
    manifest.completedChunks >= manifest.chunks.length
  ) {
    throw new Error("The verified upload manifest is already complete or invalid");
  }

  let completedBytes = manifest.chunks
    .slice(0, manifest.completedChunks)
    .reduce((total, chunk) => total + Math.max(chunk.totalBytes, chunk.fileCount), 0);
  let completedFiles = manifest.chunks
    .slice(0, manifest.completedChunks)
    .reduce((total, chunk) => total + chunk.fileCount, 0);
  const progressDenominator = Math.max(manifest.totalBytes, manifest.totalFiles);
  let latestResult: T | undefined;
  let lastProgress: DocumentUploadProgress | null = null;

  const emitProgress = (next: DocumentUploadProgress) => {
    const monotonic = {
      ...next,
      percent: Math.max(lastProgress?.percent ?? 0, next.percent),
    };
    if (
      lastProgress?.percent === monotonic.percent &&
      lastProgress.phase === monotonic.phase &&
      lastProgress.completedFiles === monotonic.completedFiles &&
      lastProgress.chunkNumber === monotonic.chunkNumber
    ) {
      return;
    }
    lastProgress = monotonic;
    onProgress?.(monotonic);
  };

  for (
    let chunkIndex = manifest.completedChunks;
    chunkIndex < manifest.chunks.length;
    chunkIndex += 1
  ) {
    const chunk = manifest.chunks[chunkIndex];
    if (!canFinalizeDocumentReceiptChunk(chunk.receipts, chunk.fileCount)) {
      throw new Error(
        "The verified PDF staging receipt is missing or expired. Check the PDFs again.",
      );
    }
    const chunkBytes = Math.max(chunk.totalBytes, chunk.fileCount);
    const report = (loaded: number, total: number | undefined) => {
      const uploadTotal = Math.max(total ?? 1, 1);
      const uploadedFraction = Math.min(Math.max(loaded / uploadTotal, 0), 1);
      const weightedBytes = completedBytes + chunkBytes * uploadedFraction * 0.8;
      emitProgress({
        percent: Math.min(99, Math.floor((weightedBytes / progressDenominator) * 100)),
        phase: uploadedFraction >= 1 ? "processing" : "uploading",
        completedFiles,
        totalFiles: manifest.totalFiles,
        chunkNumber: chunkIndex + 1,
        chunkCount: manifest.chunks.length,
      });
    };

    latestResult = await retryTransientDocumentChunk(
      () => uploadChunk(chunk, chunkIndex, report),
      signal,
    );
    completedBytes += chunkBytes;
    completedFiles += chunk.fileCount;
    manifest.completedChunks = chunkIndex + 1;
    // A committed server chunk is idempotently addressable by upload/chunk ID;
    // keeping its opaque receipts in React or session storage adds no recovery
    // value and extends sensitive browser ownership unnecessarily.
    chunk.receipts = [];
    onManifestChange?.(cloneDocumentStagingManifest(manifest));
    emitProgress({
      percent: Math.min(100, Math.floor((completedBytes / progressDenominator) * 100)),
      phase: completedFiles === manifest.totalFiles ? "completed" : "uploading",
      completedFiles,
      totalFiles: manifest.totalFiles,
      chunkNumber: chunkIndex + 1,
      chunkCount: manifest.chunks.length,
    });
  }

  if (latestResult === undefined) throw new Error("Upload at least one verified PDF");
  return latestResult;
}
