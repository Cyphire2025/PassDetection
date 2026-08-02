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
import { Directory, File, Paths } from 'expo-file-system';

import { apiRequest, authorizedDownloadResponse } from '@/core/api/client';
import { DocumentDownloadAuthorizationSchema } from '@/core/api/contracts';
import { assertSensitiveOfflineStorageAllowed } from '@/core/security/device-risk';

import { getOrCreateSecret } from './secure-store';
import {
  ALLOWED_DOCUMENT_CONTENT_TYPES,
  MAX_CONCURRENT_DOWNLOADS,
  MAX_DOCUMENT_BYTES,
  assertVaultFreeSpace,
  validateDeclaredDocumentLength,
  validateVaultDocument,
  type VaultDocument,
} from './vault-policy';

let activeDownloads = 0;
const downloadWaiters: (() => void)[] = [];

export type EncryptedOfflineFile = {
  uri: string;
  encryptedSizeBytes: number;
  checksumSha256: string;
};

async function namespaceHash(namespace: string): Promise<string> {
  return (
    await digestStringAsync(CryptoDigestAlgorithm.SHA256, namespace)
  ).slice(0, 32);
}

async function namespaceDirectory(namespace: string): Promise<Directory> {
  const root = new Directory(Paths.document, 'gc-vault-v1', await namespaceHash(namespace));
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

function offlineFile(root: Directory, documentId: string, version: number): File {
  return new File(root, `${documentId}.${version}.gcv`);
}

async function sha256(bytes: Uint8Array): Promise<string> {
  const copied = new Uint8Array(bytes.byteLength);
  copied.set(bytes);
  const hashed = new Uint8Array(await digest(CryptoDigestAlgorithm.SHA256, copied.buffer));
  return Array.from(hashed, (value) => value.toString(16).padStart(2, '0')).join('');
}

async function acquireDownloadSlot(): Promise<() => void> {
  if (activeDownloads >= MAX_CONCURRENT_DOWNLOADS) {
    await new Promise<void>((resolve) => downloadWaiters.push(resolve));
  }
  activeDownloads += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    activeDownloads -= 1;
    downloadWaiters.shift()?.();
  };
}

function responseContentType(response: Response): string {
  return (response.headers.get('content-type') ?? '').split(';', 1)[0]?.trim().toLowerCase() ?? '';
}

function removeObsoleteVersions(root: Directory, input: VaultDocument): void {
  const keep = `${input.documentId}.${input.version}.gcv`;
  for (const entry of root.list()) {
    if (entry instanceof File && entry.name.startsWith(`${input.documentId}.`) && entry.name !== keep) {
      entry.delete();
    }
  }
}

function assertAuthorizedContentPath(path: string, input: VaultDocument): void {
  const parsed = new URL(path, 'https://mobile.invalid');
  const expectedSuffix = `/mobile/trips/${input.tripId}/documents/${input.documentId}/content`;
  if (!parsed.pathname.endsWith(expectedSuffix)) {
    throw new Error('The document authorization did not match the requested document.');
  }
  const parameters = [...parsed.searchParams.keys()];
  if (
    parameters.length !== 1 ||
    parameters[0] !== 'version' ||
    parsed.searchParams.get('version') !== String(input.version)
  ) {
    throw new Error('The document authorization did not match the requested version.');
  }
}

