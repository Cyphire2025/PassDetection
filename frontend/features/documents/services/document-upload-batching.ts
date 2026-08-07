import type { ApiError } from "@/lib/api/client";

export const MAX_DOCUMENT_SELECTION_FILES = 1_500;
export const MAX_DOCUMENT_SELECTION_BYTES = 2 * 1024 * 1024 * 1024;
export const MAX_DOCUMENT_CHUNK_FILES = 50;
export const TARGET_DOCUMENT_CHUNK_BYTES = 24 * 1024 * 1024;
export const MAX_DOCUMENT_RECEIPT_CHUNK_BYTES = 8 * 1024 * 1024;
// Two isolated parser workers can process eight 10-second waves inside the
// backend's 90-second hard batch envelope. Keep the byte cap independent so
// larger PDFs retain the existing memory and request-size bounds.
export const MAX_DOCUMENT_VERIFICATION_CHUNK_FILES = 16;
export const TARGET_DOCUMENT_VERIFICATION_CHUNK_BYTES = 8 * 1024 * 1024;
export const MAX_DOCUMENT_VERIFICATION_CONCURRENCY = 1;

export interface DocumentUploadSession {
  uploadId: string;
  chunks: File[][];
  chunkIds: string[];
  totalFiles: number;
  totalBytes: number;
  completedChunks: number;
}

export interface DocumentUploadProgress {
  percent: number;
  phase: "uploading" | "processing" | "completed";
  completedFiles: number;
  totalFiles: number;
  chunkNumber: number;
  chunkCount: number;
}

export interface PassengerMatchedVerificationCandidate {
  accepted: boolean;
  matched_passenger_id: string | null;
  matched_passenger_ids: string[];
  match_status: string | null;
}

export function isPassengerMatchedVerificationFile(
  file: PassengerMatchedVerificationCandidate,
): boolean {
  return (
    file.accepted &&
    file.match_status === "matched" &&
    (Boolean(file.matched_passenger_id) || file.matched_passenger_ids.length > 0)
  );
}

interface RunChunkedUploadOptions<T> {
  session: DocumentUploadSession;
  uploadChunk: (
    files: File[],
    chunkIndex: number,
    onUploadProgress: (loaded: number, total: number | undefined) => void,
  ) => Promise<T>;
  onProgress?: (progress: DocumentUploadProgress) => void;
}

interface RunConcurrentUploadOptions<T> extends RunChunkedUploadOptions<T> {
  concurrency: number;
  uploadWeight?: number;
}

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
    totalFiles: files.length,
    totalBytes,
    completedChunks: 0,
  };
}

/**
 * Run independent verification chunks with bounded concurrency.
 *
 * Verification is intentionally separate from finalization: final document
 * writes retain their sequential, resumable commit order. Verification chunks
 * are also submitted sequentially because each backend batch already runs two
 * isolated parser processes. Sixteen files is the largest chunk that fits the
 * backend's eight parser waves; overlapping HTTP chunks would otherwise create
 * four simultaneous Tesseract processes and make image-only PDFs time out.
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
    const completedFiles = session.chunks.reduce(
      (total, chunk, index) => total + (completed[index] ? chunk.length : 0),
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
        results[chunkIndex] = await retryTransientDocumentChunk(() =>
          uploadChunk(chunk, chunkIndex, (loaded, total) => {
            const uploadTotal = Math.max(total ?? chunkBytes[chunkIndex], 1);
            uploadedFractions[chunkIndex] = Math.min(
              Math.max(loaded / uploadTotal, 0),
              1,
            );
            emitProgress(chunkIndex);
          }),
        );
        uploadedFractions[chunkIndex] = 1;
        completed[chunkIndex] = true;
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

export function createAcceptedDocumentUploadSession(
  sourceSession: DocumentUploadSession,
  acceptedByChunk: readonly (readonly boolean[])[],
): DocumentUploadSession {
  if (
    acceptedByChunk.length !== sourceSession.chunks.length ||
    sourceSession.chunkIds.length !== sourceSession.chunks.length
  ) {
    throw new Error("The document verification response did not match the upload session");
  }

  const chunks: File[][] = [];
  const chunkIds: string[] = [];
  for (const [chunkIndex, sourceChunk] of sourceSession.chunks.entries()) {
    const acceptedFiles = acceptedByChunk[chunkIndex];
    if (acceptedFiles.length !== sourceChunk.length) {
      throw new Error("The document verification response did not match the upload session");
    }

    const retainedChunk = sourceChunk.filter((_file, fileIndex) => acceptedFiles[fileIndex]);
    if (retainedChunk.length === 0) continue;
    chunks.push(retainedChunk);
    chunkIds.push(sourceSession.chunkIds[chunkIndex]);
  }

  return {
    uploadId: sourceSession.uploadId,
    chunks,
    chunkIds,
    totalFiles: chunks.reduce((total, chunk) => total + chunk.length, 0),
    totalBytes: chunks
      .flat()
      .reduce((total, file) => total + file.size, 0),
    completedChunks: 0,
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

async function retryTransientDocumentChunk<T>(operation: () => Promise<T>): Promise<T> {
  let attempt = 0;
  while (true) {
    try {
      return await operation();
    } catch (error) {
      if (attempt >= 2 || !isTransientDocumentUploadError(error)) throw error;
      attempt += 1;
      await new Promise((resolve) => globalThis.setTimeout(resolve, 400 * attempt));
    }
  }
}

function isTransientDocumentUploadError(error: unknown): boolean {
  const code = (error as Partial<ApiError> | null)?.code;
  return (
    code === "NETWORK_ERROR" ||
    code === "REQUEST_TIMEOUT" ||
    code === "HTTP_429" ||
    code === "HTTP_502" ||
    code === "HTTP_503" ||
    code === "HTTP_504"
  );
}
