import {
  AESEncryptionKey,
  AESSealedData,
  CryptoDigestAlgorithm,
  aesDecryptAsync,
  aesEncryptAsync,
  digest,
  digestStringAsync,
  randomUUID,
} from 'expo-crypto';
import { Directory, File, FileMode, Paths } from 'expo-file-system';

import { apiRequest, authorizedDownloadResponse } from '@/core/api/client';
import { DocumentDownloadAuthorizationSchema } from '@/core/api/contracts';
import { AbortableSemaphore } from '@/core/async/abortable-semaphore';
import { assertSensitiveOfflineStorageAllowed } from '@/core/security/device-risk';

import { excludeAppPrivateUriFromBackup } from './ios-backup';
import { getOrCreateSecret } from './secure-store';
import {
  temporaryViewCacheEvictions,
  type TemporaryViewCacheEntry,
} from './temporary-view-cache-policy';
import {
  VaultChunkContainerError,
  chunkedVaultMagic,
  consumePlaintextStreamBounded,
  encodeVaultChunkFrame,
  isChunkedVaultPrefix,
  maximumChunkedVaultBytes,
  recoverChunkedVault,
  type VaultChunkCipher,
  type VaultChunkReader,
  type VaultChunkRecovery,
} from './vault-chunk-container';
import {
  ALLOWED_DOCUMENT_CONTENT_TYPES,
  MAX_CONCURRENT_DOWNLOADS,
  MAX_DOCUMENT_BYTES,
  assertManagedTemporaryViewUri,
  assertVaultFreeSpace,
  isFreshResumableVaultStagingEntry,
  planVaultOrphanCleanup,
  shouldDiscardManagedCiphertextAfterFailure,
  validateAuthorizedDocumentPath,
  validateDeclaredDocumentLength,
  validateVaultDocument,
  validateVaultDocumentIdentity,
  type VaultDocument,
  type VaultDocumentDownloadRequest,
} from './vault-policy';
import {
  TripVaultWriteCoordinator,
  VaultWriteCoordinator,
} from './vault-write-coordinator';

const vaultWrites = new VaultWriteCoordinator();
const temporaryViewWrites = new TripVaultWriteCoordinator();
const TEMPORARY_VIEW_WRITE_KEY = 'temporary-views';
const VAULT_ROOT_NAME = 'gc-vault-v1';
const TEMPORARY_VIEW_ROOT_NAME = 'gc-secure-view-v1';

export type EncryptedOfflineFile = {
  uri: string;
  encryptedSizeBytes: number;
  checksumSha256: string;
  plaintextSizeBytes: number;
  contentType: string;
  /** Opaque, process-local lease protecting this file until SQLite commits its registration. */
  writeLeaseId?: string;
};

export type RegisteredOfflineFileInspection =
  | { status: 'valid' }
  | { status: 'missing' }
  | { status: 'corrupt' };

export class LocalOfflineCiphertextError extends Error {
  readonly code = 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT';

  constructor(message = 'The local encrypted document copy failed integrity verification.') {
    super(message);
    this.name = 'LocalOfflineCiphertextError';
  }
}

export function isLocalOfflineCiphertextError(error: unknown): error is LocalOfflineCiphertextError {
  return error instanceof LocalOfflineCiphertextError
    || (typeof error === 'object' && error !== null && 'code' in error
      && error.code === 'LOCAL_OFFLINE_CIPHERTEXT_CORRUPT');
}

export type VaultResumeCandidate = Pick<
  VaultDocument,
  'documentId' | 'version' | 'checksumSha256'
>;

type VaultWriteLease = {
  file: File;
};

const activeVaultWrites = new Map<string, VaultWriteLease>();
const activeStagingUris = new Set<string>();
type CachedTemporaryView = TemporaryViewCacheEntry & { file: File };
const cachedTemporaryViews = new Map<string, CachedTemporaryView>();

function temporaryViewCacheKey(input: VaultDocument): string {
  return [
    input.namespace,
    input.tripId,
    input.documentId,
    input.version,
    input.checksumSha256.toLowerCase(),
    input.expectedSizeBytes,
    input.contentType.toLowerCase(),
  ].join('|');
}

function discardCachedTemporaryView(key: string): void {
  const entry = cachedTemporaryViews.get(key);
  cachedTemporaryViews.delete(key);
  if (entry?.file.exists) entry.file.delete();
}

function reusableTemporaryView(input: VaultDocument): File | null {
  const key = temporaryViewCacheKey(input);
  const entry = cachedTemporaryViews.get(key);
  if (!entry) return null;
  if (!entry.file.exists || entry.file.size !== input.expectedSizeBytes) {
    discardCachedTemporaryView(key);
    return null;
  }
  entry.lastAccessedAt = Date.now();
  return entry.file;
}

function cacheTemporaryView(input: VaultDocument, file: File): void {
  const key = temporaryViewCacheKey(input);
  cachedTemporaryViews.set(key, {
    key,
    file,
    sizeBytes: input.expectedSizeBytes,
    lastAccessedAt: Date.now(),
  });
  const entries = [...cachedTemporaryViews.values()];
  for (const evictionKey of temporaryViewCacheEvictions(entries, key)) {
    discardCachedTemporaryView(evictionKey);
  }
}