export async function downloadAndEncryptDocument(
  input: VaultDocument,
  signal?: AbortSignal,
): Promise<EncryptedOfflineFile> {
  validateVaultDocument(input);
  await assertSensitiveOfflineStorageAllowed();
  assertVaultFreeSpace(Paths.availableDiskSpace, input.expectedSizeBytes);
  const release = await acquireDownloadSlot();
  try {
    const authorization = await apiRequest(
      `/mobile/trips/${input.tripId}/documents/${input.documentId}/authorize?version=${input.version}`,
      {
        method: 'POST',
        body: {},
        schema: DocumentDownloadAuthorizationSchema,
      },
    );
    if (
      authorization.document_id !== input.documentId ||
      authorization.version !== input.version ||
      Date.parse(authorization.expires_at) <= Date.now()
    ) {
      throw new Error('The document download authorization was invalid or expired.');
    }
    assertAuthorizedContentPath(authorization.content_path, input);
    const response = await authorizedDownloadResponse(
      authorization.content_path,
      authorization.download_token,
      signal,
    );
    const contentType = responseContentType(response);
    if (!ALLOWED_DOCUMENT_CONTENT_TYPES.has(contentType) || contentType !== input.contentType.toLowerCase()) {
      throw new Error('Downloaded document type did not match its metadata.');
    }

    const declaredLength = response.headers.get('content-length');
    validateDeclaredDocumentLength(declaredLength, input.expectedSizeBytes);

    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength !== input.expectedSizeBytes || bytes.byteLength > MAX_DOCUMENT_BYTES) {
      throw new Error('Downloaded document size did not match its metadata.');
    }
    const checksum = await sha256(bytes);
    if (checksum.toLowerCase() !== input.checksumSha256.toLowerCase()) {
      throw new Error('Downloaded document checksum did not match its metadata.');
    }

    const encodedKey = await getOrCreateSecret(input.namespace, 'vault-key');
    const key = await AESEncryptionKey.import(encodedKey, 'hex');
    const sealed = await aesEncryptAsync(bytes, key, { additionalData: aad(input) });
    const ciphertext = await sealed.combined('bytes');

    const root = await vaultDirectory(input.namespace, input.tripId);
    const destination = offlineFile(root, input.documentId, input.version);
    if (destination.exists) {
      try {
        if (destination.size < 29 || destination.size > input.expectedSizeBytes + 64) {
          throw new Error('Existing ciphertext had an invalid size.');
        }
        const existingSealed = AESSealedData.fromCombined(await destination.bytes());
        const existingPlaintext = await aesDecryptAsync(existingSealed, key, { additionalData: aad(input) });
        if ((await sha256(existingPlaintext)).toLowerCase() !== checksum.toLowerCase()) {
          throw new Error('Existing ciphertext failed integrity verification.');
        }
        return {
          uri: destination.uri,
          encryptedSizeBytes: destination.size,
          checksumSha256: checksum,
        };
      } catch {
        destination.delete();
      }
    }

    const temporary = new File(root, `.${input.documentId}.${input.version}.${randomUUID()}.tmp`);
    try {
      temporary.create({ overwrite: false, intermediates: true });
      temporary.write(ciphertext);
      await temporary.move(destination);
      removeObsoleteVersions(root, input);
    } finally {
      if (temporary.exists) temporary.delete();
    }

    return {
      uri: destination.uri,
      encryptedSizeBytes: destination.size,
      checksumSha256: checksum,
    };
  } finally {
    release();
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

export async function decryptDocumentForViewing(input: VaultDocument): Promise<File> {
  validateVaultDocument(input);
  await assertSensitiveOfflineStorageAllowed();
  assertVaultFreeSpace(Paths.availableDiskSpace, input.expectedSizeBytes);
  const root = await vaultDirectory(input.namespace, input.tripId);
  const encrypted = offlineFile(root, input.documentId, input.version);
  if (!encrypted.exists || encrypted.size < 29) throw new Error('The offline document is unavailable.');

  const encodedKey = await getOrCreateSecret(input.namespace, 'vault-key');
  const key = await AESEncryptionKey.import(encodedKey, 'hex');
  const sealed = AESSealedData.fromCombined(await encrypted.bytes());
  const plaintext = await aesDecryptAsync(sealed, key, { additionalData: aad(input) });

  const checksum = await sha256(plaintext);
  if (checksum.toLowerCase() !== input.checksumSha256.toLowerCase()) {
    throw new Error('The offline document failed integrity verification.');
  }

  const viewRoot = new Directory(Paths.cache, 'gc-secure-view-v1');
  if (!viewRoot.exists) viewRoot.create({ idempotent: true, intermediates: true });
  const temporary = new File(viewRoot, `${randomUUID()}.${viewerExtension(input.contentType)}`);
  temporary.create({ overwrite: false, intermediates: true });
  temporary.write(plaintext);
  return temporary;
}

export function removeTemporaryView(file: File): void {
  const viewRoot = new Directory(Paths.cache, 'gc-secure-view-v1');
  if (!file.uri.startsWith(`${viewRoot.uri}/`)) throw new Error('Refusing to remove an untrusted path.');
  if (file.exists) file.delete();
}

export function purgeTemporaryViews(): void {
  const root = new Directory(Paths.cache, 'gc-secure-view-v1');
  if (root.exists) root.delete();
}

export async function deleteVaultNamespace(namespace: string): Promise<void> {
  const root = new Directory(Paths.document, 'gc-vault-v1', await namespaceHash(namespace));
  if (root.exists) root.delete();
  purgeTemporaryViews();
}

export async function deleteTripVault(namespace: string, tripId: string): Promise<void> {
  if (!/^[0-9a-f-]{36}$/i.test(tripId)) throw new Error('Invalid trip identity.');
  const root = new Directory(Paths.document, 'gc-vault-v1', await namespaceHash(namespace), tripId);
  if (root.exists) root.delete();
}

export async function deleteOfflineDocument(
  namespace: string,
  tripId: string,
  documentId: string,
): Promise<void> {
  if (!/^[0-9a-f-]{36}$/i.test(documentId)) throw new Error('Invalid document identity.');
  const root = new Directory(Paths.document, 'gc-vault-v1', await namespaceHash(namespace), tripId);
  if (!root.exists) return;
  for (const entry of root.list()) {
    if (entry instanceof File && entry.name.startsWith(`${documentId}.`)) entry.delete();
  }
}

export async function removeAllOfflineDocuments(namespace: string): Promise<void> {
  await deleteVaultNamespace(namespace);
}

export async function vaultUsageBytes(namespace: string): Promise<number> {
  const root = new Directory(Paths.document, 'gc-vault-v1', await namespaceHash(namespace));
  return root.exists ? (root.size ?? 0) : 0;
}

export const documentVaultPolicy = Object.freeze({
  maxDocumentBytes: MAX_DOCUMENT_BYTES,
  maxConcurrentDownloads: MAX_CONCURRENT_DOWNLOADS,
  allowedContentTypes: [...ALLOWED_DOCUMENT_CONTENT_TYPES],
});

export type { VaultDocument } from './vault-policy';
export { validateDeclaredDocumentLength, validateVaultDocument } from './vault-policy';
