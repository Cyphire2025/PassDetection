export const MAX_DOCUMENT_BYTES = 25 * 1024 * 1024;
export const MAX_CONCURRENT_DOWNLOADS = 2;
export const MIN_FREE_SPACE_RESERVE_BYTES = 50 * 1024 * 1024;
export const ALLOWED_DOCUMENT_CONTENT_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/webp',
  'application/octet-stream',
]);

export type VaultDocument = {
  namespace: string;
  tripId: string;
  documentId: string;
  version: number;
  checksumSha256: string;
  expectedSizeBytes: number;
  contentType: string;
};

export function validateVaultDocument(input: VaultDocument): void {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuid.test(input.tripId) || !uuid.test(input.documentId)) throw new Error('Invalid document identity.');
  if (!Number.isSafeInteger(input.version) || input.version < 1) throw new Error('Invalid document version.');
  if (!/^[0-9a-f]{64}$/i.test(input.checksumSha256)) throw new Error('Invalid document checksum.');
  if (!Number.isSafeInteger(input.expectedSizeBytes) || input.expectedSizeBytes < 1 || input.expectedSizeBytes > MAX_DOCUMENT_BYTES) {
    throw new Error('Document size is outside the offline policy.');
  }
  if (!ALLOWED_DOCUMENT_CONTENT_TYPES.has(input.contentType.toLowerCase())) {
    throw new Error('Document type is not allowed for offline storage.');
  }
}

export function validateDeclaredDocumentLength(value: string | null, expectedSizeBytes: number): void {
  if (!value || !/^\d+$/.test(value)) throw new Error('Downloaded document did not provide a safe content length.');
  if (Number(value) !== expectedSizeBytes || Number(value) > MAX_DOCUMENT_BYTES) {
    throw new Error('Downloaded document size did not match its metadata.');
  }
}

export function requiredVaultFreeSpace(expectedSizeBytes: number): number {
  // Keep room for the plaintext buffer, ciphertext, an atomic temporary copy,
  // and a reserve so a document operation cannot exhaust the device filesystem.
  return expectedSizeBytes * 3 + MIN_FREE_SPACE_RESERVE_BYTES;
}

export function assertVaultFreeSpace(
  availableBytes: number | null | undefined,
  expectedSizeBytes: number,
): void {
  if (availableBytes == null || !Number.isFinite(availableBytes) || availableBytes < 0) return;
  if (availableBytes < requiredVaultFreeSpace(expectedSizeBytes)) {
    throw new Error('There is not enough free device storage to secure this document offline.');
  }
}
