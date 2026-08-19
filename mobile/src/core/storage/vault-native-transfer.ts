import { randomUUID } from 'expo-crypto';
import { Directory, File, FileMode, Paths } from 'expo-file-system';

import {
  ApiError,
  authorizedDownloadToFile,
} from '@/core/api/client';

import {
  excludeAppPrivateUriFromBackup,
  nativePathForAppPrivateFileUri,
} from './ios-backup';
import {
  VAULT_PLAINTEXT_CHUNK_BYTES,
  encodeVaultChunkFrame,
  type VaultChunkCipher,
  type VaultChunkRecovery,
} from './vault-chunk-container';
import { vaultDocumentAdditionalData } from './vault-crypto';
import { assertDocumentOperationActive } from './vault-operation';
import {
  ALLOWED_DOCUMENT_CONTENT_TYPES,
  validateDeclaredDocumentLength,
  type VaultDocument,
} from './vault-policy';
import { TripVaultWriteCoordinator } from './vault-write-coordinator';

const TRANSFER_STAGING_ROOT_NAME = 'gc-transfer-staging-v1';
const TRANSFER_STAGING_WRITE_KEY = 'native-transfer-staging';
const transferStagingWrites = new TripVaultWriteCoordinator();

async function managedTransferStagingRoot(create: boolean): Promise<Directory> {
  const root = new Directory(Paths.cache, TRANSFER_STAGING_ROOT_NAME);
  if (!root.exists && create) root.create({ idempotent: true, intermediates: true });
  if (root.exists) await excludeAppPrivateUriFromBackup(root.uri);
  return root;
}

function headerContentType(headers: Readonly<Record<string, string>>): string {
  return (headers['content-type'] ?? '').split(';', 1)[0]?.trim().toLowerCase() ?? '';
}

export class DocumentTransferIntegrityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DocumentTransferIntegrityError';
  }
}

export function validateNativeDocumentDownload(
  response: Readonly<{
    headers: Readonly<Record<string, string>>;
    status: number;
  }>,
  expectedContentType: string,
  expectedSizeBytes: number,
  rangeStart: number,
): void {
  const contentType = headerContentType(response.headers);
  if (
    !ALLOWED_DOCUMENT_CONTENT_TYPES.has(contentType)
    || contentType !== expectedContentType.toLowerCase()
  ) {
    throw new DocumentTransferIntegrityError(
      'Downloaded document type did not match its metadata.',
    );
  }
  if (rangeStart > 0) {
    if (response.status !== 206) {
      throw new DocumentTransferIntegrityError(
        'The server did not honor the document resume request.',
      );
    }
    const expectedRange = `bytes ${rangeStart}-${expectedSizeBytes - 1}/${expectedSizeBytes}`;
    if (response.headers['content-range'] !== expectedRange) {
      throw new DocumentTransferIntegrityError(
        'The resumed document range did not match its metadata.',
      );
    }
  } else if (response.status !== 200 && response.status !== 206) {
    throw new DocumentTransferIntegrityError(
      'The document server returned an invalid download response.',
    );
  }
  try {
    validateDeclaredDocumentLength(
      response.headers['content-length'] ?? null,
      expectedSizeBytes - rangeStart,
    );
  } catch {
    throw new DocumentTransferIntegrityError(
      'The downloaded document length did not match its signed metadata.',
    );
  }
}

async function appendNativePlaintextFile(
  plaintextFile: File,
  staging: File,
  cipher: VaultChunkCipher,
  input: VaultDocument,
  recovery: VaultChunkRecovery,
  signal?: AbortSignal,
): Promise<number> {
  const remainingBytes = input.expectedSizeBytes - recovery.plaintextBytes;
  if (!plaintextFile.exists || plaintextFile.size !== remainingBytes) {
    throw new DocumentTransferIntegrityError(
      'Document transfer ended before all signed bytes were received.',
    );
  }
  const inputHandle = plaintextFile.open(FileMode.ReadOnly);
  const appendHandle = staging.open(FileMode.Append);
  let consumed = 0;
  try {
    while (consumed < remainingBytes) {
      assertDocumentOperationActive(signal);
      const plaintext = inputHandle.readBytes(
        Math.min(VAULT_PLAINTEXT_CHUNK_BYTES, remainingBytes - consumed),
      );
      if (!plaintext.byteLength) {
        throw new DocumentTransferIntegrityError(
          'Document transfer ended before all signed bytes were received.',
        );
      }
      const frame = await encodeVaultChunkFrame(
        plaintext,
        cipher,
        vaultDocumentAdditionalData(input),
        recovery.chunkCount,
        recovery.plaintextBytes,
      );
      appendHandle.writeBytes(frame);
      recovery.hasher.update(plaintext);
      recovery.plaintextBytes += plaintext.byteLength;
      recovery.chunkCount += 1;
      consumed += plaintext.byteLength;
    }
    assertDocumentOperationActive(signal);
    return consumed;
  } finally {
    inputHandle.close();
    appendHandle.close();
  }
}

export async function downloadAndAppendAuthorizedFile(
  contentPath: string,
  downloadToken: string,
  staging: File,
  cipher: VaultChunkCipher,
  input: VaultDocument,
  recovery: VaultChunkRecovery,
  signal?: AbortSignal,
): Promise<number> {
  const rangeStart = recovery.plaintextBytes;
  const remainingBytes = input.expectedSizeBytes - rangeStart;
  const transferRoot = await managedTransferStagingRoot(true);
  const plaintextFile = new File(transferRoot, `${randomUUID()}.download.tmp`);
  try {
    let response: Awaited<ReturnType<typeof authorizedDownloadToFile>>;
    try {
      response = await authorizedDownloadToFile(
        contentPath,
        downloadToken,
        nativePathForAppPrivateFileUri(plaintextFile.uri),
        remainingBytes,
        signal,
        rangeStart,
      );
    } catch (error) {
      if (error instanceof ApiError && error.code === 'PAYLOAD_TOO_LARGE') {
        throw new DocumentTransferIntegrityError(
          'Downloaded document exceeded its allowed size.',
        );
      }
      throw error;
    }
    validateNativeDocumentDownload(
      response,
      input.contentType,
      input.expectedSizeBytes,
      rangeStart,
    );
    return await appendNativePlaintextFile(
      plaintextFile,
      staging,
      cipher,
      input,
      recovery,
      signal,
    );
  } finally {
    if (plaintextFile.exists) plaintextFile.delete();
  }
}

export function beginNativeTransferStagingWrite(): () => void {
  return transferStagingWrites.beginWrite(TRANSFER_STAGING_WRITE_KEY);
}

export async function purgeNativeTransferStaging(): Promise<void> {
  await transferStagingWrites.beginPurge(TRANSFER_STAGING_WRITE_KEY);
  let acknowledged = false;
  try {
    const root = new Directory(Paths.cache, TRANSFER_STAGING_ROOT_NAME);
    if (root.exists) root.delete();
    acknowledged = true;
  } finally {
    transferStagingWrites.endPurgeAttempt(TRANSFER_STAGING_WRITE_KEY);
    if (acknowledged) transferStagingWrites.completePurge(TRANSFER_STAGING_WRITE_KEY);
  }
}

export async function protectNativeTransferStagingFromBackup(): Promise<void> {
  await managedTransferStagingRoot(false);
}
