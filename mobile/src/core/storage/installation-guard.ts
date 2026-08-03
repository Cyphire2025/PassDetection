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

let initializationInFlight: Promise<void> | null = null;

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

/** Coalesces concurrent bootstrap calls and always runs before session/database bootstrap. */
export function initializeFreshInstallGuard(): Promise<void> {
  if (initializationInFlight) return initializationInFlight;
  const operation = initializeInstallationBoundary();
  initializationInFlight = operation;
  return operation.finally(() => {
    if (initializationInFlight === operation) initializationInFlight = null;
  });
}