async function namespaceHash(namespace: string): Promise<string> {
  return (
    await digestStringAsync(CryptoDigestAlgorithm.SHA256, namespace)
  ).slice(0, 32);
}

async function managedVaultRoot(create: boolean): Promise<Directory> {
  const root = new Directory(Paths.document, VAULT_ROOT_NAME);
  if (!root.exists && create) root.create({ idempotent: true, intermediates: true });
  if (root.exists) await excludeAppPrivateUriFromBackup(root.uri);
  return root;
}

async function managedTemporaryViewRoot(create: boolean): Promise<Directory> {
  const root = new Directory(Paths.cache, TEMPORARY_VIEW_ROOT_NAME);
  if (!root.exists && create) root.create({ idempotent: true, intermediates: true });
  if (root.exists) await excludeAppPrivateUriFromBackup(root.uri);
  return root;
}

function assertTripIdentity(tripId: string): void {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(tripId)) {
    throw new Error('Invalid trip identity.');
  }
}

async function namespaceDirectory(namespace: string): Promise<Directory> {
  const root = new Directory(await managedVaultRoot(true), await namespaceHash(namespace));
  if (!root.exists) root.create({ idempotent: true, intermediates: true });
  return root;
}

async function vaultDirectory(namespace: string, tripId: string): Promise<Directory> {
  const root = new Directory(await namespaceDirectory(namespace), tripId);
  if (!root.exists) root.create({ idempotent: true, intermediates: true });
  return root;
}

function aad(input: VaultDocument): Uint8Array {
  return new TextEncoder().encode(
    `${input.namespace}|${input.tripId}|${input.documentId}|${input.version}|${input.checksumSha256}`,
  );
}

function offlineFile(
  root: Directory,
  documentId: string,
  version: number,
  checksumSha256: string,
): File {
  return new File(root, `${documentId}.${version}.${checksumSha256.toLowerCase()}.gcv`);
}

function legacyOfflineFile(root: Directory, documentId: string, version: number): File {
  return new File(root, `${documentId}.${version}.gcv`);
}

function resumableStagingFile(root: Directory, input: VaultDocument): File {
  return new File(
    root,
    `.${input.documentId}.${input.version}.${input.checksumSha256.toLowerCase()}.resume.tmp`,
  );
}

function retainVaultWrite(file: File): string {
  const leaseId = randomUUID();
  activeVaultWrites.set(leaseId, { file });
  return leaseId;
}

export function finalizeEncryptedOfflineFile(file: EncryptedOfflineFile): void {
  if (file.writeLeaseId) activeVaultWrites.delete(file.writeLeaseId);
}

export function discardEncryptedOfflineFile(
  file: EncryptedOfflineFile,
  preserveRegisteredUri?: string | null,
): void {
  if (!file.writeLeaseId) return;
  const lease = activeVaultWrites.get(file.writeLeaseId);
  activeVaultWrites.delete(file.writeLeaseId);
  if (!lease || lease.file.uri === preserveRegisteredUri) return;
  if (lease.file.exists) lease.file.delete();
}

async function sha256(bytes: Uint8Array): Promise<string> {
  let input: ArrayBuffer;
  if (
    bytes.buffer instanceof ArrayBuffer &&
    bytes.byteOffset === 0 &&
    bytes.byteLength === bytes.buffer.byteLength
  ) {
    input = bytes.buffer;
  } else {
    const owned = new Uint8Array(bytes.byteLength);
    owned.set(bytes);
    input = owned.buffer;
  }
  const hashed = new Uint8Array(await digest(CryptoDigestAlgorithm.SHA256, input));
  return Array.from(hashed, (value) => value.toString(16).padStart(2, '0')).join('');
}

function vaultChunkCipher(key: AESEncryptionKey): VaultChunkCipher {
  return {
    seal: async (plaintext, additionalData) => {
      const sealed = await aesEncryptAsync(plaintext, key, { additionalData });
      return sealed.combined('bytes');
    },
    open: async (sealed, additionalData) => aesDecryptAsync(
      AESSealedData.fromCombined(sealed),
      key,
      { additionalData },
    ),
  };
}

function documentAbortError(signal?: AbortSignal): Error {
  if (signal?.reason instanceof Error) return signal.reason;
  const error = new Error('Document download was cancelled.');
  error.name = 'AbortError';
  return error;
}

const downloadSlots = new AbortableSemaphore(MAX_CONCURRENT_DOWNLOADS, documentAbortError);

function assertDocumentOperationActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw documentAbortError(signal);
}

