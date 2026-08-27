import { englishMessages } from '@/core/localization/messages';

import type { PhotoDownloadState } from '../../downloads/download-policy';
import { photoDownloadStatusCopy } from '../photo-download-status-copy';

const STATES: readonly PhotoDownloadState[] = [
  'queued',
  'waiting_wifi',
  'waiting_media_preparation',
  'downloading',
  'paused',
  'retrying',
  'completed',
  'cancelled',
  'failed',
  'corrupt',
  'expired_authorization',
  'removed',
];

test.each(STATES)('renders explicit, passenger-safe copy for %s', (state) => {
  expect(photoDownloadStatusCopy(state, englishMessages, 42).trim()).not.toBe('');
});
