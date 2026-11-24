
export const MAX_DOCUMENT_SELECTION_FILES = 1_500;

export const MAX_DOCUMENT_SELECTION_BYTES = 2 * 1024 * 1024 * 1024;

export const MAX_DOCUMENT_CHUNK_FILES = 50;

export const TARGET_DOCUMENT_CHUNK_BYTES = 24 * 1024 * 1024;

export const MAX_DOCUMENT_RECEIPT_CHUNK_BYTES = 8 * 1024 * 1024;

// Each verification request can check eight PDFs concurrently. Keep the
// 16-file limit and a separate byte target to bound request memory.
export const MAX_DOCUMENT_VERIFICATION_CHUNK_FILES = 16;

export const TARGET_DOCUMENT_VERIFICATION_CHUNK_BYTES = 16 * 1024 * 1024;

export const MAX_DOCUMENT_VERIFICATION_CONCURRENCY = 1;

export interface DocumentUploadSession {
  uploadId: string;
  chunks: File[][];
  chunkIds: string[];
  chunkFileSizes: number[][];
  totalFiles: number;
  totalBytes: number;
  completedChunks: number;
}

export interface DocumentStagingChunk {
  chunkId: string;
  receipts: string[];
  fileCount: number;
  totalBytes: number;
  filenameReplacements?: DocumentFilenameReplacement[];
}

export interface DocumentFilenameReplacement {
  filename: string;
  documents: { id: string; updated_at: string }[];
}

export interface DocumentStagingManifest {
  version: 1;
  uploadId: string;
  chunks: DocumentStagingChunk[];
  totalFiles: number;
  totalBytes: number;
  completedChunks: number;
  createdAt: string;
  /** Freeze the receipt roster once a request may have reached finalization. */
  finalizationStarted?: boolean;
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

export interface RunChunkedUploadOptions<T> {
  session: DocumentUploadSession;
  uploadChunk: (
    files: File[],
    chunkIndex: number,
    onUploadProgress: (loaded: number, total: number | undefined) => void,
  ) => Promise<T>;
  onProgress?: (progress: DocumentUploadProgress) => void;
}

export interface RunConcurrentUploadOptions<T> extends RunChunkedUploadOptions<T> {
  concurrency: number;
  uploadWeight?: number;
  signal?: AbortSignal;
}

export interface RunStagedUploadOptions<T> {
  manifest: DocumentStagingManifest;
  uploadChunk: (
    chunk: DocumentStagingChunk,
    chunkIndex: number,
    onUploadProgress: (loaded: number, total: number | undefined) => void,
  ) => Promise<T>;
  onProgress?: (progress: DocumentUploadProgress) => void;
  onManifestChange?: (manifest: DocumentStagingManifest) => void;
  signal?: AbortSignal;
}
