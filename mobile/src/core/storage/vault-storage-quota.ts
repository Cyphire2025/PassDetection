import { randomUUID } from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';

import { requiredVaultFreeSpace } from './vault-policy';
import {
  DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
  VaultStorageQuotaError,
  planVaultStorageQuota,
  type VaultQuotaCandidate,
  type VaultStorageQuotaPolicy,
} from './vault-quota-policy';
import { VaultQuotaReservationBook } from './vault-quota-reservations';

export type VaultQuotaEvictionCandidate = VaultQuotaCandidate & Readonly<{
  tripId: string;
  documentId: string;
  version: number;
  checksumSha256: string;
}>;

/**
 * SQLite owns registration truth, while the vault owns measured bytes and managed paths.
 * The reclaimer runs inside the serialized quota lane. Its commit must detach every selected
 * registration transactionally before removing the exact validated ciphertext.
 */
export type VaultStorageQuotaReclaimer = Readonly<{
  listCandidates: () => Promise<readonly VaultQuotaEvictionCandidate[]>;
  evict: (candidates: readonly VaultQuotaEvictionCandidate[]) => Promise<void>;
}>;

export type VaultStorageQuotaStatus = Readonly<{
  status: 'healthy' | 'at_limit' | 'over_quota';
  accountUsageBytes: number;
  appUsageBytes: number;
  accountRemainingBytes: number;
  appRemainingBytes: number;
  policy: VaultStorageQuotaPolicy;
}>;

export type VaultStorageQuotaRuntime = Readonly<{
  activeEncryptedUris: () => readonly string[];
  managedVaultRoot: (create: boolean) => Promise<Directory>;
  namespaceHash: (namespace: string) => Promise<string>;
}>;

const reservations = new VaultQuotaReservationBook();

function exclusive<T>(operation: () => Promise<T>): Promise<T> {
  return reservations.exclusive(operation);
}

function measuredDirectoryBytes(directory: Directory): number {
  if (!directory.exists) return 0;
  const size = directory.size;
  if (size === null || !Number.isSafeInteger(size) || size < 0) {
    throw new Error('Managed vault storage could not be measured safely.');
  }
  return size;
}

async function measuredUsage(
  runtime: VaultStorageQuotaRuntime,
  namespace: string,
): Promise<{ accountUsageBytes: number; appUsageBytes: number }> {
  if (!namespace) throw new Error('A vault account namespace is required.');
  const appRoot = await runtime.managedVaultRoot(false);
  const accountRoot = new Directory(appRoot, await runtime.namespaceHash(namespace));
  return {
    accountUsageBytes:
      measuredDirectoryBytes(accountRoot) + reservations.reservedGrowth(namespace),
    appUsageBytes: measuredDirectoryBytes(appRoot) + reservations.reservedGrowth(),
  };
}

/**
 * Active writes count as their remaining worst-case growth, preventing a status check from
 * temporarily under-reporting capacity while ciphertext is still being streamed.
 */
export function inspectVaultStorageQuotaWithRuntime(
  runtime: VaultStorageQuotaRuntime,
  namespace: string,
  policy: VaultStorageQuotaPolicy = DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
): Promise<VaultStorageQuotaStatus> {
  return exclusive(async () => {
    const usage = await measuredUsage(runtime, namespace);
    const plan = planVaultStorageQuota({
      namespace,
      ...usage,
      requestedAdditionalBytes: 0,
    }, [], policy);
    const atLimit = usage.accountUsageBytes >= policy.maximumAccountBytes
      || usage.appUsageBytes >= policy.maximumAppBytes;
    return {
      status: plan.status === 'blocked' ? 'over_quota' : atLimit ? 'at_limit' : 'healthy',
      ...usage,
      accountRemainingBytes: Math.max(0, policy.maximumAccountBytes - usage.accountUsageBytes),
      appRemainingBytes: Math.max(0, policy.maximumAppBytes - usage.appUsageBytes),
      policy,
    };
  });
}

export async function reserveVaultStorageQuotaWithRuntime(
  runtime: VaultStorageQuotaRuntime,
  namespace: string,
  staging: File,
  maximumEncryptedBytes: number,
  expectedPlaintextBytes: number,
  reclaimer?: VaultStorageQuotaReclaimer,
  policy: VaultStorageQuotaPolicy = DEFAULT_VAULT_STORAGE_QUOTA_POLICY,
): Promise<() => void> {
  const reservationId = await exclusive(async () => {
    const maximumAdditionalBytes = Math.max(
      0,
      maximumEncryptedBytes - (staging.exists ? staging.size : 0),
    );
    const availableDeviceBytes = Paths.availableDiskSpace;
    const requiredFreeDeviceBytes = requiredVaultFreeSpace(expectedPlaintextBytes);
    let usage = await measuredUsage(runtime, namespace);
    const candidates = reclaimer ? await reclaimer.listCandidates() : [];
    const activeUris = new Set(runtime.activeEncryptedUris());
    const protectedCandidates = candidates.map((candidate) => ({
      ...candidate,
      protectedFromEviction:
        candidate.protectedFromEviction === true || activeUris.has(candidate.encryptedUri),
    }));
    let plan = planVaultStorageQuota({
      namespace,
      ...usage,
      requestedAdditionalBytes: maximumAdditionalBytes,
      availableDeviceBytes,
      requiredFreeDeviceBytes,
    }, protectedCandidates, policy);

    if (plan.status === 'eviction_required') {
      if (!reclaimer) throw new VaultStorageQuotaError(plan.blockedScopes);
      const byUri = new Map(candidates.map((candidate) => [candidate.encryptedUri, candidate]));
      const selected = plan.evictions.map((candidate) => {
        const detail = byUri.get(candidate.encryptedUri);
        if (!detail) throw new Error('The vault eviction plan lost its registered artifact.');
        return detail;
      });
      await reclaimer.evict(selected);

      // Catalog sizes are not proof that native deletion succeeded; remeasure after the
      // crash-safe tombstone transaction before granting any new reservation.
      usage = await measuredUsage(runtime, namespace);
      plan = planVaultStorageQuota({
        namespace,
        ...usage,
        requestedAdditionalBytes: maximumAdditionalBytes,
        availableDeviceBytes: Paths.availableDiskSpace,
        requiredFreeDeviceBytes,
      }, [], policy);
    }
    if (plan.status === 'blocked') throw new VaultStorageQuotaError(plan.blockedScopes);

    const id = randomUUID();
    reservations.add(id, {
      maximumEncryptedBytes,
      namespace,
      materializedBytes: () => (staging.exists ? staging.size : 0),
    });
    return id;
  });

  let released = false;
  return () => {
    if (released) return;
    released = true;
    reservations.release(reservationId);
  };
}
