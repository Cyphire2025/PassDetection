import type { CompatibleMessageCatalog } from '@/core/localization/messages';

import type { FaceScanFailure } from '../model/face-scan-machine';

export function faceScanFailureCopy(
  failure: FaceScanFailure,
  messages: CompatibleMessageCatalog,
): string {
  switch (failure) {
    case 'camera_denied': return messages.myPhotosCameraDenied();
    case 'camera_blocked': return messages.myPhotosCameraBlocked();
    case 'camera_unavailable': return messages.myPhotosCameraUnavailable();
    case 'front_camera_unavailable': return messages.myPhotosFrontCameraUnavailable();
    case 'no_face': return messages.myPhotosNoFace();
    case 'multiple_faces': return messages.myPhotosMultipleFaces();
    case 'face_too_close': return messages.myPhotosFaceTooClose();
    case 'face_too_far': return messages.myPhotosFaceTooFar();
    case 'poor_lighting': return messages.myPhotosPoorLighting();
    case 'excessive_movement': return messages.myPhotosExcessiveMovement();
    case 'network_interrupted': return messages.myPhotosNetworkInterrupted();
    case 'session_expired': return messages.myPhotosSessionExpired();
    case 'liveness_rejected': return messages.myPhotosLivenessRejected();
    case 'provider_timeout': return messages.myPhotosProviderTimeout();
    case 'provider_unavailable': return messages.myPhotosProviderTemporary();
    case 'rate_limited': return messages.myPhotosCooldown();
    case 'device_unsupported': return messages.myPhotosDeviceUnsupported();
    case 'cancelled': return messages.myPhotosScanCancelled();
    case 'backgrounded': return messages.myPhotosInterrupted();
    case 'nonrecoverable': return messages.myPhotosScanNonrecoverable();
  }
}

export function faceScanFailureBodyCopy(
  failure: FaceScanFailure,
  messages: CompatibleMessageCatalog,
): string {
  if (failure === 'device_unsupported') return messages.myPhotosDeviceUnsupportedMessage();
  if (failure === 'camera_unavailable') return messages.myPhotosCameraUnavailable();
  if (failure === 'front_camera_unavailable') return messages.myPhotosFrontCameraUnavailable();
  if (failure === 'nonrecoverable') return messages.myPhotosScanNonrecoverable();
  return messages.myPhotosRetryNewSession();
}
