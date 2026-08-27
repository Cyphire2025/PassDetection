import {
  VAULT_PLAINTEXT_CHUNK_BYTES,
  maximumChunkedVaultBytes,
} from '@/core/storage/vault-chunk-container';

import type { DownloadQuality } from '../api/contracts';
import { MY_PHOTOS_MAX_ITEM_BYTES } from '../limits';

export { MY_PHOTOS_MAX_ITEM_BYTES } from '../limits';
export const MY_PHOTOS_MAX_ACCOUNT_BYTES = 8 * 1024 * 1024 * 1024;
export const MY_PHOTOS_MAX_APP_BYTES = 20 * 1024 * 1024 * 1024;
export const MY_PHOTOS_DEVICE_RESERVE_BYTES = 250 * 1024 * 1024;
export const MY_PHOTOS_DOWNLOAD_CONCURRENCY = 2;
export const MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES = 8 * 1024 * 1024;
export const MY_PHOTOS_AUTHORIZATION_BATCH_SIZE = 50;
export const MY_PHOTOS_MAX_RETRY_ATTEMPTS = 5;

export type PhotoDownloadState =
  | 'queued'
  | 'waiting_wifi'
  | 'waiting_media_preparation'
  | 'downloading'
  | 'paused'
  | 'retrying'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'corrupt'
  | 'expired_authorization'
  | 'removed';

const ALLOWED_TRANSITIONS: Readonly<Record<PhotoDownloadState, ReadonlySet<PhotoDownloadState>>> = {
  queued: new Set(['waiting_wifi', 'waiting_media_preparation', 'downloading', 'paused', 'cancelled', 'failed']),
  waiting_wifi: new Set(['queued', 'paused', 'cancelled', 'failed']),
  waiting_media_preparation: new Set(['queued', 'downloading', 'paused', 'cancelled', 'failed']),
  downloading: new Set(['waiting_media_preparation', 'retrying', 'paused', 'completed', 'cancelled', 'failed', 'corrupt', 'expired_authorization']),
  paused: new Set(['queued', 'cancelled', 'removed']),
  retrying: new Set(['downloading', 'paused', 'cancelled', 'failed', 'corrupt', 'expired_authorization']),
  completed: new Set(['corrupt', 'removed']),
  cancelled: new Set(['queued', 'removed']),
  failed: new Set(['queued', 'removed']),
  corrupt: new Set(['queued', 'removed']),
  expired_authorization: new Set(['queued', 'waiting_wifi', 'downloading', 'paused', 'cancelled', 'failed']),
  removed: new Set(['queued']),
};

export function assertPhotoDownloadTransition(
  current: PhotoDownloadState,
  next: PhotoDownloadState,
): void {
  if (current === next) return;
  if (!ALLOWED_TRANSITIONS[current].has(next)) {
    throw new Error(`Invalid My Photos download transition: ${current} -> ${next}.`);
  }
}

export function photoDownloadRetryDelayMs(
  attempt: number,
  jitterUnit = Math.random(),
): number {
  if (!Number.isSafeInteger(attempt) || attempt < 1) throw new Error('Invalid retry attempt.');
  if (!Number.isFinite(jitterUnit) || jitterUnit < 0 || jitterUnit > 1) {
    throw new Error('Invalid retry jitter.');
  }
  const base = Math.min(60_000, 1_000 * 2 ** Math.min(attempt - 1, 6));
  return Math.min(60_000, Math.round(base * (0.8 + jitterUnit * 0.4)));
}

export function photoDownloadClaimCounterIncrements(
  current: PhotoDownloadState,
  next: PhotoDownloadState,
): Readonly<{ transferAttempts: number; preparationPolls: number }> {
  return {
    transferAttempts: next === 'downloading' && current !== 'waiting_media_preparation' ? 1 : 0,
    preparationPolls: next === 'downloading' && current === 'waiting_media_preparation' ? 1 : 0,
  };
}

export function photoStorageActionIncludes(
  state: PhotoDownloadState,
  action: 'remove_completed_copies' | 'clear_trip_storage',
): boolean {
  if (state === 'removed') return false;
  return action === 'clear_trip_storage' || state === 'completed' || state === 'corrupt';
}

export function requiredPhotoDownloadSpace(expectedBytes: number): number {
  if (!Number.isSafeInteger(expectedBytes) || expectedBytes < 1 || expectedBytes > MY_PHOTOS_MAX_ITEM_BYTES) {
    throw new Error('Photo size is outside the offline policy.');
  }
  // Only authenticated ciphertext is persisted. The stream seals bounded
  // in-memory chunks immediately, so device-space preflight reserves the
  // maximum framed ciphertext plus the installation safety reserve.
  return maximumChunkedVaultBytes(expectedBytes) + MY_PHOTOS_DEVICE_RESERVE_BYTES;
}

