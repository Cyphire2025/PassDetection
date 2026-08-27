import {
  AESEncryptionKey,
  randomUUID,
} from 'expo-crypto';
import { Directory, File, FileMode, Paths } from 'expo-file-system';

import { AbortableSemaphore } from '@/core/async/abortable-semaphore';
import {
  withAuthorizedDownloadStream,
  type AuthorizedDownloadStreamResponse,
} from '@/core/api/client';
import { assertSensitiveOfflineStorageAllowed } from '@/core/security/device-risk';
import { getOrCreateSecret } from '@/core/storage/secure-store';
import {
  MY_PHOTOS_VIEW_ROOT_NAME,
  beginMyPhotosTemporaryWrite,
  deleteAllMyPhotosRoots,
  deleteMyPhotosNamespaceRoot,
  deleteMyPhotosTripRoot,
  managedMyPhotosAccountRoot,
  managedMyPhotosRoot,
  managedMyPhotosViewRoot,
  myPhotosNamespaceHash,
  myPhotosStorageWrites,
  protectManagedMyPhotosStorageFromBackup,
  purgeMyPhotosTemporaryRoots,
} from '@/core/storage/my-photos-storage-lifecycle';
import {
  VaultChunkContainerError,
  maximumChunkedVaultBytes,
  type VaultChunkRecovery,
} from '@/core/storage/vault-chunk-container';
import {
  recoverEncryptedChunks,
  recoverOrResetEncryptedStaging,
  vaultChunkCipher,
  vaultDocumentAdditionalData,
} from '@/core/storage/vault-crypto';
import type { VaultDocument } from '@/core/storage/vault-policy';

import type { DownloadQuality } from '../api/contracts';
import {
  MY_PHOTOS_DEVICE_RESERVE_BYTES,
  MY_PHOTOS_DOWNLOAD_CONCURRENCY,
  MY_PHOTOS_MAX_ITEM_BYTES,
  projectPhotoVaultReservation,
} from './download-policy';
import { appendEncryptedPhotoRanges } from './photo-range-transfer';
import { encryptBoundedPhotoStream } from './photo-stream-encryption';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CHECKSUM = /^[0-9a-f]{64}$/;
const CONTENT_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const downloadSlots = new AbortableSemaphore(MY_PHOTOS_DOWNLOAD_CONCURRENCY);
const vaultWrites = myPhotosStorageWrites;
const quotaReservations = new Map<string, number>();
let quotaTail: Promise<void> = Promise.resolve();

export type PhotoVaultInput = Readonly<{
  namespace: string;
  tripId: string;
  passengerId: string;
  assetId: string;
  quality: DownloadQuality;
  deliveryVersion: number;
  checksumSha256: string;
  expectedSizeBytes: number;
  contentType: 'image/jpeg' | 'image/png' | 'image/webp';
}>;

export type PhotoDownloadGrant = PhotoVaultInput & Readonly<{
  authorizationId: string;
  resourcePath: string;
  supportsRanges: boolean;
}>;

export type EncryptedPhotoFile = Readonly<{
  uri: string;
  encryptedBytes: number;
  plaintextBytes: number;
  checksumSha256: string;
  contentType: PhotoVaultInput['contentType'];
  resumed: boolean;
}>;

export class PhotoVaultIntegrityError extends Error {
  readonly code = 'MY_PHOTOS_LOCAL_INTEGRITY_FAILED';

  constructor(message = 'The downloaded photo failed integrity verification.') {
    super(message);
    this.name = 'PhotoVaultIntegrityError';
  }
}

export class PhotoVaultStorageError extends Error {
  readonly code = 'MY_PHOTOS_STORAGE_LIMIT';

  constructor() {
    super('There is not enough private device storage for this photo.');
    this.name = 'PhotoVaultStorageError';
  }
}

