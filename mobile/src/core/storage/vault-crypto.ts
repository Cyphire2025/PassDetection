import {
  AESEncryptionKey,
  AESSealedData,
  CryptoDigestAlgorithm,
  aesDecryptAsync,
  aesEncryptAsync,
  digest,
} from 'expo-crypto';
import { File, FileMode } from 'expo-file-system';

import {
  VaultChunkContainerError,
  chunkedVaultMagic,
  isChunkedVaultPrefix,
  maximumChunkedVaultBytes,
  recoverChunkedVault,
  type VaultChunkCipher,
  type VaultChunkReader,
  type VaultChunkRecovery,
} from './vault-chunk-container';
import {
  assertDocumentOperationActive,
  documentAbortError,
} from './vault-operation';
import {
  shouldDiscardManagedCiphertextAfterFailure,
  type VaultDocument,
} from './vault-policy';

export function vaultDocumentAdditionalData(input: VaultDocument): Uint8Array {
  return new TextEncoder().encode(
    `${input.namespace}|${input.tripId}|${input.documentId}|${input.version}|${input.checksumSha256}`,
  );
}

export async function sha256(bytes: Uint8Array): Promise<string> {
  let input: ArrayBuffer;
  if (
    bytes.buffer instanceof ArrayBuffer
    && bytes.byteOffset === 0
    && bytes.byteLength === bytes.buffer.byteLength
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

export function vaultChunkCipher(key: AESEncryptionKey): VaultChunkCipher {
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

export async function recoverEncryptedChunks(
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
    vaultDocumentAdditionalData(input),
    input.expectedSizeBytes,
    (plaintext) => {
      assertDocumentOperationActive(signal);
      onPlaintext?.(plaintext);
    },
  ));
}

export async function fileUsesChunkContainer(file: File): Promise<boolean> {
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

export async function validateExistingCiphertext(
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
  const plaintext = await aesDecryptAsync(sealed, key, {
    additionalData: vaultDocumentAdditionalData(input),
  });
  assertDocumentOperationActive(signal);
  const checksum = await sha256(plaintext);
  assertDocumentOperationActive(signal);
  return plaintext.byteLength === input.expectedSizeBytes
    && checksum.toLowerCase() === input.checksumSha256.toLowerCase();
}

export async function recoverOrResetEncryptedStaging(
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
