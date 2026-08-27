import { CryptoDigestAlgorithm, digestStringAsync } from 'expo-crypto';
import { Directory, Paths } from 'expo-file-system';

import { excludeAppPrivateUriFromBackup } from './ios-backup';
import { TripVaultWriteCoordinator, VaultWriteCoordinator } from './vault-write-coordinator';

export const MY_PHOTOS_VAULT_ROOT_NAME = 'gc-photo-vault-v1';
export const MY_PHOTOS_VIEW_ROOT_NAME = 'gc-photo-view-v1';
const LEGACY_MY_PHOTOS_TRANSFER_ROOT_NAME = 'gc-photo-transfer-v1';
export const myPhotosStorageWrites = new VaultWriteCoordinator();
const temporaryWrites = new TripVaultWriteCoordinator();
const TEMPORARY_ROOTS_KEY = 'my-photos-temporary-roots';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function myPhotosNamespaceHash(namespace: string): Promise<string> {
  if (!namespace) throw new Error('A My Photos account namespace is required.');
  return (await digestStringAsync(CryptoDigestAlgorithm.SHA256, namespace)).slice(0, 32);
}

export async function managedMyPhotosRoot(create: boolean): Promise<Directory> {
  const root = new Directory(Paths.document, MY_PHOTOS_VAULT_ROOT_NAME);
  if (!root.exists && create) root.create({ idempotent: true, intermediates: true });
  if (root.exists) await excludeAppPrivateUriFromBackup(root.uri);
  return root;
}

export async function managedMyPhotosAccountRoot(
  namespace: string,
  create: boolean,
): Promise<Directory> {
  const root = new Directory(await managedMyPhotosRoot(create), await myPhotosNamespaceHash(namespace));
  if (!root.exists && create) root.create({ idempotent: true, intermediates: true });
  return root;
}

async function legacyMyPhotosTransferRoot(): Promise<Directory> {
  // V1 builds briefly used this cache directory for native plaintext ranges.
  // It is intentionally purge-only: current transfers never create or write it.
  const root = new Directory(Paths.cache, LEGACY_MY_PHOTOS_TRANSFER_ROOT_NAME);
  if (root.exists) await excludeAppPrivateUriFromBackup(root.uri);
  return root;
}

export async function managedMyPhotosViewRoot(create: boolean): Promise<Directory> {
  const root = new Directory(Paths.cache, MY_PHOTOS_VIEW_ROOT_NAME);
  if (!root.exists && create) root.create({ idempotent: true, intermediates: true });
  if (root.exists) await excludeAppPrivateUriFromBackup(root.uri);
  return root;
}

/** Fences decrypted viewer files independently from the durable trip vault. */
export function beginMyPhotosTemporaryWrite(): () => void {
  return temporaryWrites.beginWrite(TEMPORARY_ROOTS_KEY);
}

export async function purgeMyPhotosTemporaryRoots(): Promise<void> {
  await temporaryWrites.beginPurge(TEMPORARY_ROOTS_KEY);
  let success = false;
  try {
    for (const root of [
      await legacyMyPhotosTransferRoot(),
      await managedMyPhotosViewRoot(false),
    ]) if (root.exists) root.delete();
    success = true;
  } finally {
    temporaryWrites.endPurgeAttempt(TEMPORARY_ROOTS_KEY);
    if (success) temporaryWrites.completePurge(TEMPORARY_ROOTS_KEY);
  }
}

export async function deleteMyPhotosNamespaceRoot(namespace: string): Promise<void> {
  const root = await managedMyPhotosAccountRoot(namespace, false);
  if (root.exists) root.delete();
  await purgeMyPhotosTemporaryRoots();
}

export async function deleteMyPhotosTripRoot(namespace: string, tripId: string): Promise<void> {
  if (!namespace || !UUID.test(tripId)) throw new Error('Invalid My Photos trip cleanup target.');
  const root = new Directory(await managedMyPhotosAccountRoot(namespace, false), tripId);
  if (root.exists) root.delete();
  await purgeMyPhotosTemporaryRoots();
}

export async function deleteAllMyPhotosRoots(): Promise<void> {
  await purgeMyPhotosTemporaryRoots();
  const root = await managedMyPhotosRoot(false);
  if (root.exists) root.delete();
}

export async function protectManagedMyPhotosStorageFromBackup(): Promise<void> {
  await managedMyPhotosRoot(false);
  await legacyMyPhotosTransferRoot();
  await managedMyPhotosViewRoot(false);
}