async function waitForDocumentDelay(milliseconds: number, signal?: AbortSignal): Promise<void> {
  assertDocumentOperationActive(signal);
  if (!signal) {
    await new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
    return;
  }
  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = (operation: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', onAbort);
      operation();
    };
    const onAbort = () => finish(() => reject(documentAbortError(signal)));
    const timer = setTimeout(() => finish(resolve), milliseconds);
    signal.addEventListener('abort', onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}

async function withVaultChunkReader<T>(
  file: File,
  operation: (reader: VaultChunkReader) => Promise<T> | T,
): Promise<T> {
  const handle = file.open(FileMode.ReadOnly);
  try {
    return await operation({
      size: file.size,
      read: (offset, length) => {
        const output = new Uint8Array(length);
        let outputOffset = 0;
        handle.offset = offset;
        while (outputOffset < length) {
          const next = handle.readBytes(length - outputOffset);
          if (!next.byteLength) break;
          output.set(next, outputOffset);
          outputOffset += next.byteLength;
        }
        return outputOffset === length ? output : output.subarray(0, outputOffset);
      },
    });
  } finally {
    handle.close();
  }
}

async function recoverEncryptedChunks(
  file: File,
  cipher: VaultChunkCipher,
  input: VaultDocument,
  onPlaintext?: (plaintext: Uint8Array) => void,
  signal?: AbortSignal,
): Promise<VaultChunkRecovery> {
  assertDocumentOperationActive(signal);
  return withVaultChunkReader(file, (reader) => recoverChunkedVault(
    reader,
    cipher,
    aad(input),
    input.expectedSizeBytes,
    (plaintext) => {
      assertDocumentOperationActive(signal);
      onPlaintext?.(plaintext);
    },
  ));
}

async function fileUsesChunkContainer(file: File): Promise<boolean> {
  if (!file.exists || file.size < chunkedVaultMagic().byteLength) return false;
  return withVaultChunkReader(file, (reader) => isChunkedVaultPrefix(
    reader.read(0, chunkedVaultMagic().byteLength),
  ));
}

function initializeEncryptedStaging(file: File): void {
  if (file.exists) file.delete();
  file.create({ overwrite: false, intermediates: true });
  const handle = file.open(FileMode.WriteOnly);
  try {
    handle.writeBytes(chunkedVaultMagic());
  } finally {
    handle.close();
  }
}

async function validateExistingCiphertext(
  file: File,
  key: AESEncryptionKey,
  input: VaultDocument,
  signal?: AbortSignal,
): Promise<boolean> {
  assertDocumentOperationActive(signal);
  if (!file.exists || file.size < 29) return false;
  if (await fileUsesChunkContainer(file)) {
    if (file.size > maximumChunkedVaultBytes(input.expectedSizeBytes)) return false;
    const recovered = await recoverEncryptedChunks(file, vaultChunkCipher(key), input, undefined, signal);
    assertDocumentOperationActive(signal);
    const valid = recovered.plaintextBytes === input.expectedSizeBytes
      && recovered.hasher.hexDigest().toLowerCase() === input.checksumSha256.toLowerCase();
    assertDocumentOperationActive(signal);
    return valid;
  }
  if (file.size > input.expectedSizeBytes + 64) return false;
  assertDocumentOperationActive(signal);
  const sealed = AESSealedData.fromCombined(await file.bytes());
  assertDocumentOperationActive(signal);
  const plaintext = await aesDecryptAsync(sealed, key, { additionalData: aad(input) });
  assertDocumentOperationActive(signal);
  const checksum = await sha256(plaintext);
  assertDocumentOperationActive(signal);
  return plaintext.byteLength === input.expectedSizeBytes
    && checksum.toLowerCase() === input.checksumSha256.toLowerCase();
}

function responseContentType(response: Response): string {
  return (response.headers.get('content-type') ?? '').split(';', 1)[0]?.trim().toLowerCase() ?? '';
}

class DocumentTransferIntegrityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DocumentTransferIntegrityError';
  }
}

function validateDownloadResponse(
  response: Response,
  expectedContentType: string,
  expectedSizeBytes: number,
  rangeStart: number,
): void {
  const contentType = responseContentType(response);
  if (!ALLOWED_DOCUMENT_CONTENT_TYPES.has(contentType) || contentType !== expectedContentType.toLowerCase()) {
    throw new DocumentTransferIntegrityError('Downloaded document type did not match its metadata.');
  }
  if (rangeStart > 0) {
    if (response.status !== 206) {
      throw new DocumentTransferIntegrityError('The server did not honor the document resume request.');
    }
    const expectedRange = `bytes ${rangeStart}-${expectedSizeBytes - 1}/${expectedSizeBytes}`;
    if (response.headers.get('content-range') !== expectedRange) {
      throw new DocumentTransferIntegrityError('The resumed document range did not match its metadata.');
    }
  } else if (response.status !== 200 && response.status !== 206) {
    throw new DocumentTransferIntegrityError('The document server returned an invalid download response.');
  }
  try {
    validateDeclaredDocumentLength(
      response.headers.get('content-length'),
      expectedSizeBytes - rangeStart,
    );
  } catch {
    throw new DocumentTransferIntegrityError(
      'The downloaded document length did not match its signed metadata.',
    );
  }
}

/**
 * Reads one authorized document response into its signed, exact-size buffer.
 *
 * This is exported so the transport state machine can be exercised directly
 * without involving platform key stores or the encrypted filesystem. It is
 * still an internal vault primitive; callers should use
 * `downloadAndEncryptDocument` for production document downloads.
 */
