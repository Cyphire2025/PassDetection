import type { CompatibleMessageCatalog } from '@/core/localization/messages';

import type { PhotoDownloadState } from '../downloads/download-policy';

export function photoDownloadStatusCopy(
  state: PhotoDownloadState,
  messages: CompatibleMessageCatalog,
  progressPercent = 0,
): string {
  switch (state) {
    case 'queued':
      return messages.myPhotosDownloadQueued();
    case 'waiting_wifi':
      return messages.myPhotosWaitingWifi();
    case 'waiting_media_preparation':
      return messages.myPhotosPreparingPhoto();
    case 'downloading':
      return messages.myPhotosDownloadProgress(progressPercent);
    case 'paused':
      return messages.myPhotosDownloadPaused();
    case 'retrying':
      return messages.myPhotosDownloadRetrying();
    case 'completed':
      return messages.myPhotosDownloadCompleted();
    case 'cancelled':
      return messages.myPhotosDownloadCancelled();
    case 'failed':
      return messages.myPhotosDownloadFailed();
    case 'corrupt':
      return messages.myPhotosDownloadCorrupt();
    case 'expired_authorization':
      return messages.myPhotosDownloadExpired();
    case 'removed':
      return messages.myPhotosDownloadRemoved();
  }
}
