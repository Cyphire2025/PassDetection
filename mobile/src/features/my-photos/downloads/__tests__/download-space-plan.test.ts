import {
  MY_PHOTOS_DEVICE_RESERVE_BYTES,
  projectPhotoDownloadSpace,
} from '../download-policy';

describe('My Photos remaining-byte preflight', () => {
  it('credits durable encrypted progress when interrupted Download All resumes near quota', () => {
    const mebibyte = 1024 * 1024;
    const resumed = projectPhotoDownloadSpace({
      totalPlaintextBytes: 570 * mebibyte,
      maximumItemBytes: 10 * mebibyte,
      itemCount: 57,
      retainedPlaintextBytes: 560 * mebibyte,
      completedItemCount: 56,
      availableDiskBytes: MY_PHOTOS_DEVICE_RESERVE_BYTES + 30 * mebibyte,
      accountVaultBytes: 560 * mebibyte,
      appVaultBytes: 560 * mebibyte,
    });
    expect(resumed.remainingPlaintextBytes).toBe(10 * mebibyte);
    expect(resumed.canStart).toBe(true);

    const uncredited = projectPhotoDownloadSpace({
      totalPlaintextBytes: 570 * mebibyte,
      maximumItemBytes: 10 * mebibyte,
      itemCount: 57,
      retainedPlaintextBytes: 0,
      completedItemCount: 0,
      availableDiskBytes: MY_PHOTOS_DEVICE_RESERVE_BYTES + 30 * mebibyte,
      accountVaultBytes: 560 * mebibyte,
      appVaultBytes: 560 * mebibyte,
    });
    expect(uncredited.canStart).toBe(false);
  });

  it('allows a fully completed coalesced plan without requiring fresh free space', () => {
    expect(projectPhotoDownloadSpace({
      totalPlaintextBytes: 1024,
      maximumItemBytes: 1024,
      itemCount: 1,
      retainedPlaintextBytes: 1024,
      completedItemCount: 1,
      availableDiskBytes: 0,
      accountVaultBytes: 1024,
      appVaultBytes: 1024,
    })).toMatchObject({
      remainingPlaintextBytes: 0,
      requiredDeviceBytes: 0,
      canStart: true,
    });
  });
});
