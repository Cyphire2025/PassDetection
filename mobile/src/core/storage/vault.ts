import {
  AESEncryptionKey,
  AESSealedData,
  CryptoDigestAlgorithm,
  aesDecryptAsync,
  digestStringAsync,
  randomUUID,
} from 'expo-crypto';
import { Directory, File, FileMode, Paths } from 'expo-file-system';

import { apiRequest } from '@/core/api/client';
import { DocumentDownloadAuthorizationSchema } from '@/core/api/contracts';
import { AbortableSemaphore } from '@/core/async/abortable-semaphore';
import { AbortableSharedTaskRegistry } from '@/core/async/abortable-shared-task';
import { assertSensitiveOfflineStorageAllowed } from '@/core/security/device-risk';
import { createDocumentAuthorizationIntegrityProof } from '@/core/security/app-integrity';

import { excludeAppPrivateUriFromBackup } from './ios-backup';
import { getOrCreateSecret } from './secure-store';
import {
  deleteAllMyPhotosRoots,
  deleteMyPhotosNamespaceRoot,
  deleteMyPhotosTripRoot,
  myPhotosStorageWrites,
  protectManagedMyPhotosStorageFromBackup,
  purgeMyPhotosTemporaryRoots,
} from './my-photos-storage-lifecycle';
import {
  VaultChunkContainerError,
  maximumChunkedVaultBytes,
  type VaultChunkRecovery,
} from './vault-chunk-container';
import {
  fileUsesChunkContainer,
  recoverEncryptedChunks,
  recoverOrResetEncryptedStaging,
  sha256,
  validateExistingCiphertext,
  vaultChunkCipher,
  vaultDocumentAdditionalData,
} from './vault-crypto';
import {
  beginNativeTransferStagingWrite,
  DocumentTransferIntegrityError,
  downloadAndAppendAuthorizedFile,
  protectNativeTransferStagingFromBackup,
  purgeNativeTransferStaging,
} from './vault-native-transfer';
import {
  assertDocumentOperationActive,
  documentAbortError,
  waitForDocumentDelay,
} from './vault-operation';
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
  validateVaultDocument,
  validateVaultDocumentIdentity,
  type VaultDocument,
  type VaultDocumentDownloadRequest,
} from './vault-policy';
import {
  TripVaultWriteCoordinator,
  VaultWriteCoordinator,
} from './vault-write-coordinator';
import {
  DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
  type VaultStorageQuotaPolicy,
} from './vault-quota-policy';
import {
  inspectVaultStorageQuotaWithRuntime,
  reserveVaultStorageQuotaWithRuntime,
  type VaultQuotaEvictionCandidate,
  type VaultStorageQuotaReclaimer,
  type VaultStorageQuotaRuntime,
  type VaultStorageQuotaStatus,
} from './vault-storage-quota';

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
type ActiveTemporaryView = { file: File; leases: number };
const activeTemporaryViews = new Map<string, ActiveTemporaryView>();
const temporaryViewDecryptions = new AbortableSharedTaskRegistry<string, File>();

