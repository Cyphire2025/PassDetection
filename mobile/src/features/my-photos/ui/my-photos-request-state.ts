import { ApiError } from '@/core/api/client';
import type { CompatibleMessageCatalog } from '@/core/localization/messages';

import { isMyPhotosAccessRevokedError } from './my-photos-access-error';
import type { MyPhotosStatePresentation } from './summary-state';

const FEATURE_UNAVAILABLE_CODES = new Set([
  'MY_PHOTOS_FEATURE_UNAVAILABLE',
  'MY_PHOTOS_NOT_AVAILABLE',
  'MY_PHOTOS_NOT_ENABLED',
]);

export function myPhotosUnavailablePresentation(
  messages: CompatibleMessageCatalog,
): MyPhotosStatePresentation {
  return {
    tone: 'neutral',
    title: messages.myPhotosFeatureUnavailable(),
    message: messages.myPhotosTripShortcut(),
    action: 'none',
    busy: false,
  };
}

export function myPhotosAccessRevokedPresentation(
  messages: CompatibleMessageCatalog,
): MyPhotosStatePresentation {
  return {
    tone: 'danger',
    title: messages.myPhotosAccessRevoked(),
    message: messages.myPhotosStorageExplanation(),
    action: 'none',
    busy: false,
  };
}

/**
 * Converts failures that happen before a summary can be projected into the
 * same explicit state model used by authoritative My Photos responses.
 * Provider failures are never treated as successful enrollment or search.
 */
export function myPhotosRequestErrorPresentation(
  error: unknown,
  messages: CompatibleMessageCatalog,
): MyPhotosStatePresentation {
  if (isMyPhotosAccessRevokedError(error) || (error instanceof ApiError && error.status === 410)) {
    return myPhotosAccessRevokedPresentation(messages);
  }

  if (error instanceof ApiError && (
    error.status === 404 || FEATURE_UNAVAILABLE_CODES.has(error.code)
  )) {
    return myPhotosUnavailablePresentation(messages);
  }

  return {
    tone: 'warning',
    title: messages.myPhotosRecoverableError(),
    message: messages.myPhotosStorageExplanation(),
    action: 'refresh',
    busy: false,
  };
}
