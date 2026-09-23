import type { EcrItem } from "@/types/ecr-checker.types";

export const MAX_ECR_FILES = 1_000;
export const MAX_ECR_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_ECR_CHUNK_BYTES = 20 * 1024 * 1024;
const MAX_CHUNK_FILES = 5;
const UPLOAD_CONCURRENCY = 3;
const STORAGE_PREFIX = "passdetection:ecr-upload:";

export interface EcrUploadEntry {
  file: File;
  clientId: string;
}

interface StoredEntry {
  clientId: string;
  fingerprint: string;
}

export interface EcrUploadProgress {
  completed: number;
  total: number;
  percent: number;
}

export function validateEcrFiles(files: File[]) {
  if (!files.length || files.length > MAX_ECR_FILES) {
    throw new Error(`Choose between 1 and ${MAX_ECR_FILES.toLocaleString()} images.`);
  }
  for (const file of files) {
    const supported = ["image/jpeg", "image/png", "image/webp"].includes(file.type)
      || (!file.type && /\.(jpe?g|png|webp)$/i.test(file.name));
    if (!supported) throw new Error(`${file.name}: choose a JPG, PNG or WebP image.`);
    if (!file.size || file.size > MAX_ECR_FILE_BYTES) {
      throw new Error(`${file.name}: images must be non-empty and no larger than 10 MB.`);
    }
  }
}

function fingerprint(file: File) {
  return JSON.stringify([file.name, file.size, file.lastModified, file.type]);
}

export function createEcrUploadEntries(files: File[]): EcrUploadEntry[] {
  validateEcrFiles(files);
  return files.map((file) => ({ file, clientId: crypto.randomUUID() }));
}

export function storeEcrUpload(batchId: string, entries: EcrUploadEntry[]) {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${batchId}`, JSON.stringify({
      version: 1,
      entries: entries.map(({ file, clientId }) => ({ clientId, fingerprint: fingerprint(file) })),
    }));
  } catch {
    // Uploading still works when browser storage is disabled; the in-memory
    // selection keeps stable IDs for retries while this page remains open.
  }
}

export function clearEcrUpload(batchId: string) {
  try { sessionStorage.removeItem(`${STORAGE_PREFIX}${batchId}`); } catch { /* Storage can be disabled. */ }
}

export function restoreEcrUpload(batchId: string, files: File[]): EcrUploadEntry[] {
  validateEcrFiles(files);
  let stored: { version: number; entries: StoredEntry[] };
  try {
    stored = JSON.parse(sessionStorage.getItem(`${STORAGE_PREFIX}${batchId}`) ?? "null");
    if (stored?.version !== 1 || !Array.isArray(stored.entries) || stored.entries.length !== files.length) {
      throw new Error("Invalid selection");
    }
  } catch {
    throw new Error("The original upload selection is unavailable. Start a new batch with all the images.");
  }
  const available = new Map<string, File[]>();
  for (const file of files) {
    const key = fingerprint(file);
    const matches = available.get(key) ?? [];
    matches.push(file);
    available.set(key, matches);
  }
  return stored.entries.map((entry) => {
    const file = available.get(entry.fingerprint)?.shift();
    if (!file || typeof entry.clientId !== "string") {
      throw new Error("To resume, choose the same original images again. Their selection order can differ.");
    }
    return { file, clientId: entry.clientId };
  });
}

export function chunkEcrEntries(entries: EcrUploadEntry[]) {
  const chunks: EcrUploadEntry[][] = [];
  let chunk: EcrUploadEntry[] = [];
  let bytes = 0;
  for (const entry of entries) {
    if (chunk.length >= MAX_CHUNK_FILES || bytes + entry.file.size > MAX_ECR_CHUNK_BYTES) {
      if (chunk.length) chunks.push(chunk);
      chunk = [];
      bytes = 0;
    }
    chunk.push(entry);
    bytes += entry.file.size;
  }
  if (chunk.length) chunks.push(chunk);
  return chunks;
}

/** Bounded parallel uploads; settled workers preserve successful progress on failure. */
export async function uploadEcrEntries({ entries, existingItems, uploadChunk, onProgress, signal }: {
  entries: EcrUploadEntry[];
  existingItems: Pick<EcrItem, "client_id">[];
  uploadChunk: (chunk: EcrUploadEntry[], report: (fraction: number) => void) => Promise<unknown>;
  onProgress: (progress: EcrUploadProgress) => void;
  signal: AbortSignal;
}) {
  const committedIds = new Set(existingItems.map((item) => item.client_id));
  const pending = entries.filter((entry) => !committedIds.has(entry.clientId));
  const chunks = chunkEcrEntries(pending);
  const sizes = chunks.map((chunk) => chunk.reduce((sum, entry) => sum + entry.file.size, 0));
  const totalBytes = entries.reduce((sum, entry) => sum + entry.file.size, 0);
  const committedBytes = totalBytes - sizes.reduce((sum, size) => sum + size, 0);
  const fractions = new Array<number>(chunks.length).fill(0);
  let completed = entries.length - pending.length;
  let cursor = 0;
  let failure: unknown;
  const report = () => onProgress({
    completed,
    total: entries.length,
    percent: Math.min(100, Math.floor(100 * (committedBytes + fractions.reduce((sum, value, index) => sum + value * sizes[index], 0)) / totalBytes)),
  });
  report();
  await Promise.all(Array.from({ length: Math.min(UPLOAD_CONCURRENCY, chunks.length) }, async () => {
    while (!failure && cursor < chunks.length && !signal.aborted) {
      const index = cursor++;
      try {
        await uploadChunk(chunks[index], (fraction) => {
          // Sending bytes is only 90% of a chunk; storage acknowledgement
          // must arrive before the upload can be shown as complete.
          fractions[index] = Math.min(0.9, Math.max(0, fraction) * 0.9);
          report();
        });
        fractions[index] = 1;
        completed += chunks[index].length;
        report();
      } catch (error) {
        failure = error;
      }
    }
  }));
  signal.throwIfAborted();
  if (failure) throw failure;
}

export function ecrErrorMessage(error: unknown) {
  if (error && typeof error === "object" && "message" in error && typeof error.message === "string") {
    return error.message;
  }
  return "The request could not finish. Please try again.";
}