function temporaryViewOperationKey(input: VaultDocument): string {
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

const vaultStorageQuotaRuntime: VaultStorageQuotaRuntime = {
  activeEncryptedUris: () => [
    ...[...activeVaultWrites.values()].map(({ file }) => file.uri),
    ...activeStagingUris,
  ],
  managedVaultRoot,
  namespaceHash,
};

/**
 * Reports encrypted-vault pressure without exposing account identifiers or document paths.
 * Active writes are represented by their remaining worst-case growth, so the status cannot
 * temporarily under-report capacity while ciphertext is still being streamed.
 */
export function inspectVaultStorageQuota(
  namespace: string,
  policy: VaultStorageQuotaPolicy = DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
): Promise<VaultStorageQuotaStatus> {
  return inspectVaultStorageQuotaWithRuntime(vaultStorageQuotaRuntime, namespace, policy);
}

async function reserveVaultStorageQuota(
  namespace: string,
  staging: File,
  maximumEncryptedBytes: number,
  expectedPlaintextBytes: number,
  reclaimer?: VaultStorageQuotaReclaimer,
  policy: VaultStorageQuotaPolicy = DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
): Promise<() => void> {
  return reserveVaultStorageQuotaWithRuntime(
    vaultStorageQuotaRuntime,
    namespace,
    staging,
    maximumEncryptedBytes,
    expectedPlaintextBytes,
    reclaimer,
    policy,
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

const downloadSlots = new AbortableSemaphore(MAX_CONCURRENT_DOWNLOADS, documentAbortError);

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

/**
 * Removes an already-detached quota plan from the managed vault. The complete path set is
 * validated before any file is touched, and account/trip write leases keep logout and trip purge
 * from racing the cleanup. Missing files are success: a prior killed attempt may already have
 * completed the native deletion while its durable tombstone was still present.
 */
export async function deleteVaultQuotaEvictionCandidates(
  namespace: string,
  candidates: readonly VaultQuotaEvictionCandidate[],
): Promise<void> {
  if (!namespace) throw new Error('A vault account namespace is required.');
  const validated: { candidate: VaultQuotaEvictionCandidate; file: File }[] = [];
  const seen = new Set<string>();
  for (const candidate of candidates) {
    if (
      candidate.namespace !== namespace
      || candidate.retentionClass !== 'evictable'
      || candidate.protectedFromEviction === true
    ) {
      throw new Error('A protected or cross-account vault artifact cannot be evicted.');
    }
    validateVaultDocumentIdentity({
      namespace,
      tripId: candidate.tripId,
      documentId: candidate.documentId,
      version: candidate.version,
    });
    if (!/^[0-9a-f]{64}$/i.test(candidate.checksumSha256)) {
      throw new Error('Invalid document checksum.');
    }
    if (seen.has(candidate.encryptedUri)) {
      throw new Error('Vault quota candidates must have unique encrypted URIs.');
    }
    seen.add(candidate.encryptedUri);
    const root = new Directory(
      Paths.document,
      VAULT_ROOT_NAME,
      await namespaceHash(namespace),
      candidate.tripId,
    );
    planVaultOrphanCleanup(root.uri, [], [candidate.encryptedUri]);
    const expected = offlineFile(
      root,
      candidate.documentId,
      candidate.version,
      candidate.checksumSha256,
    ).uri;
    const legacy = legacyOfflineFile(root, candidate.documentId, candidate.version).uri;
    if (candidate.encryptedUri !== expected && candidate.encryptedUri !== legacy) {
      throw new Error('A vault eviction path did not match its registered metadata.');
    }
    validated.push({ candidate, file: new File(candidate.encryptedUri) });
  }

  const releases: (() => void)[] = [];
  try {
    for (const tripId of new Set(validated.map(({ candidate }) => candidate.tripId))) {
      releases.push(vaultWrites.beginDocumentWrite(namespace, tripId));
    }
    for (const { file } of validated) {
      if (file.exists) file.delete();
    }
  } finally {
    for (const release of releases.reverse()) release();
  }
}

export async function downloadAndEncryptDocument(
  input: VaultDocumentDownloadRequest,
  signal?: AbortSignal,
  quotaReclaimer?: VaultStorageQuotaReclaimer,
): Promise<EncryptedOfflineFile> {
  validateVaultDocumentIdentity(input);
  const releaseTripWrite = vaultWrites.beginDocumentWrite(input.namespace, input.tripId);
  let releaseDownloadSlot: (() => void) | null = null;
  let releaseTransferStaging: (() => void) | null = null;
  try {
    releaseTransferStaging = beginNativeTransferStagingWrite();
    await assertSensitiveOfflineStorageAllowed();
    releaseDownloadSlot = await downloadSlots.acquire(signal);
    assertDocumentOperationActive(signal);
    const integrity = await createDocumentAuthorizationIntegrityProof({
      namespace: input.namespace,
      tripId: input.tripId,
      documentId: input.documentId,
      version: input.version,
    }, signal);
    const authorization = await apiRequest(
      `/mobile/trips/${input.tripId}/documents/${input.documentId}/authorize?version=${input.version}`,
      {
        method: 'POST',
        body: integrity ? { integrity } : {},
        schema: DocumentDownloadAuthorizationSchema,
        timeoutMs: 5_000,
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
    let releaseQuotaReservation: (() => void) | null = null;
    let promoted = false;
    try {
      pruneSupersededResumeStaging(root, staging, resolved.documentId);
      // Reuse of an already-verified final file above needs no additional disk headroom. Measure
      // only after stale staging has been pruned and immediately before a write reservation.
      releaseQuotaReservation = await reserveVaultStorageQuota(
        resolved.namespace,
        staging,
        maximumChunkedVaultBytes(resolved.expectedSizeBytes),
        resolved.expectedSizeBytes,
        quotaReclaimer,
      );
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
          await downloadAndAppendAuthorizedFile(
            authorization.content_path,
            authorization.download_token,
            staging,
            cipher,
            resolved,
            recovery,
            signal,
          );
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
      releaseQuotaReservation?.();
      activeStagingUris.delete(stagingUri);
    }
  } finally {
    releaseDownloadSlot?.();
    releaseTransferStaging?.();
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

async function decryptDocumentForViewingUncoalesced(
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
          plaintext = await aesDecryptAsync(sealed, key, {
            additionalData: vaultDocumentAdditionalData(input),
          });
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

/**
 * Decrypt one immutable document revision at most once at a time. A route
 * transition can cancel its own wait without terminating a decrypt that a
 * second active viewer still needs.
 */
export async function decryptDocumentForViewing(
  input: VaultDocument,
  signal?: AbortSignal,
): Promise<File> {
  validateVaultDocument(input);
  const file = await temporaryViewDecryptions.run(
    temporaryViewOperationKey(input),
    (sharedSignal) => decryptDocumentForViewingUncoalesced(input, sharedSignal),
    signal,
  );
  const active = activeTemporaryViews.get(file.uri);
  if (active) active.leases += 1;
  else activeTemporaryViews.set(file.uri, { file, leases: 1 });
  return file;
}

export function removeTemporaryView(file: File): void {
  const viewRoot = new Directory(Paths.cache, TEMPORARY_VIEW_ROOT_NAME);
  assertManagedTemporaryViewUri(viewRoot.uri, file.uri);
  activeTemporaryViews.delete(file.uri);
  if (file.exists) file.delete();
}

export function releaseTemporaryView(file: File): void {
  const viewRoot = new Directory(Paths.cache, TEMPORARY_VIEW_ROOT_NAME);
  assertManagedTemporaryViewUri(viewRoot.uri, file.uri);
  const active = activeTemporaryViews.get(file.uri);
  if (active) {
    active.leases -= 1;
    if (active.leases > 0) return;
    activeTemporaryViews.delete(file.uri);
  }
  if (file.exists) file.delete();
}

export async function purgeTemporaryViews(): Promise<void> {
  // A terminated native transfer can leave plaintext only in this dedicated,
  // app-private cache root. Purge it before ordinary viewer residue on every
  // startup, background, logout, and account transition.
  await purgeNativeTransferStaging();
  await purgeMyPhotosTemporaryRoots();
  await temporaryViewWrites.beginPurge(TEMPORARY_VIEW_WRITE_KEY);
  let acknowledged = false;
  try {
    activeTemporaryViews.clear();
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
  await deleteMyPhotosNamespaceRoot(namespace);
  await purgeTemporaryViews();
}

export async function beginVaultNamespacePurge(namespace: string): Promise<void> {
  await vaultWrites.beginNamespacePurge(namespace);
  try {
    await myPhotosStorageWrites.beginNamespacePurge(namespace);
  } catch (error) {
    vaultWrites.finishNamespacePurge(namespace, false);
    throw error;
  }
}

export function finishVaultNamespacePurge(namespace: string, acknowledged: boolean): void {
  myPhotosStorageWrites.finishNamespacePurge(namespace, acknowledged);
  vaultWrites.finishNamespacePurge(namespace, acknowledged);
}

export async function protectManagedVaultStorageFromBackup(): Promise<void> {
  await managedVaultRoot(false);
  await managedTemporaryViewRoot(false);
  await protectNativeTransferStagingFromBackup();
  await protectManagedMyPhotosStorageFromBackup();
}

export async function deleteAllManagedVaultStorage(): Promise<void> {
  await vaultWrites.beginGlobalPurge();
  let photoFenceStarted = false;
  let acknowledged = false;
  try {
    await myPhotosStorageWrites.beginGlobalPurge();
    photoFenceStarted = true;
    if (activeVaultWrites.size || activeStagingUris.size) {
      throw new Error('Managed vault reset cannot race an uncommitted document write.');
    }
    await purgeTemporaryViews();
    const root = new Directory(Paths.document, VAULT_ROOT_NAME);
    if (root.exists) root.delete();
    await deleteAllMyPhotosRoots();
    acknowledged = true;
  } finally {
    if (photoFenceStarted) myPhotosStorageWrites.finishGlobalPurge(acknowledged);
    vaultWrites.finishGlobalPurge(acknowledged);
  }
}

export async function deleteTripVault(namespace: string, tripId: string): Promise<void> {
  assertTripIdentity(tripId);
  const finishAttempt = await vaultWrites.beginTripPurge(namespace, tripId);
  let finishPhotoAttempt: (() => void) | null = null;
  try {
    finishPhotoAttempt = await myPhotosStorageWrites.beginTripPurge(namespace, tripId);
    const root = new Directory(Paths.document, VAULT_ROOT_NAME, await namespaceHash(namespace), tripId);
    if (root.exists) root.delete();
    await deleteMyPhotosTripRoot(namespace, tripId);
  } finally {
    finishPhotoAttempt?.();
    finishAttempt();
  }
}

/** Release the process-local write fence only after SQLite removes the matching tombstone. */
export function completeTripVaultPurge(namespace: string, tripId: string): void {
  assertTripIdentity(tripId);
  myPhotosStorageWrites.completeTripPurge(namespace, tripId);
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
  maxAccountBytes: DEFAULT_VAULT_STORAGE_QUOTA_POLICY.maximumAccountBytes,
  maxAppBytes: DEFAULT_VAULT_STORAGE_QUOTA_POLICY.maximumAppBytes,
  quotaRecoveryTargetRatio: DEFAULT_VAULT_STORAGE_QUOTA_POLICY.recoveryTargetRatio,
  allowedContentTypes: [...ALLOWED_DOCUMENT_CONTENT_TYPES],
});

export type { VaultDocument } from './vault-policy';
export { validateDeclaredDocumentLength, validateVaultDocument } from './vault-policy';
export { validateNativeDocumentDownload } from './vault-native-transfer';
export type {
  VaultQuotaEvictionCandidate,
  VaultStorageQuotaReclaimer,
  VaultStorageQuotaStatus,
} from './vault-storage-quota';