export async function readResponseBytesBounded(
  initialResponse: Response,
  maximumBytes: number,
  expectedContentType: string,
  resume: (offset: number) => Promise<Response>,
  signal?: AbortSignal,
): Promise<Uint8Array> {
  // The signed grant gives an exact upper bound, so fill one preallocated buffer instead
  // of retaining every network chunk and then allocating a second full-size copy.
  const bytes = new Uint8Array(maximumBytes);
  let offset = 0;
  let response = initialResponse;
  let resumeAttempts = 0;

  while (offset < maximumBytes) {
    assertDocumentOperationActive(signal);
    validateDownloadResponse(response, expectedContentType, maximumBytes, offset);
    const reader = response.body?.getReader();
    try {
      if (!reader) {
        const remainder = new Uint8Array(await response.arrayBuffer());
        assertDocumentOperationActive(signal);
        if (offset + remainder.byteLength > maximumBytes) {
          throw new DocumentTransferIntegrityError('Downloaded document exceeded its allowed size.');
        }
        bytes.set(remainder, offset);
        offset += remainder.byteLength;
      } else {
        while (true) {
          const next = await reader.read();
          if (next.done) break;
          if (!next.value?.byteLength) continue;
          if (offset + next.value.byteLength > maximumBytes) {
            await reader.cancel('Document exceeded its allowed size.').catch(() => undefined);
            throw new DocumentTransferIntegrityError('Downloaded document exceeded its allowed size.');
          }
          bytes.set(next.value, offset);
          offset += next.value.byteLength;
        }
      }
      if (offset === maximumBytes) return bytes;
      throw new Error('Document transfer ended before all signed bytes were received.');
    } catch (error) {
      await reader?.cancel().catch(() => undefined);
      if (signal?.aborted) throw documentAbortError(signal);
      if (
        error instanceof DocumentTransferIntegrityError ||
        resumeAttempts >= 2 ||
        offset <= 0
      ) {
        throw error;
      }
      resumeAttempts += 1;
      await waitForDocumentDelay(250 * (2 ** (resumeAttempts - 1)), signal);
      response = await resume(offset);
    }
  }
  return bytes;
}

async function recoverOrResetEncryptedStaging(
  file: File,
  cipher: VaultChunkCipher,
  input: VaultDocument,
  signal?: AbortSignal,
): Promise<VaultChunkRecovery> {
  assertDocumentOperationActive(signal);
  if (file.exists) {
    try {
      if (file.size > maximumChunkedVaultBytes(input.expectedSizeBytes)) {
        throw new VaultChunkContainerError('Encrypted vault staging exceeded its signed size.');
      }
      return await recoverEncryptedChunks(file, cipher, input, undefined, signal);
    } catch {
      if (!shouldDiscardManagedCiphertextAfterFailure(signal)) {
        throw documentAbortError(signal);
      }
      // A partial frame can be left behind if the OS terminates the process during an append.
      // It is never trusted or decrypted further: discard it and restart from the signed source.
      file.delete();
    }
  }
  initializeEncryptedStaging(file);
  return recoverEncryptedChunks(file, cipher, input, undefined, signal);
}

function pruneSupersededResumeStaging(
  root: Directory,
  current: File,
  documentId: string,
): void {
  for (const entry of root.list()) {
    if (
      entry instanceof File
      && entry.uri !== current.uri
      && entry.name.startsWith(`.${documentId}.`)
      && entry.name.endsWith('.resume.tmp')
    ) {
      entry.delete();
    }
  }
}

async function waitForTransferRetry(attempt: number, signal?: AbortSignal): Promise<void> {
  await waitForDocumentDelay(250 * (2 ** (attempt - 1)), signal);
}

async function appendAuthorizedResponse(
  response: Response,
  staging: File,
  cipher: VaultChunkCipher,
  input: VaultDocument,
  recovery: VaultChunkRecovery,
  signal?: AbortSignal,
): Promise<number> {
  validateDownloadResponse(
    response,
    input.contentType,
    input.expectedSizeBytes,
    recovery.plaintextBytes,
  );
  const networkReader = response.body?.getReader();
  if (!networkReader) {
    // Expo SDK 57 provides a native response stream. A whole-body fallback would recreate the
    // exact memory spike this vault format is designed to prevent, so fail safely instead.
    throw new DocumentTransferIntegrityError('The document transport did not provide a stream.');
  }
  const appendHandle = staging.open(FileMode.Append);
  try {
    return await consumePlaintextStreamBounded(
      {
        read: async () => networkReader.read(),
        cancel: async (reason) => networkReader.cancel(reason),
      },
      input.expectedSizeBytes - recovery.plaintextBytes,
      async (plaintext) => {
        const frame = await encodeVaultChunkFrame(
          plaintext,
          cipher,
          aad(input),
          recovery.chunkCount,
          recovery.plaintextBytes,
        );
        appendHandle.writeBytes(frame);
        // Advance only after the complete authenticated frame has been handed to app-private
        // storage. A restart independently rebuilds these values from ciphertext on disk.
        recovery.hasher.update(plaintext);
        recovery.plaintextBytes += plaintext.byteLength;
        recovery.chunkCount += 1;
      },
      signal,
    );
  } catch (error) {
    await networkReader.cancel(error).catch(() => undefined);
    throw error;
  } finally {
    appendHandle.close();
  }
}

/**
 * Removes only managed ciphertext that SQLite no longer references for this exact account/trip.
 * The full plan is validated before deletion, so a corrupt or cross-namespace registration causes
 * no filesystem mutation. In-flight writes are retained until their database outcome is known.
 */
