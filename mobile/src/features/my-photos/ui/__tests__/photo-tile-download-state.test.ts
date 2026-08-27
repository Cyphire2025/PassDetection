import type { PhotoDownloadJob } from '../../downloads/download-repository';
import type { PhotoDownloadState } from '../../downloads/download-policy';
import { photoTileDownloadStates } from '../photo-tile-download-state';

function job(
  assetId: string,
  state: PhotoDownloadState,
  updatedAt: string,
  overrides: Partial<PhotoDownloadJob> = {},
): PhotoDownloadJob {
  return {
    id: `${assetId}:${state}:${updatedAt}`,
    batchId: null,
    namespace: 'private-account',
    tripId: 'trip',
    passengerId: 'passenger',
    assetId,
    quality: 'optimized',
    wifiOnly: false,
    state,
    deliveryVersion: 1,
    expectedSizeBytes: 1_000,
    expectedChecksumSha256: 'a'.repeat(64),
    contentType: 'image/jpeg',
    verifiedPlaintextBytes: state === 'downloading' ? 250 : 0,
    encryptedSizeBytes: null,
    encryptedFileUri: null,
    attemptCount: 0,
    preparationPollCount: 0,
    integrityVerifiedAt: null,
    nextAttemptAt: null,
    stableErrorCode: null,
    authorizationExpiresAt: null,
    supportsRanges: true,
    createdAt: '2026-08-23T10:00:00Z',
    updatedAt,
    completedAt: state === 'completed' ? updatedAt : null,
    ...overrides,
  };
}

test('projects private jobs into per-asset status without exposing job metadata', () => {
  const values = photoTileDownloadStates([
    job('asset-a', 'completed', '2026-08-23T10:01:00Z'),
    job('asset-a', 'downloading', '2026-08-23T10:02:00Z', { quality: 'original' }),
    job('asset-b', 'removed', '2026-08-23T10:03:00Z'),
  ], (state, progress) => `${state}:${progress}`);

  expect(values.get('asset-a')).toEqual({ downloaded: true, label: 'downloading:25' });
  expect(values.has('asset-b')).toBe(false);
  expect(JSON.stringify(values.get('asset-a'))).not.toContain('private-account');
});

test('prefers actionable failure over an older completed quality', () => {
  const values = photoTileDownloadStates([
    job('asset-a', 'completed', '2026-08-23T10:01:00Z'),
    job('asset-a', 'corrupt', '2026-08-23T10:02:00Z', { quality: 'original' }),
  ], (state) => state);

  expect(values.get('asset-a')).toEqual({ downloaded: true, label: 'corrupt' });
});
