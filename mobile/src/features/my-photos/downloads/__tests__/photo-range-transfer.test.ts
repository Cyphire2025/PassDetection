import { MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES } from '../download-policy';
import {
  appendEncryptedPhotoRanges,
  type PhotoByteRange,
} from '../photo-range-transfer';

type FileSystem = Readonly<{
  readFileSync: (path: string, encoding: 'utf8') => string;
}>;
type PathModule = Readonly<{
  join: (...parts: string[]) => string;
}>;
const fileSystem = jest.requireActual<FileSystem>('fs');
const pathModule = jest.requireActual<PathModule>('path');
const processModule = jest.requireActual<{ cwd: () => string }>('process');

describe('My Photos bounded range transfer', () => {
  it('resumes from the exact encrypted checkpoint after an interrupted native range', async () => {
    const total = MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES * 2 + 37;
    let encryptedCheckpoint = 0;
    const firstRanges: PhotoByteRange[] = [];
    let downloads = 0;

    await expect(appendEncryptedPhotoRanges(total, encryptedCheckpoint, true, {
      streamAndAppendEncrypted: (range) => {
        firstRanges.push(range);
        downloads += 1;
        if (downloads === 3) throw new TypeError('network interrupted');
        encryptedCheckpoint = range.endInclusive + 1;
        return encryptedCheckpoint;
      },
    })).rejects.toThrow('network interrupted');

    expect(encryptedCheckpoint).toBe(MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES * 2);
    expect(firstRanges.map((range) => [range.start, range.endInclusive])).toEqual([
      [0, MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES - 1],
      [MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES, MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES * 2 - 1],
      [MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES * 2, total - 1],
    ]);

    const resumedRanges: PhotoByteRange[] = [];
    await expect(appendEncryptedPhotoRanges(total, encryptedCheckpoint, true, {
      streamAndAppendEncrypted: (range) => {
        resumedRanges.push(range);
        encryptedCheckpoint = range.endInclusive + 1;
        return encryptedCheckpoint;
      },
    })).resolves.toBe(total);

    expect(resumedRanges).toEqual([{
      start: MY_PHOTOS_NATIVE_RANGE_CHUNK_BYTES * 2,
      endInclusive: total - 1,
      byteLength: 37,
      requested: true,
    }]);
  });

  it('uses one exact full transfer when the authorized provider does not support ranges', async () => {
    const ranges: PhotoByteRange[] = [];
    await expect(appendEncryptedPhotoRanges(4096, 0, false, {
      streamAndAppendEncrypted: (range) => {
        ranges.push(range);
        return range.endInclusive + 1;
      },
    })).resolves.toBe(4096);
    expect(ranges).toEqual([{ start: 0, endInclusive: 4095, byteLength: 4096, requested: false }]);
    await expect(appendEncryptedPhotoRanges(4096, 1, false, {
      streamAndAppendEncrypted: () => 4096,
    })).rejects.toThrow('cannot resume');
  });

  it('keeps the My Photos persistent transfer path ciphertext-only', () => {
    const source = fileSystem.readFileSync(pathModule.join(
      processModule.cwd(),
      'src/features/my-photos/downloads/photo-vault.ts',
    ), 'utf8');
    expect(source).toContain('withAuthorizedDownloadStream');
    expect(source).toContain('appendEncryptedPhotoRanges');
    expect(source).not.toContain('authorizedDownloadToFile');
    expect(source).not.toContain('nativePathForAppPrivateFileUri');
    expect(source).not.toContain('managedMyPhotosTransferRoot');
    expect(source).not.toContain('.download.tmp');
    expect(source).not.toContain('createPlaintextTarget');
    const downloadBody = source.slice(source.indexOf('export async function downloadPhotoToVault'));
    expect(downloadBody.indexOf('recoverOrResetEncryptedStaging(')).toBeGreaterThanOrEqual(0);
    expect(downloadBody.indexOf('reserveQuota(grant, staging)')).toBeGreaterThan(
      downloadBody.indexOf('recoverOrResetEncryptedStaging('),
    );
  });
});