export async function reconcileTripVault(
  namespace: string,
  tripId: string,
  registeredUris: readonly string[],
  resumableDocuments: readonly VaultResumeCandidate[] = [],
): Promise<void> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(tripId)) {
    throw new Error('Invalid trip identity.');
  }
  const releaseTripWrite = vaultWrites.beginDocumentWrite(namespace, tripId);
  try {
    const root = new Directory(Paths.document, VAULT_ROOT_NAME, await namespaceHash(namespace), tripId);
    if (!root.exists) return;

    const files = root.list().filter((entry): entry is File => entry instanceof File);
    const rootPrefix = root.uri.endsWith('/') ? root.uri : `${root.uri}/`;
    const recoverableFinalNames = new Set<string>();
    const resumableNames = new Set(resumableDocuments.map((document) => {
      validateVaultDocumentIdentity({ namespace, tripId, ...document });
      if (!/^[0-9a-f]{64}$/i.test(document.checksumSha256)) {
        throw new Error('Invalid document checksum.');
      }
      recoverableFinalNames.add(
        `${document.documentId}.${document.version}.${document.checksumSha256.toLowerCase()}.gcv`,
      );
      return `.${document.documentId}.${document.version}.${document.checksumSha256.toLowerCase()}.resume.tmp`;
    }));
    const freshResumableUris = files
      .filter((file) => (
        resumableNames.has(file.name)
        && isFreshResumableVaultStagingEntry({
          name: file.name,
          uri: file.uri,
          lastModified: file.lastModified,
        })
      ))
      .map((file) => file.uri);
    const recoverableFinalUris = files
      .filter((file) => recoverableFinalNames.has(file.name))
      .map((file) => file.uri);
    const activeUris = [
      ...[...activeVaultWrites.values()].map(({ file }) => file.uri),
      ...activeStagingUris,
      ...freshResumableUris,
      ...recoverableFinalUris,
    ].filter((uri) => uri.startsWith(rootPrefix) && !uri.slice(rootPrefix.length).includes('/'));
    const deletionPlan = planVaultOrphanCleanup(
      root.uri,
      files.map((file) => ({
        name: file.name,
        uri: file.uri,
        lastModified: file.lastModified,
      })),
      registeredUris,
      activeUris,
    );
    const byUri = new Map(files.map((file) => [file.uri, file]));
    for (const uri of deletionPlan) {
      const file = byUri.get(uri);
      if (file?.exists) file.delete();
    }
  } finally {
    releaseTripWrite();
  }
}

/**
 * Authenticates every encrypted frame and verifies the recovered plaintext checksum before an
 * SQLite registration may be treated as a completed offline job. A missing/corrupt local file is
 * explicitly separate from a server transfer-integrity failure: callers may safely unregister and
 * redownload local damage, while signed provider metadata mismatches remain terminal.
 */
export async function inspectRegisteredOfflineFile(
  input: VaultDocument & { encryptedUri: string },
  signal?: AbortSignal,
): Promise<RegisteredOfflineFileInspection> {
  validateVaultDocument(input);
  assertDocumentOperationActive(signal);
  const releaseTripWrite = vaultWrites.beginDocumentWrite(input.namespace, input.tripId);
  try {
    const root = new Directory(
      Paths.document,
      VAULT_ROOT_NAME,
      await namespaceHash(input.namespace),
      input.tripId,
    );
    // Validate the database-controlled path before reading it. Only the immutable checksum-bound
    // filename and its legacy predecessor are accepted for this exact document/version.
    planVaultOrphanCleanup(root.uri, [], [input.encryptedUri]);
    const expected = offlineFile(root, input.documentId, input.version, input.checksumSha256).uri;
    const legacy = legacyOfflineFile(root, input.documentId, input.version).uri;
    if (input.encryptedUri !== expected && input.encryptedUri !== legacy) {
      throw new Error('Registered offline document path did not match its metadata.');
    }
    if (!root.exists) return { status: 'missing' };
    const file = new File(input.encryptedUri);
    if (!file.exists) return { status: 'missing' };

    const encodedKey = await getOrCreateSecret(input.namespace, 'vault-key');
    const key = await AESEncryptionKey.import(encodedKey, 'hex');
    try {
      const valid = await validateExistingCiphertext(file, key, input, signal);
      return valid ? { status: 'valid' } : { status: 'corrupt' };
    } catch {
      if (signal?.aborted) throw documentAbortError(signal);
      // Key-store/import errors happen above and remain retryable infrastructure failures. Once a
      // key is available, any parse/authentication/checksum failure is damage to this local copy.
      return { status: 'corrupt' };
    }
  } finally {
    releaseTripWrite();
  }
}

export async function removeRegisteredOfflineFile(
  input: VaultDocument & { encryptedUri: string },
): Promise<void> {
  validateVaultDocument(input);
  const releaseTripWrite = vaultWrites.beginDocumentWrite(input.namespace, input.tripId);
  try {
    const root = new Directory(
      Paths.document,
      VAULT_ROOT_NAME,
      await namespaceHash(input.namespace),
      input.tripId,
    );
    planVaultOrphanCleanup(root.uri, [], [input.encryptedUri]);
    const expected = offlineFile(root, input.documentId, input.version, input.checksumSha256).uri;
    const legacy = legacyOfflineFile(root, input.documentId, input.version).uri;
    if (input.encryptedUri !== expected && input.encryptedUri !== legacy) {
      throw new Error('Registered offline document path did not match its metadata.');
    }
    const file = new File(input.encryptedUri);
    if (file.exists) file.delete();
  } finally {
    releaseTripWrite();
  }
}

