import type { MyPhotosSummary } from '../api/contracts';

export type FaceScanCapabilityBlock =
  | 'feature_unavailable'
  | 'provider_not_configured'
  | 'provider_temporarily_unavailable';

/** Server capability is authoritative even on a deep-linked scan route. */
export function faceScanCapabilityBlock(
  capability: MyPhotosSummary['capability'],
): FaceScanCapabilityBlock | null {
  if (!capability.feature_enabled) return 'feature_unavailable';
  if (capability.provider_state === 'not_configured') return 'provider_not_configured';
  if (capability.provider_state === 'temporarily_unavailable' || !capability.provider_ready) {
    return 'provider_temporarily_unavailable';
  }
  return null;
}
