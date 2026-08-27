import type { CompatibleMessageCatalog } from '@/core/localization/messages';

import type { MyPhotosSummary } from '../api/contracts';

export type MyPhotosStateAction = 'none' | 'refresh' | 'open_face_scan';

export type MyPhotosStatePresentation = Readonly<{
  tone: 'neutral' | 'progress' | 'warning' | 'danger' | 'success';
  title: string;
  message: string;
  action: MyPhotosStateAction;
  busy: boolean;
}>;

export function myPhotosStatePresentation(
  summary: MyPhotosSummary,
  messages: CompatibleMessageCatalog,
  cache: Readonly<{ source: 'network' | 'offline'; partial: boolean }> = {
    source: 'network', partial: false,
  },
): MyPhotosStatePresentation {
  if (
    cache.source === 'offline'
    && summary.results.match_count > 0
    && !['feature_unavailable', 'access_expired', 'access_revoked', 'nonrecoverable_error'].includes(summary.experience_state)
  ) {
    return cache.partial
      ? { tone: 'warning', title: messages.myPhotosPhotosFound(summary.results.match_count), message: messages.myPhotosPartiallyOffline(), action: 'refresh', busy: false }
      : { tone: 'warning', title: messages.myPhotosPhotosFound(summary.results.match_count), message: messages.myPhotosOffline(), action: 'refresh', busy: false };
  }
  const state = summary.experience_state;
  switch (state) {
    case 'feature_unavailable':
      return { tone: 'neutral', title: messages.myPhotosFeatureUnavailable(), message: messages.myPhotosTripShortcut(), action: 'none', busy: false };
    case 'provider_not_configured':
      return { tone: 'warning', title: messages.myPhotosProviderUnavailable(), message: messages.myPhotosProviderNotConfiguredMessage(), action: 'none', busy: false };
    case 'gallery_not_uploaded':
      return { tone: 'neutral', title: messages.myPhotosNoGallery(), message: messages.myPhotosTripShortcut(), action: 'refresh', busy: false };
    case 'gallery_processing':
      return { tone: 'progress', title: messages.myPhotosGalleryPending(), message: messages.myPhotosTripShortcut(), action: 'refresh', busy: true };
    case 'gallery_indexing':
      return { tone: 'progress', title: messages.myPhotosGalleryIndexing(), message: messages.myPhotosTripShortcut(), action: 'refresh', busy: true };
    case 'consent_required':
      return { tone: 'neutral', title: messages.myPhotosSetUpFaceScan(), message: messages.myPhotosConsentRequired(), action: 'open_face_scan', busy: false };
    case 'camera_permission_required':
    case 'ready_to_scan':
      return { tone: 'neutral', title: messages.myPhotosVerifyFace(), message: messages.myPhotosReadyMessage(), action: 'open_face_scan', busy: false };
    case 'scan_running':
      return { tone: 'progress', title: messages.myPhotosScanRunning(), message: messages.myPhotosScanGuidance(), action: 'open_face_scan', busy: true };
    case 'scan_cancelled':
      return { tone: 'warning', title: messages.myPhotosScanCancelled(), message: messages.myPhotosRetryNewSession(), action: 'open_face_scan', busy: false };
    case 'session_expired':
      return { tone: 'warning', title: messages.myPhotosSessionExpired(), message: messages.myPhotosRetryNewSession(), action: 'open_face_scan', busy: false };
    case 'liveness_rejected':
      return { tone: 'warning', title: messages.myPhotosLivenessRejected(), message: messages.myPhotosAccuracyNotice(), action: 'open_face_scan', busy: false };
    case 'cooldown':
      return { tone: 'warning', title: messages.myPhotosCooldown(), message: messages.myPhotosRetryNewSession(), action: 'none', busy: false };
    case 'device_unsupported':
      return { tone: 'danger', title: messages.myPhotosDeviceUnsupported(), message: messages.myPhotosProviderUnavailable(), action: 'none', busy: false };
    case 'provider_unavailable':
      return { tone: 'warning', title: messages.myPhotosProviderTemporary(), message: messages.myPhotosProviderUnavailable(), action: 'refresh', busy: false };
    case 'search_queued':
      return { tone: 'progress', title: messages.myPhotosSearchQueued(), message: messages.myPhotosSearching(), action: 'refresh', busy: true };
    case 'searching':
      return {
        tone: 'progress',
        title: messages.myPhotosSearching(),
        message: messages.myPhotosSearchProgress(summary.search?.progress_percent ?? 0),
        action: 'refresh',
        busy: true,
      };
    case 'no_matches':
      return { tone: 'neutral', title: messages.myPhotosNoMatches(), message: messages.myPhotosNoMatchesMessage(), action: 'open_face_scan', busy: false };
    case 'matches_preparing':
      return { tone: 'progress', title: messages.myPhotosPreparing(), message: messages.myPhotosPhotosFound(summary.results.match_count), action: 'none', busy: true };
    case 'matches_ready':
      return { tone: 'success', title: messages.myPhotosPhotosFound(summary.results.match_count), message: messages.myPhotosAccuracyNotice(), action: 'none', busy: false };
    case 'offline_results':
      return { tone: 'warning', title: messages.myPhotosPhotosFound(summary.results.match_count), message: messages.myPhotosOffline(), action: 'refresh', busy: false };
    case 'partial_offline_results':
      return { tone: 'warning', title: messages.myPhotosPhotosFound(summary.results.match_count), message: messages.myPhotosPartiallyOffline(), action: 'refresh', busy: false };
    case 'access_expired':
    case 'access_revoked':
      return { tone: 'danger', title: messages.myPhotosAccessRevoked(), message: messages.myPhotosStorageExplanation(), action: 'none', busy: false };
    case 'recoverable_error':
      return { tone: 'warning', title: messages.myPhotosRecoverableError(), message: messages.myPhotosStorageExplanation(), action: 'refresh', busy: false };
    case 'nonrecoverable_error':
      return { tone: 'danger', title: messages.myPhotosNonrecoverableError(), message: messages.myPhotosProviderUnavailable(), action: 'none', busy: false };
    case 'enrollment_deleted':
      return { tone: 'neutral', title: messages.myPhotosSetUpFaceScan(), message: messages.myPhotosDeleteFaceScanExplanation(), action: 'open_face_scan', busy: false };
  }
}
