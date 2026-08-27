import { fireEvent, render, screen } from '@testing-library/react-native';

import type {
  CompletedPhotoDownloadPage,
  PhotoDownloadJob,
} from '../../downloads/download-repository';
import { DownloadedPhotosCard } from '../downloaded-photos-card';

jest.mock('lucide-react-native/icons/chevron-left', () => () => null);
jest.mock('lucide-react-native/icons/chevron-right', () => () => null);
jest.mock('lucide-react-native/icons/image', () => () => null);
jest.mock('lucide-react-native/icons/trash-2', () => () => null);

function completedJob(): PhotoDownloadJob {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    batchId: null,
    namespace: 'tenant.account',
    tripId: '22222222-2222-4222-8222-222222222222',
    passengerId: 'passenger',
    assetId: '33333333-3333-4333-8333-333333333333',
    quality: 'original',
    wifiOnly: false,
    state: 'completed',
    deliveryVersion: 1,
    expectedSizeBytes: 1_000_000,
    expectedChecksumSha256: 'a'.repeat(64),
    contentType: 'image/jpeg',
    verifiedPlaintextBytes: 1_000_000,
    encryptedSizeBytes: 1_000_128,
    encryptedFileUri: 'file:///private/photo.enc',
    attemptCount: 1,
    preparationPollCount: 0,
    integrityVerifiedAt: '2026-08-23T10:00:00.000Z',
    nextAttemptAt: null,
    stableErrorCode: null,
    authorizationExpiresAt: null,
    supportsRanges: true,
    createdAt: '2026-08-23T09:59:00.000Z',
    updatedAt: '2026-08-23T10:00:00.000Z',
    completedAt: '2026-08-23T10:00:00.000Z',
  };
}

test('renders a bounded manifest row without a thumbnail and exposes open, remove, and paging actions', async () => {
  const job = completedJob();
  const page: CompletedPhotoDownloadPage = {
    items: [job],
    previousCursor: null,
    nextCursor: {
      completedAt: job.completedAt!,
      id: job.id,
      direction: 'older',
    },
  };
  const onOpen = jest.fn();
  const onRemove = jest.fn();
  const onNext = jest.fn();
  const { toJSON } = await render(
    <DownloadedPhotosCard
      error={false}
      loading={false}
      onNext={onNext}
      onOpen={onOpen}
      onPrevious={jest.fn()}
      onRemove={onRemove}
      onRetry={jest.fn()}
      page={page}
      removingJobId={null}
    />,
  );

  await fireEvent.press(screen.getByLabelText(/Downloaded photo 1/));
  await fireEvent.press(screen.getByLabelText('Remove this downloaded copy'));
  await fireEvent.press(screen.getByLabelText('Next downloaded photos'));
  expect(onOpen).toHaveBeenCalledWith(job);
  expect(onRemove).toHaveBeenCalledWith(job);
  expect(onNext).toHaveBeenCalledTimes(1);
  expect(JSON.stringify(toJSON())).not.toContain('Â');
});