export async function downloadAndEncryptDocument(
  input: VaultDocumentDownloadRequest,
  signal?: AbortSignal,
): Promise<EncryptedOfflineFile> {
  validateVaultDocumentIdentity(input);
  const releaseTripWrite = vaultWrites.beginDocumentWrite(input.namespace, input.tripId);
  let releaseDownloadSlot: (() => void) | null = null;
  try {
    await assertSensitiveOfflineStorageAllowed();
    releaseDownloadSlot = await downloadSlots.acquire(signal);
    assertDocumentOperationActive(signal);
    const authorization = await apiRequest(
      `/mobile/trips/${input.tripId}/documents/${input.documentId}/authorize?version=${input.version}`,
      {
        method: 'POST',
        body: {},
        schema: DocumentDownloadAuthorizationSchema,
        ...(signal ? { signal } : {}),
      },
    );
    if (
      authorization.document_id !== input.documentId ||
      authorization.version !== input.version ||
      Date.parse(authorization.expires_at) <= Date.now()
    ) {
      throw new Error('The document download authorization was invalid or expired.');
    }
    const resolved: VaultDocument = {
      namespace: input.namespace,
      tripId: input.tripId,
      documentId: input.documentId,
      version: input.version,
      checksumSha256: authorization.checksum_sha256,
      expectedSizeBytes: authorization.size_bytes,
      contentType: authorization.content_type,
    };
    validateVaultDocument(resolved);
    if (
      (input.checksumSha256 !== undefined && input.checksumSha256.toLowerCase() !== resolved.checksumSha256.toLowerCase()) ||
      (input.expectedSizeBytes !== undefined && input.expectedSizeBytes !== resolved.expectedSizeBytes) ||
      (input.contentType !== undefined && input.contentType.toLowerCase() !== resolved.contentType.toLowerCase())
    ) {
      throw new Error('Authorized document metadata did not match the synchronized version.');
    }
    assertVaultFreeSpace(Paths.availableDiskSpace, resolved.expectedSizeBytes);
    validateAuthorizedDocumentPath(
      authorization.content_path,
      input.tripId,
      input.documentId,
      input.version,
    );
    const encodedKey = await getOrCreateSecret(input.namespace, 'vault-key');
    const key = await AESEncryptionKey.import(encodedKey, 'hex');
    const root = await vaultDirectory(resolved.namespace, resolved.tripId);
    // The checksum makes each content revision immutable even if a faulty upstream reuses a
    // version number. The previously registered ciphertext remains valid until SQLite commits.
    const destination = offlineFile(
      root,
      resolved.documentId,
      resolved.version,
      resolved.checksumSha256,
    );
    if (destination.exists) {
      try {
        if (!await validateExistingCiphertext(destination, key, resolved, signal)) {
          throw new Error('Existing ciphertext failed integrity verification.');
        }
        const writeLeaseId = retainVaultWrite(destination);
        return {
          uri: destination.uri,
          encryptedSizeBytes: destination.size,
          checksumSha256: resolved.checksumSha256,
          plaintextSizeBytes: resolved.expectedSizeBytes,
          contentType: resolved.contentType,
          writeLeaseId,
        };
      } catch {
        if (!shouldDiscardManagedCiphertextAfterFailure(signal)) {
          throw documentAbortError(signal);
        }
        destination.delete();
      }
    }

    const staging = resumableStagingFile(root, resolved);
    const stagingUri = staging.uri;
    activeStagingUris.add(stagingUri);
    pruneSupersededResumeStaging(root, staging, resolved.documentId);
    let promoted = false;
    try {
      const cipher = vaultChunkCipher(key);
      let recovery = await recoverOrResetEncryptedStaging(staging, cipher, resolved, signal);
      let transferAttempts = 0;

      while (recovery.plaintextBytes < resolved.expectedSizeBytes) {
        if (signal?.aborted) {
          throw signal.reason instanceof Error
            ? signal.reason
            : new Error('Document download was cancelled.');
        }
        try {
          const response = await authorizedDownloadResponse(
            authorization.content_path,
            authorization.download_token,
            signal,
            recovery.plaintextBytes,
          );
          await appendAuthorizedResponse(response, staging, cipher, resolved, recovery, signal);
          if (recovery.plaintextBytes < resolved.expectedSizeBytes) {
            throw new Error('Document transfer ended before all signed bytes were received.');
          }
        } catch (error) {
          if (signal?.aborted) throw documentAbortError(signal);
          if (
            error instanceof DocumentTransferIntegrityError
            || error instanceof VaultChunkContainerError
          ) {
            if (staging.exists) staging.delete();
            throw error;
          }
          if (transferAttempts >= 2) throw error;
          transferAttempts += 1;
          await waitForTransferRetry(transferAttempts, signal);
          recovery = await recoverOrResetEncryptedStaging(staging, cipher, resolved, signal);
        }
      }

      const checksum = recovery.hasher.hexDigest();
      if (
        recovery.plaintextBytes !== resolved.expectedSizeBytes
        || recovery.plaintextBytes > MAX_DOCUMENT_BYTES
        || checksum.toLowerCase() !== resolved.checksumSha256.toLowerCase()
      ) {
        if (staging.exists) staging.delete();
        throw new DocumentTransferIntegrityError(
          'Downloaded document checksum did not match its metadata.',
        );
      }

      await staging.move(destination);
      promoted = true;

      const writeLeaseId = retainVaultWrite(destination);
      return {
        uri: destination.uri,
        encryptedSizeBytes: destination.size,
        checksumSha256: resolved.checksumSha256,
        plaintextSizeBytes: resolved.expectedSizeBytes,
        contentType: resolved.contentType,
        writeLeaseId,
      };
    } catch (error) {
      // Before this function hands the lease to SQLite, no caller can register the new path.
      if (promoted && destination.exists) destination.delete();
      throw error;
    } finally {
      activeStagingUris.delete(stagingUri);
    }
  } finally {
    releaseDownloadSlot?.();
    releaseTripWrite();
  }
}