export type PhotoDownloadSpaceProjection = Readonly<{
  remainingPlaintextBytes: number;
  encryptedGrowthBytes: number;
  concurrentPlaintextBytes: number;
  requiredDeviceBytes: number;
  canStart: boolean;
}>;

export type PhotoVaultReservationProjection = Readonly<{
  remainingGrowthBytes: number;
  requiredDeviceBytes: number;
  canReserve: boolean;
}>;

/** Exact same-directory encrypted-staging reservation. `retainedEncryptedBytes`
 * is trusted only after authenticated recovery has accepted or reset staging. */
export function projectPhotoVaultReservation(input: Readonly<{
  expectedPlaintextBytes: number;
  retainedEncryptedBytes: number;
  availableDiskBytes: number;
  accountVaultBytes: number;
  appVaultBytes: number;
  reservedAccountBytes: number;
  reservedAppBytes: number;
}>): PhotoVaultReservationProjection {
  for (const [label, value] of Object.entries(input)) {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${label} is invalid.`);
  }
  if (
    input.expectedPlaintextBytes < 1
    || input.expectedPlaintextBytes > MY_PHOTOS_MAX_ITEM_BYTES
  ) throw new Error('Photo size is outside the offline policy.');
  const maximumEncryptedBytes = maximumChunkedVaultBytes(input.expectedPlaintextBytes);
  if (input.retainedEncryptedBytes > maximumEncryptedBytes) {
    throw new Error('Retained photo ciphertext exceeds its authenticated maximum.');
  }
  const remainingGrowthBytes = maximumEncryptedBytes - input.retainedEncryptedBytes;
  const requiredDeviceBytes = input.reservedAppBytes
    + remainingGrowthBytes
    + MY_PHOTOS_DEVICE_RESERVE_BYTES;
  return {
    remainingGrowthBytes,
    requiredDeviceBytes,
    canReserve:
      input.accountVaultBytes + input.reservedAccountBytes + remainingGrowthBytes
        <= MY_PHOTOS_MAX_ACCOUNT_BYTES
      && input.appVaultBytes + input.reservedAppBytes + remainingGrowthBytes
        <= MY_PHOTOS_MAX_APP_BYTES
      && requiredDeviceBytes <= input.availableDiskBytes,
  };
}

export function projectPhotoDownloadSpace(input: Readonly<{
  totalPlaintextBytes: number;
  maximumItemBytes: number;
  itemCount: number;
  retainedPlaintextBytes: number;
  completedItemCount: number;
  availableDiskBytes: number;
  accountVaultBytes: number;
  appVaultBytes: number;
}>): PhotoDownloadSpaceProjection {
  for (const [label, value] of Object.entries(input)) {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${label} is invalid.`);
  }
  if (input.totalPlaintextBytes < 1 || input.maximumItemBytes < 1 || input.itemCount < 1) {
    throw new Error('Photo download projection is empty.');
  }
  const retained = input.completedItemCount >= input.itemCount
    ? input.totalPlaintextBytes
    : Math.min(input.totalPlaintextBytes, input.retainedPlaintextBytes);
  const remainingPlaintextBytes = input.totalPlaintextBytes - retained;
  const remainingItems = Math.max(0, input.itemCount - input.completedItemCount);
  const maximumChunks = Math.ceil(remainingPlaintextBytes / VAULT_PLAINTEXT_CHUNK_BYTES)
    + remainingItems;
  const encryptedGrowthBytes = remainingPlaintextBytes
    + maximumChunks * 36
    + remainingItems * 8;
  const concurrentPlaintextBytes = Math.min(remainingPlaintextBytes, Math.min(
    input.maximumItemBytes,
    VAULT_PLAINTEXT_CHUNK_BYTES,
  ) * MY_PHOTOS_DOWNLOAD_CONCURRENCY);
  const requiredDeviceBytes = remainingPlaintextBytes > 0
    ? encryptedGrowthBytes + MY_PHOTOS_DEVICE_RESERVE_BYTES
    : 0;
  return {
    remainingPlaintextBytes,
    encryptedGrowthBytes,
    concurrentPlaintextBytes,
    requiredDeviceBytes,
    canStart: input.maximumItemBytes <= MY_PHOTOS_MAX_ITEM_BYTES
      && (remainingPlaintextBytes === 0 || input.availableDiskBytes > 0)
      && requiredDeviceBytes <= input.availableDiskBytes
      && input.accountVaultBytes + encryptedGrowthBytes <= MY_PHOTOS_MAX_ACCOUNT_BYTES
      && input.appVaultBytes + encryptedGrowthBytes <= MY_PHOTOS_MAX_APP_BYTES,
  };
}

export type PhotoDownloadIdentity = Readonly<{
  assetId: string;
  quality: DownloadQuality;
}>;

export function coalescePhotoDownloadRequests(
  values: readonly PhotoDownloadIdentity[],
): PhotoDownloadIdentity[] {
  const result: PhotoDownloadIdentity[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const key = `${value.assetId}:${value.quality}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(value);
  }
  return result;
}
