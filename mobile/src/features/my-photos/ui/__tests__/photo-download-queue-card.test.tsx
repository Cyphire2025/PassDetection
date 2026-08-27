import { fireEvent, render } from '@testing-library/react-native';

import type { PhotoDownloadJob } from '../../downloads/download-repository';
import type { PhotoDownloadState } from '../../downloads/download-policy';
import { PhotoDownloadQueueCard } from '../photo-download-queue-card';

function job(id: string, state: PhotoDownloadState): PhotoDownloadJob {
  return {
    id,
    batchId: null,
    namespace: 'account-namespace',
    tripId: '11111111-1111-4111-8111-111111111111',
    passengerId: '22222222-2222-4222-8222-222222222222',
    assetId: '33333333-3333-4333-8333-333333333333',
    quality: 'optimized',
    wifiOnly: true,
    state,
    deliveryVersion: 2,
    expectedSizeBytes: 1_000,
    expectedChecksumSha256: 'a'.repeat(64),
    contentType: 'image/jpeg',
    verifiedPlaintextBytes: state === 'downloading' ? 500 : 0,
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
    updatedAt: '2026-08-23T10:00:00Z',
    completedAt: null,
  };
}

test('shows aggregate and per-item durable states without exposing local paths or asset identifiers', async () => {
  const pause = jest.fn();
  const resume = jest.fn();
  const cancel = jest.fn();
  const screen = await render(
    <PhotoDownloadQueueCard
      activeCount={2}
      completedCount={1}
      jobs={[job('downloading-job', 'downloading'), job('paused-job', 'paused')]}
      onCancel={cancel}
      onPause={pause}
      onResume={resume}
    />,
  );

  expect(screen.getByText('1 downloaded, 2 pending')).toBeTruthy();
  expect(screen.getByText('50 percent downloaded')).toBeTruthy();
  expect(screen.getByText('Paused')).toBeTruthy();
  expect(screen.queryByText('33333333-3333-4333-8333-333333333333')).toBeNull();

  await fireEvent.press(screen.getByRole('button', { name: 'Pause downloads' }));
  await fireEvent.press(screen.getByRole('button', { name: 'Resume downloads' }));
  await fireEvent.press(screen.getAllByRole('button', { name: 'Cancel download' })[0]!);

  expect(pause).toHaveBeenCalledWith('downloading-job');
  expect(resume).toHaveBeenCalledWith('paused-job');
  expect(cancel).toHaveBeenCalledWith('downloading-job');
});