function viewerExtension(contentType: string): string {
  switch (contentType.toLowerCase()) {
    case 'application/pdf':
      return 'pdf';
    case 'image/jpeg':
      return 'jpg';
    case 'image/png':
      return 'png';
    case 'image/webp':
      return 'webp';
    default:
      return 'bin';
  }
}

export async function decryptDocumentForViewing(
  input: VaultDocument,
  signal?: AbortSignal,
): Promise<File> {
  validateVaultDocument(input);
  assertDocumentOperationActive(signal);
  const releaseTripWrite = vaultWrites.beginDocumentWrite(input.namespace, input.tripId);
  let releaseTemporaryWrite: (() => void) | null = null;
  try {
    releaseTemporaryWrite = temporaryViewWrites.beginWrite(TEMPORARY_VIEW_WRITE_KEY);
    await assertSensitiveOfflineStorageAllowed();
    const reusable = reusableTemporaryView(input);
    if (reusable) return reusable;
    assertVaultFreeSpace(Paths.availableDiskSpace, input.expectedSizeBytes);
    const root = await vaultDirectory(input.namespace, input.tripId);
    const current = offlineFile(root, input.documentId, input.version, input.checksumSha256);
    // Read legacy deterministic paths created before checksum-bound immutable filenames shipped.
    const legacy = legacyOfflineFile(root, input.documentId, input.version);
    const encrypted = current.exists ? current : legacy;
    if (!encrypted.exists || encrypted.size < 29) {
      throw new LocalOfflineCiphertextError('The local encrypted document copy is unavailable.');
    }

    const encodedKey = await getOrCreateSecret(input.namespace, 'vault-key');
    const key = await AESEncryptionKey.import(encodedKey, 'hex');
    assertDocumentOperationActive(signal);
    const viewRoot = await managedTemporaryViewRoot(true);
    const temporary = new File(viewRoot, `${randomUUID()}.${viewerExtension(input.contentType)}`);
    temporary.create({ overwrite: false, intermediates: true });
    try {
      if (await fileUsesChunkContainer(encrypted)) {
        const viewHandle = temporary.open(FileMode.WriteOnly);
        let recovered: VaultChunkRecovery;
        let temporaryWriteError: unknown = null;
        try {
          try {
            recovered = await recoverEncryptedChunks(
              encrypted,
              vaultChunkCipher(key),
              input,
              (plaintext) => {
                try {
                  viewHandle.writeBytes(plaintext);
                } catch (error) {
                  temporaryWriteError = error;
                  throw error;
                }
              },
              signal,
            );
          } catch {
            if (signal?.aborted) throw documentAbortError(signal);
            if (temporaryWriteError) throw temporaryWriteError;
            throw new LocalOfflineCiphertextError();
          }
        } finally {
          viewHandle.close();
        }
        if (
          recovered.plaintextBytes !== input.expectedSizeBytes
          || recovered.hasher.hexDigest().toLowerCase() !== input.checksumSha256.toLowerCase()
        ) {
          throw new LocalOfflineCiphertextError();
        }
      } else {
        // Legacy v1 ciphertext remains readable while all new downloads use bounded v2 chunks.
        let plaintext: Uint8Array;
        try {
          const sealed = AESSealedData.fromCombined(await encrypted.bytes());
          assertDocumentOperationActive(signal);
          plaintext = await aesDecryptAsync(sealed, key, { additionalData: aad(input) });
          assertDocumentOperationActive(signal);
        } catch {
          if (signal?.aborted) throw documentAbortError(signal);
          throw new LocalOfflineCiphertextError();
        }
        if (
          plaintext.byteLength !== input.expectedSizeBytes
          || (await sha256(plaintext)).toLowerCase() !== input.checksumSha256.toLowerCase()
        ) {
          throw new LocalOfflineCiphertextError();
        }
        assertDocumentOperationActive(signal);
        temporary.write(plaintext);
      }
      cacheTemporaryView(input, temporary);
      return temporary;
    } catch (error) {
      if (temporary.exists) temporary.delete();
      throw error;
    }
  } finally {
    releaseTemporaryWrite?.();
    releaseTripWrite();
  }
}

