import { maximumChunkedVaultBytes } from '@/core/storage/vault-chunk-container';

import {
  MY_PHOTOS_DEVICE_RESERVE_BYTES,
  assertPhotoDownloadTransition,
  coalescePhotoDownloadRequests,
  photoDownloadClaimCounterIncrements,
  photoDownloadRetryDelayMs,
  photoStorageActionIncludes,
  projectPhotoVaultReservation,
  requiredPhotoDownloadSpace,
} from '../download-policy';

describe('My Photos download policy', () => {
  it('coalesces duplicate one/selected/download-all requests', () => {
    const assetId = 'a7d33c38-f09c-46c3-a026-a810a907640c';
    expect(coalescePhotoDownloadRequests([
      { assetId, quality: 'original' },
      { assetId, quality: 'original' },
      { assetId, quality: 'optimized' },
    ])).toHaveLength(2);
  });

  it('enforces explicit queue transitions', () => {
    expect(() => assertPhotoDownloadTransition('downloading', 'completed')).not.toThrow();
    expect(() => assertPhotoDownloadTransition('queued', 'completed')).toThrow('Invalid');
    expect(() => assertPhotoDownloadTransition('completed', 'downloading')).toThrow('Invalid');
  });

  it('uses bounded exponential retry with deterministic jitter in tests', () => {
    expect(photoDownloadRetryDelayMs(1, 0)).toBe(800);
    expect(photoDownloadRetryDelayMs(10, 1)).toBe(60_000);
  });

  it('reserves framed ciphertext and device headroom without a plaintext disk copy', () => {
    const expected = 10 * 1024 * 1024;
    expect(requiredPhotoDownloadSpace(expected)).toBe(
      maximumChunkedVaultBytes(expected) + MY_PHOTOS_DEVICE_RESERVE_BYTES,
    );
  });

  it('credits only authenticated retained ciphertext for a near-complete resume', () => {
    const expected = 10 * 1024 * 1024;
    const maximum = maximumChunkedVaultBytes(expected);
    const projection = projectPhotoVaultReservation({
      expectedPlaintextBytes: expected,
      retainedEncryptedBytes: maximum - 1_024,
      availableDiskBytes: MY_PHOTOS_DEVICE_RESERVE_BYTES + 1_024,
      accountVaultBytes: maximum - 1_024,
      appVaultBytes: maximum - 1_024,
      reservedAccountBytes: 0,
      reservedAppBytes: 0,
    });
    expect(projection).toMatchObject({
      remainingGrowthBytes: 1_024,
      requiredDeviceBytes: MY_PHOTOS_DEVICE_RESERVE_BYTES + 1_024,
      canReserve: true,
    });
  });

  it('includes other in-flight app reservations in the device-space fence', () => {
    const expected = 1024;
    const maximum = maximumChunkedVaultBytes(expected);
    const input = {
      expectedPlaintextBytes: expected,
      retainedEncryptedBytes: maximum - 512,
      accountVaultBytes: 0,
      appVaultBytes: 0,
      reservedAccountBytes: 0,
      reservedAppBytes: 2_048,
    };
    expect(projectPhotoVaultReservation({
      ...input,
      availableDiskBytes: MY_PHOTOS_DEVICE_RESERVE_BYTES + 512 + 2_047,
    }).canReserve).toBe(false);
    expect(projectPhotoVaultReservation({
      ...input,
      availableDiskBytes: MY_PHOTOS_DEVICE_RESERVE_BYTES + 512 + 2_048,
    }).canReserve).toBe(true);
  });

  it('keeps long media preparation polls separate from bounded transfer attempts', () => {
    let transferAttempts = 1;
    let preparationPolls = 0;
    for (let index = 0; index < 50; index += 1) {
      const increment = photoDownloadClaimCounterIncrements(
        'waiting_media_preparation',
        'downloading',
      );
      transferAttempts += increment.transferAttempts;
      preparationPolls += increment.preparationPolls;
    }
    const retryIncrement = photoDownloadClaimCounterIncrements('retrying', 'downloading');
    transferAttempts += retryIncrement.transferAttempts;

    expect({ transferAttempts, preparationPolls }).toEqual({
      transferAttempts: 2,
      preparationPolls: 50,
    });
  });

  it('keeps completed-copy removal distinct from destructive trip storage clearing', () => {
    expect(photoStorageActionIncludes('queued', 'remove_completed_copies')).toBe(false);
    expect(photoStorageActionIncludes('paused', 'remove_completed_copies')).toBe(false);
    expect(photoStorageActionIncludes('completed', 'remove_completed_copies')).toBe(true);
    expect(photoStorageActionIncludes('corrupt', 'remove_completed_copies')).toBe(true);

    expect(photoStorageActionIncludes('queued', 'clear_trip_storage')).toBe(true);
    expect(photoStorageActionIncludes('waiting_media_preparation', 'clear_trip_storage')).toBe(true);
    expect(photoStorageActionIncludes('paused', 'clear_trip_storage')).toBe(true);
    expect(photoStorageActionIncludes('completed', 'clear_trip_storage')).toBe(true);
    expect(photoStorageActionIncludes('removed', 'clear_trip_storage')).toBe(false);
  });
});