function assertInput(input: PhotoVaultInput): void {
  if (!input.namespace || !UUID.test(input.tripId) || !UUID.test(input.passengerId) || !UUID.test(input.assetId)) {
    throw new Error('Invalid account-scoped photo identity.');
  }
  if (!Number.isSafeInteger(input.deliveryVersion) || input.deliveryVersion < 1) {
    throw new Error('Invalid photo delivery version.');
  }
  if (!CHECKSUM.test(input.checksumSha256) || !CONTENT_TYPES.has(input.contentType)) {
    throw new Error('Invalid photo integrity metadata.');
  }
  if (
    !Number.isSafeInteger(input.expectedSizeBytes)
    || input.expectedSizeBytes < 1
    || input.expectedSizeBytes > MY_PHOTOS_MAX_ITEM_BYTES
  ) throw new Error('Photo size is outside the private download policy.');
}

function documentInput(input: PhotoVaultInput): VaultDocument {
  return {
    namespace: input.namespace,
    tripId: input.tripId,
    // Passenger and quality are authenticated in every AES-GCM frame, preventing
    // ciphertext substitution between profiles or variants on the same account.
    documentId: `${input.passengerId}|${input.assetId}|${input.quality}`,
    version: input.deliveryVersion,
    checksumSha256: input.checksumSha256,
    expectedSizeBytes: input.expectedSizeBytes,
    contentType: input.contentType,
  };
}

async function rootDirectory(create: boolean): Promise<Directory> {
  return managedMyPhotosRoot(create);
}

async function accountDirectory(namespace: string, create: boolean): Promise<Directory> {
  return managedMyPhotosAccountRoot(namespace, create);
}

async function photoDirectory(input: PhotoVaultInput, create: boolean): Promise<Directory> {
  const root = new Directory(
    await accountDirectory(input.namespace, create),
    input.tripId,
    await myPhotosNamespaceHash(input.passengerId),
  );
  if (!root.exists && create) root.create({ idempotent: true, intermediates: true });
  return root;
}

function finalFile(root: Directory, input: PhotoVaultInput): File {
  return new File(
    root,
    `${input.assetId}.${input.quality}.${input.deliveryVersion}.${input.checksumSha256}.gcp`,
  );
}

function stagingFile(root: Directory, input: PhotoVaultInput): File {
  return new File(
    root,
    `.${input.assetId}.${input.quality}.${input.deliveryVersion}.${input.checksumSha256}.resume.tmp`,
  );
}

async function viewRoot(): Promise<Directory> {
  return managedMyPhotosViewRoot(true);
}

function measuredBytes(directory: Directory): number {
  if (!directory.exists) return 0;
  const size = directory.size;
  if (size === null || !Number.isSafeInteger(size) || size < 0) {
    throw new PhotoVaultStorageError();
  }
  return size;
}

function quotaExclusive<T>(operation: () => Promise<T>): Promise<T> {
  const run = quotaTail.then(operation, operation);
  quotaTail = run.then(() => undefined, () => undefined);
  return run;
}

async function reserveQuota(input: PhotoVaultInput, staging: File): Promise<() => void> {
  return quotaExclusive(async () => {
    const app = await rootDirectory(false);
    const account = await accountDirectory(input.namespace, false);
    const reservedApp = [...quotaReservations.values()].reduce((sum, bytes) => sum + bytes, 0);
    const reservedAccount = quotaReservations.get(input.namespace) ?? 0;
    let reservation;
    try {
      reservation = projectPhotoVaultReservation({
        expectedPlaintextBytes: input.expectedSizeBytes,
        retainedEncryptedBytes: staging.exists ? staging.size : 0,
        availableDiskBytes: Paths.availableDiskSpace,
        accountVaultBytes: measuredBytes(account),
        appVaultBytes: measuredBytes(app),
        reservedAccountBytes: reservedAccount,
        reservedAppBytes: reservedApp,
      });
    } catch {
      throw new PhotoVaultStorageError();
    }
    if (!reservation.canReserve) throw new PhotoVaultStorageError();
    const remainingGrowth = reservation.remainingGrowthBytes;
    quotaReservations.set(input.namespace, reservedAccount + remainingGrowth);
    let released = false;
    return () => {
      if (released) return;
      released = true;
      void quotaExclusive(async () => {
        const next = Math.max(0, (quotaReservations.get(input.namespace) ?? 0) - remainingGrowth);
        if (next) quotaReservations.set(input.namespace, next);
        else quotaReservations.delete(input.namespace);
      });
    };
  });
}

