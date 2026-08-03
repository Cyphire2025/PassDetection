export const MAX_DOCUMENT_BYTES = 25 * 1024 * 1024;
export const MAX_CONCURRENT_DOWNLOADS = 2;
export const LARGE_DOCUMENT_SERIAL_THRESHOLD_BYTES = 8 * 1024 * 1024;
export const MIN_FREE_SPACE_RESERVE_BYTES = 50 * 1024 * 1024;
export const VAULT_RESUME_STAGING_RETENTION_MS = 24 * 60 * 60 * 1_000;
export const ALLOWED_DOCUMENT_CONTENT_TYPES = new Set([
  'application/pdf',
  'image/jpeg',
  'image/png',
  'image/webp',
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

export type VaultDocumentIdentity = Pick<VaultDocument, 'namespace' | 'tripId' | 'documentId' | 'version'>;

export type VaultDocumentDownloadRequest = VaultDocumentIdentity & {
  checksumSha256?: string;
  expectedSizeBytes?: number;
  contentType?: string;
};

export type VaultDirectoryEntry = {
  name: string;
  uri: string;
  lastModified?: number | null;
};

const UUID_PATTERN = '[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const MANAGED_FINAL_FILE = new RegExp(
  `^${UUID_PATTERN}\\.[1-9][0-9]*\\.(?:[0-9a-f]{64}\\.)?gcv$`,
  'i',
);
const MANAGED_STAGING_FILE = new RegExp(
  `^\\.${UUID_PATTERN}\\.[1-9][0-9]*\\.${UUID_PATTERN}\\.tmp$`,
  'i',
);
const RESUMABLE_STAGING_FILE = new RegExp(
  `^\\.${UUID_PATTERN}\\.[1-9][0-9]*\\.[0-9a-f]{64}\\.resume\\.tmp$`,
  'i',
);
const MANAGED_TEMPORARY_VIEW_FILE = new RegExp(
  `^${UUID_PATTERN}\\.(?:pdf|jpg|png|webp|bin)$`,
  'i',
);

function vaultRootPrefix(rootUri: string): string {
  if (!rootUri) throw new Error('Invalid vault root.');
  return rootUri.endsWith('/') ? rootUri : `${rootUri}/`;
}

function assertImmediateVaultChild(rootUri: string, uri: string): void {
  const prefix = vaultRootPrefix(rootUri);
  if (!uri.startsWith(prefix)) throw new Error('Vault registration escaped its account and trip boundary.');
  const relative = uri.slice(prefix.length);
  if (!relative || relative.includes('/')) {
    throw new Error('Vault registration escaped its account and trip boundary.');
  }
}

/**
 * Validates a plaintext-view cleanup target before the filesystem is touched. Temporary views
 * are random, immediate children of the one managed cache directory; prefix-confusable siblings,
 * traversal segments, nested paths and platform-specific separators all fail closed.
 */
export function assertManagedTemporaryViewUri(rootUri: string, uri: string): void {
  if (!rootUri || !uri || rootUri.includes('\\') || uri.includes('\\')) {
    throw new Error('Refusing to remove an untrusted temporary-view path.');
  }
  const normalizedRoot = rootUri.replace(/\/+$/, '');
  const prefix = `${normalizedRoot}/`;
  if (!uri.startsWith(prefix)) {
    throw new Error('Refusing to remove an untrusted temporary-view path.');
  }
  const relative = uri.slice(prefix.length);
  if (!relative || relative.includes('/') || !MANAGED_TEMPORARY_VIEW_FILE.test(relative)) {
    throw new Error('Refusing to remove an untrusted temporary-view path.');
  }
}

/**
 * Cancellation is not evidence of corruption. Preserve resumable staging and already-validated
 * ciphertext when validation is interrupted so the next operation can resume or authenticate it.
 */
export function shouldDiscardManagedCiphertextAfterFailure(signal?: AbortSignal): boolean {
  return signal?.aborted !== true;
}

export function isManagedVaultFileName(name: string): boolean {
  return MANAGED_FINAL_FILE.test(name)
    || MANAGED_STAGING_FILE.test(name)
    || RESUMABLE_STAGING_FILE.test(name);
}

export function isResumableVaultStagingFileName(name: string): boolean {
  return RESUMABLE_STAGING_FILE.test(name);
}

export function isFreshResumableVaultStagingEntry(
  entry: VaultDirectoryEntry,
  currentTimeMs = Date.now(),
): boolean {
  return isResumableVaultStagingFileName(entry.name)
    && typeof entry.lastModified === 'number'
    && Number.isFinite(entry.lastModified)
    && Math.max(0, currentTimeMs - entry.lastModified) <= VAULT_RESUME_STAGING_RETENTION_MS;
}

/**
 * Computes a complete deletion plan before any filesystem mutation. Invalid database paths
 * fail closed, while unknown/future files remain untouched. Callers must pass only the
 * registrations selected for this exact account namespace and trip.
 */
export function planVaultOrphanCleanup(
  rootUri: string,
  entries: readonly VaultDirectoryEntry[],
  registeredUris: readonly string[],
  activeWriteUris: readonly string[] = [],
): string[] {
  for (const uri of registeredUris) assertImmediateVaultChild(rootUri, uri);
  for (const uri of activeWriteUris) assertImmediateVaultChild(rootUri, uri);
  for (const entry of entries) {
    assertImmediateVaultChild(rootUri, entry.uri);
    if (entry.uri.slice(vaultRootPrefix(rootUri).length) !== entry.name) {
      throw new Error('Vault directory entry did not match its resolved path.');
    }
  }

  const retained = new Set([...registeredUris, ...activeWriteUris]);
  return entries
    .filter((entry) => isManagedVaultFileName(entry.name) && !retained.has(entry.uri))
    .map((entry) => entry.uri);
}

export function validateVaultDocumentIdentity(input: VaultDocumentIdentity): void {
  const uuid = new RegExp(`^${UUID_PATTERN}$`, 'i');
  if (!uuid.test(input.tripId) || !uuid.test(input.documentId)) throw new Error('Invalid document identity.');
  if (!Number.isSafeInteger(input.version) || input.version < 1) throw new Error('Invalid document version.');
}

export function validateVaultDocument(input: VaultDocument): void {
  validateVaultDocumentIdentity(input);
  if (!/^[0-9a-f]{64}$/i.test(input.checksumSha256)) throw new Error('Invalid document checksum.');
  if (!Number.isSafeInteger(input.expectedSizeBytes) || input.expectedSizeBytes < 1 || input.expectedSizeBytes > MAX_DOCUMENT_BYTES) {
    throw new Error('Document size is outside the offline policy.');
  }
  if (!ALLOWED_DOCUMENT_CONTENT_TYPES.has(input.contentType.toLowerCase())) {
    throw new Error('Document type is not allowed for offline storage.');
  }
}

export function validateDeclaredDocumentLength(value: string | null, expectedSizeBytes: number): void {
  // Reverse proxies and chunked transfers may legitimately omit Content-Length. The response
  // body is still bounded and its final size must exactly match the signed metadata.
  if (value === null) return;
  if (!/^\d+$/.test(value)) throw new Error('Downloaded document provided an invalid content length.');
  if (Number(value) !== expectedSizeBytes || Number(value) > MAX_DOCUMENT_BYTES) {
    throw new Error('Downloaded document size did not match its metadata.');
  }
}

export function validateAuthorizedDocumentPath(
  path: string,
  tripId: string,
  documentId: string,
  version: number,
): void {
  const parsed = new URL(path, 'https://mobile.invalid');
  const expectedSuffix = `/mobile/trips/${tripId}/documents/${documentId}/content`;
  const pathnameMatches =
    parsed.pathname === expectedSuffix ||
    parsed.pathname === `/api/v1${expectedSuffix}`;
  if (!pathnameMatches) {
    throw new Error('The document authorization did not match the requested document.');
  }
  const parameters = [...parsed.searchParams.keys()];
  if (
    parameters.length !== 1 ||
    parameters[0] !== 'version' ||
    parsed.searchParams.get('version') !== String(version)
  ) {
    throw new Error('The document authorization did not match the requested version.');
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

export function offlinePrefetchConcurrency(
  sizes: readonly (number | null | undefined)[],
): number {
  return sizes.some(
    (size) => typeof size === 'number' && size >= LARGE_DOCUMENT_SERIAL_THRESHOLD_BYTES,
  ) ? 1 : MAX_CONCURRENT_DOWNLOADS;
}
