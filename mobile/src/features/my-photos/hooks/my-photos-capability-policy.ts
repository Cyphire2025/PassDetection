import { onlineManager } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';

import type { CachedResult } from '../data/my-photos-repository';
import type { MyPhotosSummary } from '../api/contracts';

export type MyPhotosCapabilityDecision = Readonly<{
  visible: boolean;
  confirmedNetworkDisabled: boolean;
}>;

/**
 * The summary endpoint is the only mobile authority for this feature. Cached
 * summaries remain useful inside an already-open gallery, but they must not
 * independently reveal a hidden entry point or authorize a direct route.
 */
export function myPhotosCapabilityDecision(
  summary: CachedResult<MyPhotosSummary> | null | undefined,
  error: unknown = null,
  online = true,
): MyPhotosCapabilityDecision {
  const isFreshServerResult = online && summary?.source === 'network' && error == null;
  const enabled = summary?.value.capability.feature_enabled === true
    && summary.value.experience_state !== 'feature_unavailable';

  return {
    visible: Boolean(isFreshServerResult && enabled),
    confirmedNetworkDisabled: Boolean(
      isFreshServerResult
      && summary.value.capability.feature_enabled === false,
    ),
  };
}

export function useMyPhotosCapabilityDecision(
  summary: CachedResult<MyPhotosSummary> | null | undefined,
  error: unknown = null,
): MyPhotosCapabilityDecision {
  const online = useSyncExternalStore(
    (listener) => onlineManager.subscribe(listener),
    () => onlineManager.isOnline(),
    () => false,
  );
  return myPhotosCapabilityDecision(summary, error, online);
}

export function isMyPhotosRoute(pathname: string): boolean {
  return pathname.includes('/my-photos');
}

export function shouldBlockMyPhotosRoute(
  pathname: string,
  capability: MyPhotosCapabilityDecision,
): boolean {
  return isMyPhotosRoute(pathname) && !capability.visible;
}
