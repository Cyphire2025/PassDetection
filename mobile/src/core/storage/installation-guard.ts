import * as Crypto from 'expo-crypto';

import {
  deleteAllManagedAccountDatabases,
  protectManagedAccountDatabasesFromBackup,
} from './database';
import {
  clearSecureStateForInstallationReset,
  isTrustedInstallationBinding,
  protectInstallationMarkersFromBackup,
  readInstallationBinding,
  writeInstallationBinding,
} from './secure-store';
import {
  deleteAllManagedVaultStorage,
  protectManagedVaultStorageFromBackup,
} from './vault';

let initialization: Promise<void> | null = null;

async function initializeInstallationBoundary(): Promise<void> {
  const binding = await readInstallationBinding();
  if (isTrustedInstallationBinding(binding)) {
    // Existing encrypted artifacts may predate backup-exclusion support. Apply
    // it before any account database is opened or sensitive file is viewed.
    await protectInstallationMarkersFromBackup();
    await protectManagedAccountDatabasesFromBackup();
    await protectManagedVaultStorageFromBackup();
    return;
  }

  // A restored Documents/SQLite container is not trusted unless it is bound to
  // the THIS_DEVICE_ONLY installation UUID. Purge only GC-owned artifacts,
  // retain the old keys until those deletions succeed, then create the new
  // binding last. Any failure leaves the next bootstrap untrusted and retryable.
  await deleteAllManagedAccountDatabases();
  await deleteAllManagedVaultStorage();
  await clearSecureStateForInstallationReset();
  await writeInstallationBinding(Crypto.randomUUID());
}

/**
 * Establishes the installation boundary once per JS process, before any account
 * opens. Root-screen recovery and account changes reuse that completed boundary:
 * repeating its pre-open backup protection while a database is open would fail.
 * Newly opened account databases/vault artifacts enforce their own protection.
 * Failed attempts remain retryable and never count as a trusted initialization.
 */
export function initializeFreshInstallGuard(): Promise<void> {
  if (initialization) return initialization;
  const operation = initializeInstallationBoundary().catch((error: unknown) => {
    if (initialization === operation) initialization = null;
    throw error;
  });
  initialization = operation;
  return operation;
}