export function removeTemporaryView(file: File): void {
  const viewRoot = new Directory(Paths.cache, TEMPORARY_VIEW_ROOT_NAME);
  assertManagedTemporaryViewUri(viewRoot.uri, file.uri);
  for (const [key, entry] of cachedTemporaryViews) {
    if (entry.file.uri === file.uri) cachedTemporaryViews.delete(key);
  }
  if (file.exists) file.delete();
}

export function releaseTemporaryView(file: File): void {
  const viewRoot = new Directory(Paths.cache, TEMPORARY_VIEW_ROOT_NAME);
  assertManagedTemporaryViewUri(viewRoot.uri, file.uri);
  const cached = [...cachedTemporaryViews.values()].find((entry) => entry.file.uri === file.uri);
  if (cached && file.exists) {
    cached.lastAccessedAt = Date.now();
    return;
  }
  if (file.exists) file.delete();
}

export async function purgeTemporaryViews(): Promise<void> {
  await temporaryViewWrites.beginPurge(TEMPORARY_VIEW_WRITE_KEY);
  let acknowledged = false;
  try {
    cachedTemporaryViews.clear();
    const root = new Directory(Paths.cache, TEMPORARY_VIEW_ROOT_NAME);
    if (root.exists) root.delete();
    acknowledged = true;
  } finally {
    temporaryViewWrites.endPurgeAttempt(TEMPORARY_VIEW_WRITE_KEY);
    if (acknowledged) temporaryViewWrites.completePurge(TEMPORARY_VIEW_WRITE_KEY);
  }
}

export async function deleteVaultNamespace(namespace: string): Promise<void> {
  const root = new Directory(Paths.document, VAULT_ROOT_NAME, await namespaceHash(namespace));
  if (root.exists) root.delete();
  await purgeTemporaryViews();
}

export function beginVaultNamespacePurge(namespace: string): Promise<void> {
  return vaultWrites.beginNamespacePurge(namespace);
}

export function finishVaultNamespacePurge(namespace: string, acknowledged: boolean): void {
  vaultWrites.finishNamespacePurge(namespace, acknowledged);
}

export async function protectManagedVaultStorageFromBackup(): Promise<void> {
  await managedVaultRoot(false);
  await managedTemporaryViewRoot(false);
}

export async function deleteAllManagedVaultStorage(): Promise<void> {
  await vaultWrites.beginGlobalPurge();
  let acknowledged = false;
  try {
    if (activeVaultWrites.size || activeStagingUris.size) {
      throw new Error('Managed vault reset cannot race an uncommitted document write.');
    }
    await purgeTemporaryViews();
    const root = new Directory(Paths.document, VAULT_ROOT_NAME);
    if (root.exists) root.delete();
    acknowledged = true;
  } finally {
    vaultWrites.finishGlobalPurge(acknowledged);
  }
}

export async function deleteTripVault(namespace: string, tripId: string): Promise<void> {
  assertTripIdentity(tripId);
  const finishAttempt = await vaultWrites.beginTripPurge(namespace, tripId);
  try {
    const root = new Directory(Paths.document, VAULT_ROOT_NAME, await namespaceHash(namespace), tripId);
    if (root.exists) root.delete();
  } finally {
    finishAttempt();
  }
}

/** Release the process-local write fence only after SQLite removes the matching tombstone. */
export function completeTripVaultPurge(namespace: string, tripId: string): void {
  assertTripIdentity(tripId);
  vaultWrites.completeTripPurge(namespace, tripId);
}

export async function deleteOfflineDocument(
  namespace: string,
  tripId: string,
  documentId: string,
): Promise<void> {
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!uuid.test(tripId) || !uuid.test(documentId)) throw new Error('Invalid document identity.');
  const releaseTripWrite = vaultWrites.beginDocumentWrite(namespace, tripId);
  try {
    const root = new Directory(Paths.document, VAULT_ROOT_NAME, await namespaceHash(namespace), tripId);
    if (!root.exists) return;
    for (const entry of root.list()) {
      const isFinal = entry.name.startsWith(`${documentId}.`) && entry.name.endsWith('.gcv');
      const isStaging = entry.name.startsWith(`.${documentId}.`) && entry.name.endsWith('.tmp');
      if (entry instanceof File && (isFinal || isStaging)) entry.delete();
    }
  } finally {
    releaseTripWrite();
  }
}

export async function vaultUsageBytes(namespace: string): Promise<number> {
  const root = new Directory(Paths.document, VAULT_ROOT_NAME, await namespaceHash(namespace));
  return root.exists ? (root.size ?? 0) : 0;
}

export const documentVaultPolicy = Object.freeze({
  maxDocumentBytes: MAX_DOCUMENT_BYTES,
  maxConcurrentDownloads: MAX_CONCURRENT_DOWNLOADS,
  allowedContentTypes: [...ALLOWED_DOCUMENT_CONTENT_TYPES],
});

export type { VaultDocument } from './vault-policy';
export { validateDeclaredDocumentLength, validateVaultDocument } from './vault-policy';