function assertPhotoSignature(bytes: Uint8Array, contentType: PhotoVaultInput['contentType']): void {
  const valid = contentType === 'image/jpeg'
    ? bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
    : contentType === 'image/png'
      ? bytes.length >= 8 && [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
        .every((value, index) => bytes[index] === value)
      : bytes.length >= 12
        && new TextDecoder().decode(bytes.subarray(0, 4)) === 'RIFF'
        && new TextDecoder().decode(bytes.subarray(8, 12)) === 'WEBP';
  if (!valid) throw new PhotoVaultIntegrityError('Photo bytes did not match the authorized media type.');
}

async function inspectCiphertext(
  file: File,
  key: AESEncryptionKey,
  input: PhotoVaultInput,
  signal?: AbortSignal,
): Promise<boolean> {
  if (!file.exists || file.size < 29 || file.size > maximumChunkedVaultBytes(input.expectedSizeBytes)) {
    return false;
  }
  const prefix = new Uint8Array(12);
  let prefixLength = 0;
  try {
    const recovery = await recoverEncryptedChunks(
      file,
      vaultChunkCipher(key),
      documentInput(input),
      (plaintext) => {
        const count = Math.min(prefix.length - prefixLength, plaintext.length);
        if (count > 0) prefix.set(plaintext.subarray(0, count), prefixLength);
        prefixLength += count;
      },
      signal,
    );
    if (
      recovery.plaintextBytes !== input.expectedSizeBytes
      || recovery.hasher.hexDigest().toLowerCase() !== input.checksumSha256
    ) return false;
    assertPhotoSignature(prefix.subarray(0, prefixLength), input.contentType);
    return true;
  } catch {
    if (signal?.aborted) throw signal.reason instanceof Error ? signal.reason : new Error('Photo operation cancelled.');
    return false;
  }
}

function validateGrantPath(grant: PhotoDownloadGrant): void {
  if (!UUID.test(grant.authorizationId)) throw new Error('Invalid photo authorization.');
  const expected = `/api/v1/mobile/trips/${grant.tripId}/my-photos/download-authorizations/${grant.authorizationId}/content`;
  if (grant.resourcePath !== expected) throw new Error('Photo authorization resource did not match its owner.');
}

function validateTransferResponse(
  response: Readonly<{ status: number; headers: Readonly<Record<string, string>> }>,
  input: PhotoVaultInput,
  rangeStart: number,
  rangeEndInclusive: number,
  rangeRequested: boolean,
): void {
  const contentType = (response.headers['content-type'] ?? '').split(';', 1)[0]?.trim().toLowerCase();
  if (contentType !== input.contentType) throw new PhotoVaultIntegrityError('Photo response type changed.');
  if (rangeRequested) {
    if (response.status !== 206) throw new PhotoVaultIntegrityError('Photo resume was not honored.');
    const expectedRange = `bytes ${rangeStart}-${rangeEndInclusive}/${input.expectedSizeBytes}`;
    if (response.headers['content-range'] !== expectedRange) {
      throw new PhotoVaultIntegrityError('Photo resume range was invalid.');
    }
  } else if (response.status !== 200) {
    throw new PhotoVaultIntegrityError('Photo download response was invalid.');
  }
  const declared = response.headers['content-length'];
  const expectedTransferBytes = rangeEndInclusive - rangeStart + 1;
  if (declared === undefined || !/^\d+$/.test(declared) || Number(declared) !== expectedTransferBytes) {
    throw new PhotoVaultIntegrityError('Photo response length was invalid.');
  }
}

function assertTransferActive(
  signal: AbortSignal | undefined,
  assertAuthorizationCurrent: () => void,
): void {
  if (signal?.aborted) {
    throw signal.reason instanceof Error
      ? signal.reason
      : new Error('Photo operation cancelled.');
  }
  assertAuthorizationCurrent();
}

async function appendEncryptedResponseStream(
  response: AuthorizedDownloadStreamResponse,
  encrypted: File,
  input: PhotoVaultInput,
  recovery: VaultChunkRecovery,
  key: AESEncryptionKey,
  expectedTransferBytes: number,
  expectedRangeStart: number,
  assertAuthorizationCurrent: () => void,
  signal?: AbortSignal,
): Promise<number> {
  if (recovery.plaintextBytes !== expectedRangeStart) {
    throw new PhotoVaultIntegrityError('Encrypted photo checkpoint changed during transfer.');
  }
  const reader = response.body.getReader();
  let writer: ReturnType<File['open']> | null = null;
  let streamFinished = false;
  try {
    const activeWriter = encrypted.open(FileMode.Append);
    writer = activeWriter;
    const cipher = vaultChunkCipher(key);
    const additionalData = vaultDocumentAdditionalData(documentInput(input));
    let received: number;
    try {
      received = await encryptBoundedPhotoStream({
        reader: {
          read: () => reader.read(),
          cancel: (reason) => reader.cancel(reason),
        },
        expectedBytes: expectedTransferBytes,
        cipher,
        additionalData,
        recovery,
        writeFrame: (frame) => activeWriter.writeBytes(frame),
        assertActive: () => assertTransferActive(signal, assertAuthorizationCurrent),
        ...(signal ? { signal } : {}),
      });
    } catch (error) {
      if (error instanceof VaultChunkContainerError) {
        throw new PhotoVaultIntegrityError('Photo response length did not match its authorization.');
      }
      throw error;
    }
    streamFinished = true;
    if (received !== expectedTransferBytes) {
      throw new PhotoVaultIntegrityError('Photo transfer was short.');
    }
  } finally {
    if (!streamFinished) await reader.cancel('Photo transfer did not complete.').catch(() => undefined);
    reader.releaseLock();
    writer?.close();
  }
  assertTransferActive(signal, assertAuthorizationCurrent);
  return recovery.plaintextBytes;
}

export async function assertCanonicalPhotoVaultUri(
  input: PhotoVaultInput,
  uri: string,
): Promise<void> {
  assertInput(input);
  const root = await photoDirectory(input, false);
  if (finalFile(root, input).uri !== uri) throw new Error('Photo vault path did not match its account manifest.');
}

/** Native response stream -> immediate authenticated chunk encryption ->
 * checksum/signature verification -> atomic final rename. Persistent transfer
 * state is ciphertext-only; plaintext exists only in bounded in-memory chunks. */
export async function downloadPhotoToVault(
  grant: PhotoDownloadGrant,
  signal?: AbortSignal,
  onProgress?: (verifiedPlaintextBytes: number) => void | Promise<void>,
): Promise<EncryptedPhotoFile> {
  assertInput(grant);
  validateGrantPath(grant);
  await assertSensitiveOfflineStorageAllowed();
  const releaseSlot = await downloadSlots.acquire(signal);
  const releaseWrite = vaultWrites.beginDocumentWrite(grant.namespace, grant.tripId);
  let releaseQuota: (() => void) | null = null;
  try {
    const key = await AESEncryptionKey.import(
      await getOrCreateSecret(grant.namespace, 'vault-key'),
      'hex',
    );
    const root = await photoDirectory(grant, true);
    const destination = finalFile(root, grant);
    if (destination.exists) {
      if (await inspectCiphertext(destination, key, grant, signal)) {
        return {
          uri: destination.uri,
          encryptedBytes: destination.size,
          plaintextBytes: grant.expectedSizeBytes,
          checksumSha256: grant.checksumSha256,
          contentType: grant.contentType,
          resumed: false,
        };
      }
      destination.delete();
    }
    const staging = stagingFile(root, grant);
    let recovery = await recoverOrResetEncryptedStaging(
      staging,
      vaultChunkCipher(key),
      documentInput(grant),
      signal,
    );
    if (recovery.plaintextBytes > 0 && !grant.supportsRanges) {
      staging.delete();
      recovery = await recoverOrResetEncryptedStaging(
        staging,
        vaultChunkCipher(key),
        documentInput(grant),
        signal,
      );
    }
    // Recovery authenticates retained frames (or resets corrupt staging)
    // before quota credit is calculated. This prevents corrupt-file credit and
    // requires only remaining same-directory ciphertext growth for a resume.
    releaseQuota = await reserveQuota(grant, staging);
    const resumed = recovery.plaintextBytes > 0;
    if (recovery.plaintextBytes > 0) await onProgress?.(recovery.plaintextBytes);
    await appendEncryptedPhotoRanges(
      grant.expectedSizeBytes,
      recovery.plaintextBytes,
      grant.supportsRanges,
      {
        streamAndAppendEncrypted: (range) => withAuthorizedDownloadStream(
            grant.resourcePath,
            grant.authorizationId,
            {
              maximumBytes: range.byteLength,
              rangeStart: range.start,
              rangeEndInclusive: range.endInclusive,
              requestRange: range.requested,
              ...(signal ? { signal } : {}),
            },
            async (response, assertAuthorizationCurrent) => {
              validateTransferResponse(
                response,
                grant,
                range.start,
                range.endInclusive,
                range.requested,
              );
              return appendEncryptedResponseStream(
                response,
                staging,
                grant,
                recovery,
                key,
                range.byteLength,
                range.start,
                assertAuthorizationCurrent,
                signal,
              );
            },
          ),
        ...(onProgress ? { progress: onProgress } : {}),
      },
      signal,
    );
    if (
      recovery.plaintextBytes !== grant.expectedSizeBytes
      || recovery.hasher.hexDigest().toLowerCase() !== grant.checksumSha256
      || !(await inspectCiphertext(staging, key, grant, signal))
    ) {
      if (staging.exists) staging.delete();
      throw new PhotoVaultIntegrityError();
    }
    await staging.move(destination);
    return {
      uri: destination.uri,
      encryptedBytes: destination.size,
      plaintextBytes: grant.expectedSizeBytes,
      checksumSha256: grant.checksumSha256,
      contentType: grant.contentType,
      resumed,
    };
  } finally {
    releaseQuota?.();
    releaseWrite();
    releaseSlot();
  }
}

export async function discardPhotoVaultStaging(input: PhotoVaultInput): Promise<void> {
  assertInput(input);
  const releaseWrite = vaultWrites.beginDocumentWrite(input.namespace, input.tripId);
  try {
    const root = await photoDirectory(input, false);
    const staging = stagingFile(root, input);
    if (staging.exists) staging.delete();
  } finally {
    releaseWrite();
  }
}

export function availablePhotoVaultDiskBytes(): number {
  const available = Paths.availableDiskSpace;
  return Number.isSafeInteger(available) && available >= 0 ? available : 0;
}

export async function photoVaultStorageUsage(namespace: string): Promise<Readonly<{
  accountBytes: number;
  appBytes: number;
}>> {
  return {
    accountBytes: measuredBytes(await accountDirectory(namespace, false)),
    appBytes: measuredBytes(await rootDirectory(false)),
  };
}

export async function inspectPhotoVaultFile(
  input: PhotoVaultInput & Readonly<{ encryptedUri: string }>,
  signal?: AbortSignal,
): Promise<'valid' | 'missing' | 'corrupt'> {
  await assertCanonicalPhotoVaultUri(input, input.encryptedUri);
  const file = new File(input.encryptedUri);
  if (!file.exists) return 'missing';
  const key = await AESEncryptionKey.import(await getOrCreateSecret(input.namespace, 'vault-key'), 'hex');
  return (await inspectCiphertext(file, key, input, signal)) ? 'valid' : 'corrupt';
}

/** Bounded startup check: validates canonical ownership plus native file
 * existence/size without decrypting or reading the ciphertext body. Full
 * authenticated inspection is reserved for dirty or explicitly requested
 * rows by the incremental reconciler. */
export async function inspectPhotoVaultFileMetadata(
  input: PhotoVaultInput & Readonly<{
    encryptedUri: string;
    expectedEncryptedBytes: number;
  }>,
): Promise<'present' | 'missing' | 'size_mismatch'> {
  await assertCanonicalPhotoVaultUri(input, input.encryptedUri);
  const file = new File(input.encryptedUri);
  if (!file.exists) return 'missing';
  return file.size === input.expectedEncryptedBytes ? 'present' : 'size_mismatch';
}

function viewExtension(contentType: PhotoVaultInput['contentType']): string {
  return contentType === 'image/jpeg' ? 'jpg' : contentType === 'image/png' ? 'png' : 'webp';
}

export async function decryptPhotoForViewing(
  input: PhotoVaultInput & Readonly<{ encryptedUri: string }>,
  signal?: AbortSignal,
): Promise<File> {
  await assertSensitiveOfflineStorageAllowed();
  await assertCanonicalPhotoVaultUri(input, input.encryptedUri);
  const releaseTemporaryWrite = beginMyPhotosTemporaryWrite();
  try {
  const available = Paths.availableDiskSpace;
  if (
    !Number.isSafeInteger(available)
    || available < 0
    || available < input.expectedSizeBytes + MY_PHOTOS_DEVICE_RESERVE_BYTES
  ) {
    throw new PhotoVaultStorageError();
  }
  const encrypted = new File(input.encryptedUri);
  if (!encrypted.exists) throw new PhotoVaultIntegrityError('The private photo copy is missing.');
  const key = await AESEncryptionKey.import(await getOrCreateSecret(input.namespace, 'vault-key'), 'hex');
  const temporary = new File(await viewRoot(), `${randomUUID()}.${viewExtension(input.contentType)}`);
  temporary.create({ overwrite: false, intermediates: true });
  try {
    const writer = temporary.open(FileMode.WriteOnly);
    let recovery: VaultChunkRecovery;
    try {
      recovery = await recoverEncryptedChunks(
        encrypted,
        vaultChunkCipher(key),
        documentInput(input),
        (bytes) => writer.writeBytes(bytes),
        signal,
      );
    } finally {
      writer.close();
    }
    if (
      recovery.plaintextBytes !== input.expectedSizeBytes
      || recovery.hasher.hexDigest().toLowerCase() !== input.checksumSha256
      || temporary.size !== input.expectedSizeBytes
    ) throw new PhotoVaultIntegrityError();
    const reader = temporary.open(FileMode.ReadOnly);
    try {
      assertPhotoSignature(reader.readBytes(12), input.contentType);
    } finally {
      reader.close();
    }
    return temporary;
  } catch (error) {
    if (temporary.exists) temporary.delete();
    throw error;
  }
  } finally {
    releaseTemporaryWrite();
  }
}

export function releasePhotoView(file: File): void {
  const root = new Directory(Paths.cache, MY_PHOTOS_VIEW_ROOT_NAME);
  if (!file.uri.startsWith(`${root.uri.replace(/\/+$/, '')}/`) || file.uri.slice(root.uri.length + 1).includes('/')) {
    throw new Error('Refusing to remove an unmanaged photo view.');
  }
  if (file.exists) file.delete();
}

export async function removePhotoVaultFile(
  input: PhotoVaultInput & Readonly<{ encryptedUri: string }>,
): Promise<void> {
  await assertCanonicalPhotoVaultUri(input, input.encryptedUri);
  const release = vaultWrites.beginDocumentWrite(input.namespace, input.tripId);
  try {
    const file = new File(input.encryptedUri);
    if (file.exists) file.delete();
  } finally {
    release();
  }
}

export async function purgePhotoTemporaryFiles(): Promise<void> {
  await purgeMyPhotosTemporaryRoots();
}

export async function deletePhotoTripStorage(namespace: string, tripId: string): Promise<void> {
  if (!namespace || !UUID.test(tripId)) throw new Error('Invalid photo trip cleanup target.');
  const release = await vaultWrites.beginTripPurge(namespace, tripId);
  let success = false;
  try {
    await deleteMyPhotosTripRoot(namespace, tripId);
    success = true;
  } finally {
    release();
    if (success) vaultWrites.completeTripPurge(namespace, tripId);
  }
  await purgePhotoTemporaryFiles();
}

export async function deletePhotoNamespaceStorage(namespace: string): Promise<void> {
  if (!namespace) throw new Error('Invalid photo account cleanup target.');
  await vaultWrites.beginNamespacePurge(namespace);
  let success = false;
  try {
    await deleteMyPhotosNamespaceRoot(namespace);
    success = true;
  } finally {
    vaultWrites.finishNamespacePurge(namespace, success);
  }
  await purgePhotoTemporaryFiles();
}

export async function deleteAllPhotoStorage(): Promise<void> {
  await vaultWrites.beginGlobalPurge();
  let success = false;
  try {
    await deleteAllMyPhotosRoots();
    success = true;
  } finally {
    vaultWrites.finishGlobalPurge(success);
  }
  await purgePhotoTemporaryFiles();
}

export async function protectPhotoStorageFromBackup(): Promise<void> {
  await protectManagedMyPhotosStorageFromBackup();
}
