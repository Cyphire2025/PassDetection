import type { DocumentUploadProgress, RunConcurrentUploadOptions } from "./document-upload-model.ts";
import { retryTransientDocumentChunk } from "./document-upload-retry.ts";

/**
 * Run independent verification chunks with bounded concurrency.
 *
 * Verification is intentionally separate from finalization: final document
 * writes retain their sequential, resumable commit order. Verification chunks
 * are also submitted sequentially because each distribution batch can use eight
 * isolated parser processes, within the shared eight-process deployment budget.
 * Every
 * in-flight request is drained before an error is returned, so successful
 * staging writes always retain their server-side cleanup ownership.
 */
export async function runConcurrentDocumentVerification<T>({
  session,
  uploadChunk,
  onProgress,
  concurrency,
  uploadWeight = 0.2,
  signal,
}: RunConcurrentUploadOptions<T>): Promise<T[]> {
  if (!Number.isInteger(concurrency) || concurrency < 1) {
    throw new Error("Document verification concurrency must be positive");
  }
  if (!(uploadWeight > 0 && uploadWeight < 1)) {
    throw new Error("Document verification upload weight must be between zero and one");
  }

  const results: Array<T | undefined> = Array(session.chunks.length);
  const uploadedFractions = Array(session.chunks.length).fill(0) as number[];
  const completed = Array(session.chunks.length).fill(false) as boolean[];
  const chunkBytes = session.chunks.map((chunk) =>
    chunk.reduce((total, file) => total + Math.max(file.size, 1), 0),
  );
  const chunkFileCounts = session.chunks.map((chunk) => chunk.length);
  const progressDenominator = Math.max(
    chunkBytes.reduce((total, value) => total + value, 0),
    session.totalFiles,
  );
  let nextChunkIndex = 0;
  let firstError: unknown;
  let failed = false;
  let lastProgress: DocumentUploadProgress | null = null;

  const emitProgress = (activeChunkIndex: number) => {
    const completedBytes = chunkBytes.reduce(
      (total, value, index) => total + (completed[index] ? value : 0),
      0,
    );
    const uploadedProcessingBytes = chunkBytes.reduce(
      (total, value, index) =>
        total + (completed[index] ? 0 : value * uploadedFractions[index] * uploadWeight),
      0,
    );
    const completedFiles = chunkFileCounts.reduce(
      (total, fileCount, index) => total + (completed[index] ? fileCount : 0),
      0,
    );
    const allActiveUploadsComplete = uploadedFractions.every(
      (fraction, index) => completed[index] || fraction === 0 || fraction >= 1,
    );
    const next: DocumentUploadProgress = {
      percent: Math.min(
        completedFiles === session.totalFiles ? 100 : 99,
        Math.floor(((completedBytes + uploadedProcessingBytes) / progressDenominator) * 100),
      ),
      phase:
        completedFiles === session.totalFiles
          ? "completed"
          : allActiveUploadsComplete
            ? "processing"
            : "uploading",
      completedFiles,
      totalFiles: session.totalFiles,
      chunkNumber: activeChunkIndex + 1,
      chunkCount: session.chunks.length,
    };
    next.percent = Math.max(lastProgress?.percent ?? 0, next.percent);
    if (
      lastProgress?.percent === next.percent &&
      lastProgress.phase === next.phase &&
      lastProgress.completedFiles === next.completedFiles &&
      lastProgress.chunkNumber === next.chunkNumber
    ) {
      return;
    }
    lastProgress = next;
    onProgress?.(next);
  };

  const worker = async () => {
    while (!failed) {
      const chunkIndex = nextChunkIndex;
      nextChunkIndex += 1;
      if (chunkIndex >= session.chunks.length) return;
      const chunk = session.chunks[chunkIndex];
      try {
        results[chunkIndex] = await retryTransientDocumentChunk(
          () => uploadChunk(chunk, chunkIndex, (loaded, total) => {
            const uploadTotal = Math.max(total ?? chunkBytes[chunkIndex], 1);
            uploadedFractions[chunkIndex] = Math.min(
              Math.max(loaded / uploadTotal, 0),
              1,
            );
            emitProgress(chunkIndex);
          }),
          signal,
        );
        uploadedFractions[chunkIndex] = 1;
        completed[chunkIndex] = true;
        // The server acknowledgement owns a durable staged copy. Release the
        // browser File handles immediately instead of retaining every verified
        // PDF until the user starts finalization.
        session.chunks[chunkIndex] = [];
        emitProgress(chunkIndex);
      } catch (error) {
        if (!failed) firstError = error;
        failed = true;
      }
    }
  };

  const workerCount = Math.min(concurrency, session.chunks.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
  if (failed) throw firstError;
  session.completedChunks = session.chunks.length;
  return results.map((result) => {
    if (result === undefined) {
      throw new Error("The document verification response was incomplete");
    }
    return result;
  });
}
